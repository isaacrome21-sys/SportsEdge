"""Independent MLB game-total mean challenger (RESEARCH ONLY).

Repairs the *hypothesis* behind margin-proxy totals: run production depends on
each offense and its opposing run prevention, not predicted victory margin.

Inputs are retrospective final-score rows with caller-declared observation times.
Times are screened point-in-time, but this code DOES NOT authenticate those
times, prove capture provenance, validate a predictive distribution, or grant
pricing/PLAY/OFFICIAL authority. No bookmaker data enter the mean formula.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite, sqrt
from typing import Any, Iterable, Mapping


class MLBTotalCandidateError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateSpec:
    # Development defaults. Changing these requires a NEW candidate identity;
    # do not tune against the reserved evaluation period.
    recent_games: int = 30
    prior_equivalent_games: float = 25.0
    lookback_days: int = 370
    min_team_games: int = 10
    min_league_games: int = 150

    def __post_init__(self):
        if (type(self.recent_games) is not int or self.recent_games <= 0
                or type(self.lookback_days) is not int or self.lookback_days <= 0
                or type(self.min_team_games) is not int
                or not 1 <= self.min_team_games <= self.recent_games
                or type(self.min_league_games) is not int or self.min_league_games < 1
                or isinstance(self.prior_equivalent_games, bool)
                or not isinstance(self.prior_equivalent_games, (int, float))
                or not isfinite(float(self.prior_equivalent_games))
                or self.prior_equivalent_games <= 0):
            raise MLBTotalCandidateError("CANDIDATE_SPEC_INVALID")


def _timestamp(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str):
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MLBTotalCandidateError(f"{name}:INVALID") from exc
    else:
        raise MLBTotalCandidateError(f"{name}:INVALID")
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise MLBTotalCandidateError(f"{name}:TIMEZONE_REQUIRED")
    return stamp.astimezone(timezone.utc)


def _id(value: Any, name: str) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise MLBTotalCandidateError(f"{name}:IDENTITY_REQUIRED")
    out = str(value).strip()
    if not out:
        raise MLBTotalCandidateError(f"{name}:IDENTITY_REQUIRED")
    return out


def _runs(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= 100:
        raise MLBTotalCandidateError(f"{name}:NONNEGATIVE_INTEGER_REQUIRED")
    return value


@dataclass(frozen=True)
class FinalScore:
    event_id: str
    away_id: str
    home_id: str
    event_start: datetime
    final_observed: datetime
    away_runs: int
    home_runs: int

    @classmethod
    def parse(cls, raw: Mapping[str, Any]) -> "FinalScore":
        # Do not admit a pregame feature contaminated with a market quote.
        if not isinstance(raw, Mapping) or any(k in raw for k in (
            "american_odds", "model_p", "price", "market_total",
            "closing_total", "closing_spread", "spread_line",
        )):
            raise MLBTotalCandidateError("FINAL_SCORE_INPUT_INVALID_OR_MARKET_LEAK")
        if raw.get("status") != "FINAL":
            raise MLBTotalCandidateError("ONLY_FINAL_SCORES_ADMISSIBLE")
        start = _timestamp(raw.get("event_start_ts"), "event_start_ts")
        observed = _timestamp(raw.get("final_observed_ts"), "final_observed_ts")
        if observed <= start:
            raise MLBTotalCandidateError("FINAL_OBSERVED_BEFORE_EVENT_END")
        away, home = _id(raw.get("away_id"), "away_id"), _id(raw.get("home_id"), "home_id")
        if away == home:
            raise MLBTotalCandidateError("SAME_TEAM_BOTH_SIDES")
        return cls(
            event_id=_id(raw.get("event_id"), "event_id"), away_id=away, home_id=home,
            event_start=start, final_observed=observed,
            away_runs=_runs(raw.get("away_runs"), "away_runs"),
            home_runs=_runs(raw.get("home_runs"), "home_runs"),
        )


def parse_finals(history: Iterable[Mapping[str, Any]]) -> tuple[FinalScore, ...]:
    if isinstance(history, (str, bytes, Mapping)):
        raise MLBTotalCandidateError("HISTORY_SEQUENCE_REQUIRED")
    records = tuple(FinalScore.parse(row) for row in history)
    if len({row.event_id for row in records}) != len(records):
        raise MLBTotalCandidateError("DUPLICATE_EVENT_ID")
    return records


def _predict(records: tuple[FinalScore, ...], target: Mapping[str, Any],
             spec: CandidateSpec) -> dict[str, Any]:
    if not isinstance(target, Mapping):
        raise MLBTotalCandidateError("TARGET_INVALID")
    start = _timestamp(target.get("event_start_ts"), "event_start_ts")
    event_id = _id(target.get("event_id"), "event_id")
    away = _id(target.get("away_id"), "away_id")
    home = _id(target.get("home_id"), "home_id")
    if away == home:
        raise MLBTotalCandidateError("SAME_TEAM_BOTH_SIDES")
    cutoff = start - timedelta(days=spec.lookback_days)
    # Strict availability: an earlier start is not sufficient unless its
    # final result was observed strictly before this game's start.
    league = [r for r in records if cutoff <= r.event_start < start
              and r.final_observed < start and r.event_id != event_id]
    if len(league) < spec.min_league_games:
        raise MLBTotalCandidateError("LEAGUE_HISTORY_INSUFFICIENT")
    baseline_away = sum(r.away_runs for r in league) / len(league)
    baseline_home = sum(r.home_runs for r in league) / len(league)
    league_mean = (baseline_away + baseline_home) / 2.0
    if league_mean <= 0:
        raise MLBTotalCandidateError("LEAGUE_RATE_ZERO")

    def rates(team: str) -> tuple[float, float, int]:
        chosen = [r for r in league if team in (r.away_id, r.home_id)]
        chosen.sort(key=lambda r: (r.event_start, r.event_id))
        chosen = chosen[-spec.recent_games:]
        if len(chosen) < spec.min_team_games:
            raise MLBTotalCandidateError(f"TEAM_HISTORY_INSUFFICIENT:{team}")
        scored = sum(r.away_runs if r.away_id == team else r.home_runs for r in chosen)
        allowed = sum(r.home_runs if r.away_id == team else r.away_runs for r in chosen)
        denom = len(chosen) + spec.prior_equivalent_games
        return ((scored + spec.prior_equivalent_games * league_mean) / denom,
                (allowed + spec.prior_equivalent_games * league_mean) / denom,
                len(chosen))

    away_for, away_against, away_n = rates(away)
    home_for, home_against, home_n = rates(home)
    # Team attack x opposing prevention, anchored to actual home/away scoring.
    # Predict *means only*. A Poisson, correlated score path and priced EV
    # still require separate untouched-holdout validation.
    away_runs = baseline_away * (away_for / league_mean) * (home_against / league_mean)
    home_runs = baseline_home * (home_for / league_mean) * (away_against / league_mean)
    if any(not isfinite(x) or x < 0 for x in (away_runs, home_runs)):
        raise MLBTotalCandidateError("PREDICTED_RATE_INVALID")
    return {
        "schema_version": "MLB_TOTAL_OFFENSE_DEFENSE_RESEARCH_V1",
        "candidate_id": "MLB_TOTAL_OD_SHRINKAGE_30_25_V1",
        "status": "RESEARCH_ONLY_NOT_VALIDATED",
        "pricing_authorized": False,
        "official_authorized": False,
        "point_in_time_capture_authenticated": False,
        "event_id": event_id,
        "away_team_mean": away_runs, "home_team_mean": home_runs,
        "candidate_total_mean": away_runs + home_runs,
        "league_only_total_baseline": baseline_away + baseline_home,
        "league_games": len(league),
        "away_history_games": away_n,
        "home_history_games": home_n,
    }


def predict_total(history: Iterable[Mapping[str, Any]], target: Mapping[str, Any],
                  *, spec: CandidateSpec = CandidateSpec()) -> dict[str, Any]:
    return _predict(parse_finals(history), target, spec)


def prequential_backtest(history: Iterable[Mapping[str, Any]], *,
                         holdout_from: str,
                         spec: CandidateSpec = CandidateSpec()) -> dict[str, Any]:
    """Development score-only comparison. Never treats row count as independent markets.

    Walks forward at each actual kickoff, using only finals *already observed*.
    Holdout boundary must have been selected externally before inspecting data.
    """
    records = parse_finals(history)
    boundary = _timestamp(holdout_from, "holdout_from")
    trials: list[tuple[float, float, float]] = []
    refused: dict[str, int] = {}
    for row in sorted(records, key=lambda r: (r.event_start, r.event_id)):
        if row.event_start < boundary:
            continue
        target = dict(event_id=row.event_id, away_id=row.away_id,
                      home_id=row.home_id, event_start_ts=row.event_start)
        try:
            pred = _predict(records, target, spec)
        except MLBTotalCandidateError as exc:
            refused[str(exc)] = refused.get(str(exc), 0) + 1
            continue
        actual = float(row.away_runs + row.home_runs)
        trials.append((actual, pred["candidate_total_mean"],
                       pred["league_only_total_baseline"]))
    if not trials:
        raise MLBTotalCandidateError("NO_EVALUABLE_HOLDOUT_GAMES")
    def metric(index: int):
        return {
            "mae": sum(abs(row[0] - row[index]) for row in trials) / len(trials),
            "rmse": sqrt(sum((row[0] - row[index]) ** 2 for row in trials) / len(trials)),
        }
    return {
        "status": "RETROSPECTIVE_DEVELOPMENT_ONLY",
        "validated": False, "official_authorized": False,
        "point_in_time_capture_authenticated": False,
        "holdout_from": boundary.isoformat(),
        "n_distinct_games": len(trials),
        "n_refused": sum(refused.values()), "refusal_reasons": refused,
        "candidate": metric(1), "league_only_baseline": metric(2),
        "paired_market_benchmark": "MISSING",
        "claim": "No calibrated distribution or market-relative edge established",
    }
