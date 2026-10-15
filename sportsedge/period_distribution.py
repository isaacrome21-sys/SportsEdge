"""Shared first-3 / first-7 innings score distribution and read-outs.

This is the period generalization of sportsedge.f5_distribution, built
for the DraftKings 1st-3-innings and 1st-7-innings market sets
(F3_MONEYLINE / F3_RUN_LINE / F3_TOTALS / F3_TEAM_TOTALS and the F7
equivalents; enumerated in the Oct 13 2026 DraftKings catalog capture,
CATALOG_MLB.md: "Same structure exists for 1st 3 innings and 1st 7
innings (ML, team totals, run line, BTTS ladder, winning margin)").

The construction is identical in kind to the F5 candidate and never
scales a full-game mean: it is built from actual strictly-prior
inning-level scores through the period (3 or 7 completed innings).
Each team's scoring marginal is an equal blend of its own period
runs-for empirical PMF and the opponent's period runs-allowed
empirical PMF, optionally smoothed toward a strictly-prior league
period PMF (m30, the F5 recipe). The two marginals form one joint
period score state reused by all period market read-outs.

The F5 module is deliberately NOT modified: its distribution SHA
identity is byte-sensitive for existing consumers. This module carries
its own version strings per period.

Research only: nothing here validates, promotes or prices anything.
Eligibility is governed by the deployment registry, consulted by the
binding layer (sportsedge.mlb_period_quote_binding).
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .mlb_empirical_bayes import posterior_settlement_mass
from .source_lineage import canonical_json_sha256

PERIOD_INNINGS = (3, 7)
MIN_HISTORY_GAMES = 10
LEAGUE_PRIOR_STRENGTH = 30
MIN_LEAGUE_HALVES = 200


def period_markets(innings: int) -> frozenset:
    if innings not in PERIOD_INNINGS:
        raise PeriodDistributionError(f"unsupported period: {innings}")
    prefix = f"F{innings}"
    return frozenset({
        f"{prefix}_MONEYLINE", f"{prefix}_RUN_LINE",
        f"{prefix}_TOTALS", f"{prefix}_TEAM_TOTALS",
    })


F3_MARKETS = period_markets(3)
F7_MARKETS = period_markets(7)
PERIOD_MARKETS = F3_MARKETS | F7_MARKETS


def distribution_version(innings: int, *, league_prior_strength: int = LEAGUE_PRIOR_STRENGTH) -> str:
    if league_prior_strength == LEAGUE_PRIOR_STRENGTH:
        return f"mlb_period_empirical_state_v1_m30_league_prior_f{innings}"
    return f"mlb_period_empirical_state_v1_candidate_f{innings}"


def readout_version(innings: int) -> str:
    return f"mlb_period_readout_v1_jeffreys_f{innings}"


def innings_for_market(market: str) -> int:
    name = str(market or "").strip().upper()
    if name in F3_MARKETS:
        return 3
    if name in F7_MARKETS:
        return 7
    raise PeriodDistributionError(f"unsupported period market: {market}")


class PeriodDistributionError(ValueError):
    pass


@dataclass(frozen=True)
class PeriodDistribution:
    innings: int
    away_history_games: int
    home_history_games: int
    joint_score_pmf: dict[str, float]
    distribution_sha256: str
    distribution_version: str


@dataclass(frozen=True)
class PeriodReadout:
    market: str
    line: float | None
    side: str
    probability: float
    push_probability: float
    distribution_sha256: str
    readout_sha256: str
    readout_version: str


def _count_pool(value: Any, field: str) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PeriodDistributionError(f"{field} must be a sequence")
    if len(value) < MIN_HISTORY_GAMES:
        raise PeriodDistributionError(
            f"{field} requires at least {MIN_HISTORY_GAMES} strictly-prior games"
        )
    out: list[int] = []
    for index, raw in enumerate(value):
        if isinstance(raw, bool):
            raise PeriodDistributionError(f"{field}[{index}] must be integer >= 0")
        try:
            numeric = float(raw)
        except (TypeError, ValueError) as exc:
            raise PeriodDistributionError(f"{field}[{index}] must be integer >= 0") from exc
        if not isfinite(numeric) or numeric < 0 or numeric != int(numeric):
            raise PeriodDistributionError(f"{field}[{index}] must be integer >= 0")
        out.append(int(numeric))
    return tuple(out)


def _empirical_pmf(values: tuple[int, ...]) -> dict[int, float]:
    counts: dict[int, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    n = len(values)
    return {key: count / n for key, count in counts.items()}


def _league_pmf(value: Any) -> dict[int, float]:
    if not isinstance(value, Mapping) or not value:
        raise PeriodDistributionError("league_period_pmf must be a non-empty mapping")
    out: dict[int, float] = {}
    total = 0.0
    for raw_key, raw_p in value.items():
        try:
            key = int(raw_key)
            probability = float(raw_p)
        except (TypeError, ValueError) as exc:
            raise PeriodDistributionError("league_period_pmf contains invalid state") from exc
        if key < 0 or not isfinite(probability) or probability < 0:
            raise PeriodDistributionError("league_period_pmf contains invalid probability")
        out[key] = out.get(key, 0.0) + probability
        total += probability
    if abs(total - 1.0) > 1e-9:
        raise PeriodDistributionError("league_period_pmf does not conserve probability")
    return out


def _smoothed_pmf(values: tuple[int, ...], league: Mapping[int, float]) -> dict[int, float]:
    counts: dict[int, float] = {}
    for value in values:
        counts[value] = counts.get(value, 0.0) + 1.0
    keys = set(counts) | set(league)
    denom = float(len(values) + LEAGUE_PRIOR_STRENGTH)
    out = {
        key: (counts.get(key, 0.0) + LEAGUE_PRIOR_STRENGTH * float(league.get(key, 0.0))) / denom
        for key in keys
    }
    if abs(sum(out.values()) - 1.0) > 1e-12:
        raise PeriodDistributionError("smoothed period marginal does not conserve probability")
    return out


def _blend(left: dict[int, float], right: dict[int, float]) -> dict[int, float]:
    keys = set(left) | set(right)
    out = {key: 0.5 * left.get(key, 0.0) + 0.5 * right.get(key, 0.0) for key in keys}
    if abs(sum(out.values()) - 1.0) > 1e-12:
        raise PeriodDistributionError("blended period marginal does not conserve probability")
    return out


def build_period_distribution(
    features: Mapping[str, Any],
    *,
    innings: int,
    league_prior_strength: int = 0,
) -> PeriodDistribution:
    """Build the joint period score state for innings 3 or 7.

    Feature arrays are strictly-prior period runs (through inning
    ``innings``): away_period_runs_for / away_period_runs_against /
    home_period_runs_for / home_period_runs_against, plus, when the
    m30 league prior is requested, league_period_pmf /
    league_prior_halves / league_prior_strength.
    """
    if innings not in PERIOD_INNINGS:
        raise PeriodDistributionError(f"unsupported period: {innings}")
    if not isinstance(features, Mapping):
        raise PeriodDistributionError("period features must be an object")
    away_for = _count_pool(features.get("away_period_runs_for"), "away_period_runs_for")
    away_against = _count_pool(features.get("away_period_runs_against"), "away_period_runs_against")
    home_for = _count_pool(features.get("home_period_runs_for"), "home_period_runs_for")
    home_against = _count_pool(features.get("home_period_runs_against"), "home_period_runs_against")
    if len(away_for) != len(away_against):
        raise PeriodDistributionError("away period history arrays must align")
    if len(home_for) != len(home_against):
        raise PeriodDistributionError("home period history arrays must align")
    if league_prior_strength not in {0, LEAGUE_PRIOR_STRENGTH}:
        raise PeriodDistributionError("unsupported league prior strength")
    league_halves = 0
    league: dict[int, float] | None = None
    if league_prior_strength == LEAGUE_PRIOR_STRENGTH:
        try:
            league_halves = int(features.get("league_prior_halves"))
            league_strength = int(features.get("league_prior_strength"))
        except (TypeError, ValueError) as exc:
            raise PeriodDistributionError("league prior identity fields required") from exc
        if league_halves < MIN_LEAGUE_HALVES:
            raise PeriodDistributionError(
                f"league prior requires at least {MIN_LEAGUE_HALVES} team-halves"
            )
        if league_strength != LEAGUE_PRIOR_STRENGTH:
            raise PeriodDistributionError("league prior strength drift")
        league = _league_pmf(features.get("league_period_pmf"))
        away_for_pmf = _smoothed_pmf(away_for, league)
        home_against_pmf = _smoothed_pmf(home_against, league)
        home_for_pmf = _smoothed_pmf(home_for, league)
        away_against_pmf = _smoothed_pmf(away_against, league)
    else:
        away_for_pmf = _empirical_pmf(away_for)
        home_against_pmf = _empirical_pmf(home_against)
        home_for_pmf = _empirical_pmf(home_for)
        away_against_pmf = _empirical_pmf(away_against)

    away_scoring = _blend(away_for_pmf, home_against_pmf)
    home_scoring = _blend(home_for_pmf, away_against_pmf)
    joint: dict[str, float] = {}
    for away_runs, away_p in sorted(away_scoring.items()):
        for home_runs, home_p in sorted(home_scoring.items()):
            joint[f"{away_runs},{home_runs}"] = away_p * home_p
    if abs(sum(joint.values()) - 1.0) > 1e-12:
        raise PeriodDistributionError("period joint score PMF does not conserve probability")

    version = distribution_version(innings, league_prior_strength=league_prior_strength)
    digest_payload: dict[str, Any] = {
        "version": version,
        "innings": innings,
        "blend_policy": "equal_offense_opponent_allowed_empirical_marginals",
        "joint_score_pmf": joint,
    }
    if league_prior_strength == LEAGUE_PRIOR_STRENGTH:
        digest_payload["blend_policy"] = (
            "equal_offense_opponent_allowed_m30_league_smoothed_marginals")
        digest_payload["league_prior_strength"] = LEAGUE_PRIOR_STRENGTH
        digest_payload["league_prior_halves"] = int(league_halves)
        digest_payload["league_period_pmf"] = {
            str(k): float(v) for k, v in sorted(league.items())}
    digest = canonical_json_sha256(digest_payload)
    return PeriodDistribution(
        innings=innings,
        away_history_games=len(away_for),
        home_history_games=len(home_for),
        joint_score_pmf=joint,
        distribution_sha256=digest,
        distribution_version=version,
    )


def _states(distribution: PeriodDistribution):
    total = 0.0
    rows: list[tuple[int, int, float]] = []
    for key, raw_p in distribution.joint_score_pmf.items():
        try:
            away_text, home_text = str(key).split(",", 1)
            away_runs = int(away_text)
            home_runs = int(home_text)
            probability = float(raw_p)
        except (TypeError, ValueError) as exc:
            raise PeriodDistributionError("invalid period joint score state") from exc
        if away_runs < 0 or home_runs < 0 or not isfinite(probability) or probability < 0:
            raise PeriodDistributionError("invalid period joint score state")
        total += probability
        rows.append((away_runs, home_runs, probability))
    if abs(total - 1.0) > 1e-12:
        raise PeriodDistributionError("period joint score PMF does not conserve probability")
    return tuple(rows)


def _line(value: Any, *, required: bool) -> float | None:
    if value is None and not required:
        return None
    if isinstance(value, bool):
        raise PeriodDistributionError("line must be finite numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PeriodDistributionError("line must be finite numeric") from exc
    if not isfinite(out):
        raise PeriodDistributionError("line must be finite numeric")
    return out


def read_period_probability(
    distribution: PeriodDistribution,
    *,
    market: str,
    line: Any = None,
    side: str,
    team_side: str | None = None,
) -> PeriodReadout:
    if not isinstance(distribution, PeriodDistribution):
        raise PeriodDistributionError("distribution must be PeriodDistribution")
    market = str(market or "").upper()
    side = str(side or "").upper()
    innings = innings_for_market(market)
    if innings != distribution.innings:
        raise PeriodDistributionError(
            f"market {market} does not belong to the F{distribution.innings} distribution")
    rows = _states(distribution)
    prefix = f"F{innings}"

    if market == f"{prefix}_MONEYLINE":
        resolved_line = _line(line, required=False)
        if side in {"HOME", "HOME_ML"}:
            probability = sum(p for away, home, p in rows if home > away)
        elif side in {"AWAY", "AWAY_ML"}:
            probability = sum(p for away, home, p in rows if away > home)
        else:
            raise PeriodDistributionError(f"{prefix} moneyline side must be HOME or AWAY")
        push_probability = sum(p for away, home, p in rows if away == home)
    elif market == f"{prefix}_RUN_LINE":
        resolved_line = _line(line, required=True)
        assert resolved_line is not None
        if side in {"HOME", "HOME_RL"}:
            margins = tuple((home - away) + resolved_line for away, home, _ in rows)
        elif side in {"AWAY", "AWAY_RL"}:
            margins = tuple((away - home) + resolved_line for away, home, _ in rows)
        else:
            raise PeriodDistributionError(f"{prefix} run-line side must be HOME or AWAY")
        probability = sum(p for (_, _, p), value in zip(rows, margins) if value > 0)
        push_probability = sum(p for (_, _, p), value in zip(rows, margins) if abs(value) < 1e-12)
    elif market == f"{prefix}_TOTALS":
        resolved_line = _line(line, required=True)
        assert resolved_line is not None
        if resolved_line < 0:
            raise PeriodDistributionError(f"{prefix} totals line must be >= 0")
        if side == "OVER":
            probability = sum(p for away, home, p in rows if away + home > resolved_line)
        elif side == "UNDER":
            probability = sum(p for away, home, p in rows if away + home < resolved_line)
        else:
            raise PeriodDistributionError(f"{prefix} totals side must be OVER or UNDER")
        push_probability = sum(p for away, home, p in rows if abs(away + home - resolved_line) < 1e-12)
    else:
        resolved_line = _line(line, required=True)
        assert resolved_line is not None
        if resolved_line < 0:
            raise PeriodDistributionError(f"{prefix} team-total line must be >= 0")
        selected = str(team_side or "").upper()
        if selected not in {"AWAY", "HOME"}:
            raise PeriodDistributionError(f"{prefix} team-total team_side must be AWAY or HOME")
        values = tuple(away if selected == "AWAY" else home for away, home, _ in rows)
        if side == "OVER":
            probability = sum(p for (_, _, p), value in zip(rows, values) if value > resolved_line)
        elif side == "UNDER":
            probability = sum(p for (_, _, p), value in zip(rows, values) if value < resolved_line)
        else:
            raise PeriodDistributionError(f"{prefix} team-total side must be OVER or UNDER")
        push_probability = sum(p for (_, _, p), value in zip(rows, values) if abs(value - resolved_line) < 1e-12)

    if probability < -1e-12 or push_probability < -1e-12 or probability + push_probability > 1.0 + 1e-9:
        raise PeriodDistributionError("period readout probability mass invalid")

    # Same Jeffreys stabilization discipline as the F5 readout: the score
    # state is built from only 10-30 prior games per club, so a sparse
    # empirical state cannot manufacture near-certainty.
    push_possible = (
        market == f"{prefix}_MONEYLINE"
        or (resolved_line is not None and float(resolved_line).is_integer())
    )
    raw_probability = float(probability)
    raw_push_probability = float(push_probability)
    loss_probability = max(0.0, 1.0 - raw_probability - raw_push_probability)
    posterior = posterior_settlement_mass(
        over_mass=raw_probability,
        under_mass=loss_probability,
        push_mass=raw_push_probability,
        effective_n=float(min(distribution.away_history_games, distribution.home_history_games)),
        has_push=push_possible,
    )
    probability = float(posterior["p_over"])
    push_probability = float(posterior["p_push"])

    version = readout_version(innings)
    readout_sha = canonical_json_sha256({
        "version": version,
        "distribution_sha256": distribution.distribution_sha256,
        "market": market,
        "line": resolved_line,
        "side": side,
        "team_side": str(team_side or "").upper() or None,
        "probability": float(probability),
        "push_probability": float(push_probability),
        "raw_probability": raw_probability,
        "raw_push_probability": raw_push_probability,
        "posterior_prior": posterior["prior"],
        "effective_history_games": float(min(distribution.away_history_games, distribution.home_history_games)),
    })
    return PeriodReadout(
        market=market,
        line=resolved_line,
        side=side,
        probability=float(probability),
        push_probability=float(push_probability),
        distribution_sha256=distribution.distribution_sha256,
        readout_sha256=readout_sha,
        readout_version=version,
    )
