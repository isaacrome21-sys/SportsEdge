"""Research-only PIT-safe MLB venue park factors.

This first park-factor lane estimates venue outcome-rate ratios from strictly-prior
Statcast history and shrinks them toward league average. It is intentionally a
baseline, not a promoted Model_P feature: raw venue outcome rates can still contain
team/schedule composition effects and must pass walk-forward temporal validation
before the adapter's environment validation flag may be enabled.

Governance hyperparameters below are policy choices, not empirical facts.
"""
from __future__ import annotations

from datetime import date, timedelta
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

SOURCE = "BASEBALL_SAVANT_STATCAST_PLUS_STATSAPI_VENUE"
SCHEMA_VERSION = "mlb_park_factors_v1"
MODEL_VERSION = "venue_eb_rate_ratio_v1"

DEFAULT_LOOKBACK_DAYS = 3 * 365
DEFAULT_MIN_VENUE_PA = 2000
DEFAULT_MIN_HAND_PA = 750
DEFAULT_MIN_VENUE_GAMES = 50
DEFAULT_PRIOR_EQUIVALENT_PA = 5000
DEFAULT_PRIOR_EQUIVALENT_HAND_PA = 2500
DEFAULT_PRIOR_EQUIVALENT_GAMES = 81


class MLBParkFactorsError(ValueError):
    pass


def _content_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _int(value: Any) -> int | None:
    parsed = _float(value)
    return int(parsed) if parsed is not None else None


def _date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def normalize_game_venues(
    value: Mapping[Any, Any] | Iterable[Mapping[str, Any]],
) -> dict[int, int]:
    """Return game_pk -> venue_id from a mapping or row iterable."""
    out: dict[int, int] = {}
    if isinstance(value, Mapping):
        for game_raw, venue_raw in value.items():
            game_pk = _int(game_raw)
            if isinstance(venue_raw, Mapping):
                venue_id = _int(venue_raw.get("venue_id") or venue_raw.get("venueId") or venue_raw.get("id"))
            else:
                venue_id = _int(venue_raw)
            if game_pk is not None and venue_id is not None:
                out[game_pk] = venue_id
        return out

    for row in value:
        if not isinstance(row, Mapping):
            continue
        game_pk = _int(row.get("game_pk") or row.get("gamePk"))
        venue_id = _int(row.get("venue_id") or row.get("venueId"))
        if game_pk is not None and venue_id is not None:
            out[game_pk] = venue_id
    return out


def prepare_park_history(
    pitch_rows: Iterable[Mapping[str, Any]],
    *,
    game_venues: Mapping[Any, Any] | Iterable[Mapping[str, Any]],
    target_date: date,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], dict[str, int]]:
    """Build strictly-prior terminal-PA rows plus final-score candidates by game."""
    if int(lookback_days) < 1:
        raise MLBParkFactorsError("INVALID_LOOKBACK_DAYS")
    venues = normalize_game_venues(game_venues)
    window_start = target_date - timedelta(days=int(lookback_days))
    plate_appearances: list[dict[str, Any]] = []
    games: dict[int, dict[str, Any]] = {}
    counts = {
        "input_rows": 0,
        "future_or_target_date_excluded": 0,
        "before_lookback_excluded": 0,
        "invalid_game_date_excluded": 0,
        "missing_venue_assignment_excluded": 0,
        "non_terminal_rows": 0,
        "terminal_pa_rows": 0,
    }

    for raw in pitch_rows:
        counts["input_rows"] += 1
        if not isinstance(raw, Mapping):
            counts["invalid_game_date_excluded"] += 1
            continue
        game_day = _date(raw.get("game_date"))
        if game_day is None:
            counts["invalid_game_date_excluded"] += 1
            continue
        if game_day >= target_date:
            counts["future_or_target_date_excluded"] += 1
            continue
        if game_day < window_start:
            counts["before_lookback_excluded"] += 1
            continue
        game_pk = _int(raw.get("game_pk"))
        venue_id = venues.get(game_pk) if game_pk is not None else None
        if game_pk is None or venue_id is None:
            counts["missing_venue_assignment_excluded"] += 1
            continue

        game = games.setdefault(
            int(game_pk),
            {
                "game_pk": int(game_pk),
                "game_date": game_day.isoformat(),
                "venue_id": int(venue_id),
                "max_home_score": None,
                "max_away_score": None,
            },
        )
        home_score = _float(raw.get("post_home_score"))
        away_score = _float(raw.get("post_away_score"))
        if home_score is not None:
            current = game["max_home_score"]
            game["max_home_score"] = home_score if current is None else max(float(current), home_score)
        if away_score is not None:
            current = game["max_away_score"]
            game["max_away_score"] = away_score if current is None else max(float(current), away_score)

        event = str(raw.get("events") or "").strip().lower()
        if not event:
            counts["non_terminal_rows"] += 1
            continue
        stand = str(raw.get("stand") or "").strip().upper()
        plate_appearances.append(
            {
                "game_pk": int(game_pk),
                "game_date": game_day.isoformat(),
                "venue_id": int(venue_id),
                "event": event,
                "stand": stand if stand in {"L", "R"} else None,
            }
        )
        counts["terminal_pa_rows"] += 1

    return plate_appearances, games, counts


def _rate_factor(
    *,
    venue_events: int,
    venue_pa: int,
    league_events: int,
    league_pa: int,
    prior_equivalent_pa: int,
) -> float | None:
    if venue_pa <= 0 or league_pa <= 0 or int(prior_equivalent_pa) < 1:
        return None
    league_rate = league_events / league_pa
    if league_rate <= 0.0:
        return None
    smoothed = (venue_events + league_rate * int(prior_equivalent_pa)) / (
        venue_pa + int(prior_equivalent_pa)
    )
    return smoothed / league_rate


def _runs_factor(
    *,
    venue_runs: float,
    venue_games: int,
    league_runs: float,
    league_games: int,
    prior_equivalent_games: int,
) -> float | None:
    if venue_games <= 0 or league_games <= 0 or int(prior_equivalent_games) < 1:
        return None
    league_rate = league_runs / league_games
    if league_rate <= 0.0:
        return None
    smoothed = (venue_runs + league_rate * int(prior_equivalent_games)) / (
        venue_games + int(prior_equivalent_games)
    )
    return smoothed / league_rate


def build_park_factors(
    *,
    pitch_rows: Iterable[Mapping[str, Any]],
    game_venues: Mapping[Any, Any] | Iterable[Mapping[str, Any]],
    target_date: date,
    venue_id: int,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    min_venue_pa: int = DEFAULT_MIN_VENUE_PA,
    min_hand_pa: int = DEFAULT_MIN_HAND_PA,
    min_venue_games: int = DEFAULT_MIN_VENUE_GAMES,
    prior_equivalent_pa: int = DEFAULT_PRIOR_EQUIVALENT_PA,
    prior_equivalent_hand_pa: int = DEFAULT_PRIOR_EQUIVALENT_HAND_PA,
    prior_equivalent_games: int = DEFAULT_PRIOR_EQUIVALENT_GAMES,
) -> dict[str, Any]:
    """Return sample-gated empirical-Bayes park factor ratios for one venue."""
    for name, value in (
        ("min_venue_pa", min_venue_pa),
        ("min_hand_pa", min_hand_pa),
        ("min_venue_games", min_venue_games),
        ("prior_equivalent_pa", prior_equivalent_pa),
        ("prior_equivalent_hand_pa", prior_equivalent_hand_pa),
        ("prior_equivalent_games", prior_equivalent_games),
    ):
        if int(value) < 1:
            raise MLBParkFactorsError(f"INVALID_{name.upper()}")

    rows, games, exclusions = prepare_park_history(
        pitch_rows,
        game_venues=game_venues,
        target_date=target_date,
        lookback_days=int(lookback_days),
    )
    target_venue = int(venue_id)
    venue_rows = [row for row in rows if int(row["venue_id"]) == target_venue]
    if not rows or not venue_rows:
        return {
            "schema_version": SCHEMA_VERSION,
            "model_version": MODEL_VERSION,
            "source": SOURCE,
            "target_date": target_date.isoformat(),
            "venue_id": target_venue,
            "status": "MISSING_VENUE_HISTORY",
            "values": {},
            "exclusions": exclusions,
            "model_p_eligible": False,
            "promotion_status": "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION",
        }

    def count_event(materialized: list[dict[str, Any]], events: set[str], *, hand: str | None = None) -> tuple[int, int]:
        subset = materialized if hand is None else [row for row in materialized if row.get("stand") == hand]
        return sum(1 for row in subset if row["event"] in events), len(subset)

    league_hr, league_pa = count_event(rows, {"home_run"})
    venue_hr, venue_pa = count_event(venue_rows, {"home_run"})
    league_1b, _ = count_event(rows, {"single"})
    venue_1b, _ = count_event(venue_rows, {"single"})
    league_2b3b, _ = count_event(rows, {"double", "triple"})
    venue_2b3b, _ = count_event(venue_rows, {"double", "triple"})

    league_l_hr, league_l_pa = count_event(rows, {"home_run"}, hand="L")
    venue_l_hr, venue_l_pa = count_event(venue_rows, {"home_run"}, hand="L")
    league_r_hr, league_r_pa = count_event(rows, {"home_run"}, hand="R")
    venue_r_hr, venue_r_pa = count_event(venue_rows, {"home_run"}, hand="R")

    scored_games = [
        game for game in games.values()
        if game.get("max_home_score") is not None and game.get("max_away_score") is not None
    ]
    venue_scored_games = [game for game in scored_games if int(game["venue_id"]) == target_venue]
    league_runs = sum(float(game["max_home_score"]) + float(game["max_away_score"]) for game in scored_games)
    venue_runs = sum(float(game["max_home_score"]) + float(game["max_away_score"]) for game in venue_scored_games)

    overall_sample_pass = venue_pa >= int(min_venue_pa)
    l_sample_pass = venue_l_pa >= int(min_hand_pa)
    r_sample_pass = venue_r_pa >= int(min_hand_pa)
    game_sample_pass = len(venue_scored_games) >= int(min_venue_games)

    values = {
        "park_hr_factor": round(_rate_factor(
            venue_events=venue_hr, venue_pa=venue_pa,
            league_events=league_hr, league_pa=league_pa,
            prior_equivalent_pa=int(prior_equivalent_pa),
        ), 6) if overall_sample_pass and _rate_factor(
            venue_events=venue_hr, venue_pa=venue_pa,
            league_events=league_hr, league_pa=league_pa,
            prior_equivalent_pa=int(prior_equivalent_pa),
        ) is not None else None,
        "park_hr_factor_lhb": round(_rate_factor(
            venue_events=venue_l_hr, venue_pa=venue_l_pa,
            league_events=league_l_hr, league_pa=league_l_pa,
            prior_equivalent_pa=int(prior_equivalent_hand_pa),
        ), 6) if l_sample_pass and _rate_factor(
            venue_events=venue_l_hr, venue_pa=venue_l_pa,
            league_events=league_l_hr, league_pa=league_l_pa,
            prior_equivalent_pa=int(prior_equivalent_hand_pa),
        ) is not None else None,
        "park_hr_factor_rhb": round(_rate_factor(
            venue_events=venue_r_hr, venue_pa=venue_r_pa,
            league_events=league_r_hr, league_pa=league_r_pa,
            prior_equivalent_pa=int(prior_equivalent_hand_pa),
        ), 6) if r_sample_pass and _rate_factor(
            venue_events=venue_r_hr, venue_pa=venue_r_pa,
            league_events=league_r_hr, league_pa=league_r_pa,
            prior_equivalent_pa=int(prior_equivalent_hand_pa),
        ) is not None else None,
        "park_runs_factor": round(_runs_factor(
            venue_runs=venue_runs, venue_games=len(venue_scored_games),
            league_runs=league_runs, league_games=len(scored_games),
            prior_equivalent_games=int(prior_equivalent_games),
        ), 6) if game_sample_pass and _runs_factor(
            venue_runs=venue_runs, venue_games=len(venue_scored_games),
            league_runs=league_runs, league_games=len(scored_games),
            prior_equivalent_games=int(prior_equivalent_games),
        ) is not None else None,
        "park_1b_factor": round(_rate_factor(
            venue_events=venue_1b, venue_pa=venue_pa,
            league_events=league_1b, league_pa=league_pa,
            prior_equivalent_pa=int(prior_equivalent_pa),
        ), 6) if overall_sample_pass and _rate_factor(
            venue_events=venue_1b, venue_pa=venue_pa,
            league_events=league_1b, league_pa=league_pa,
            prior_equivalent_pa=int(prior_equivalent_pa),
        ) is not None else None,
        "park_2b_3b_factor": round(_rate_factor(
            venue_events=venue_2b3b, venue_pa=venue_pa,
            league_events=league_2b3b, league_pa=league_pa,
            prior_equivalent_pa=int(prior_equivalent_pa),
        ), 6) if overall_sample_pass and _rate_factor(
            venue_events=venue_2b3b, venue_pa=venue_pa,
            league_events=league_2b3b, league_pa=league_pa,
            prior_equivalent_pa=int(prior_equivalent_pa),
        ) is not None else None,
    }

    source_rows = sorted(
        ({
            "game_pk": row["game_pk"], "game_date": row["game_date"],
            "venue_id": row["venue_id"], "event": row["event"], "stand": row["stand"],
        } for row in rows),
        key=lambda row: (row["game_date"], row["game_pk"], row["event"], str(row["stand"])),
    )
    source_games = sorted(
        ({
            "game_pk": game["game_pk"], "game_date": game["game_date"],
            "venue_id": game["venue_id"], "max_home_score": game["max_home_score"],
            "max_away_score": game["max_away_score"],
        } for game in games.values()),
        key=lambda game: (game["game_date"], game["game_pk"]),
    )
    source_sha = _content_sha({"plate_appearances": source_rows, "games": source_games})
    missing = tuple(name for name, value in values.items() if value is None)

    return {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "source": SOURCE,
        "target_date": target_date.isoformat(),
        "lookback_days": int(lookback_days),
        "venue_id": target_venue,
        "status": "AVAILABLE" if not missing else "INCOMPLETE",
        "values": values,
        "missing_factors": missing,
        "sample": {
            "venue_pa": venue_pa,
            "venue_lhb_pa": venue_l_pa,
            "venue_rhb_pa": venue_r_pa,
            "venue_scored_games": len(venue_scored_games),
            "league_pa": league_pa,
            "league_scored_games": len(scored_games),
        },
        "sample_policy": {
            "min_venue_pa": int(min_venue_pa),
            "min_hand_pa": int(min_hand_pa),
            "min_venue_games": int(min_venue_games),
            "prior_equivalent_pa": int(prior_equivalent_pa),
            "prior_equivalent_hand_pa": int(prior_equivalent_hand_pa),
            "prior_equivalent_games": int(prior_equivalent_games),
            "policy_note": "Governance hyperparameters; not empirical facts.",
        },
        "source_subset_sha256": source_sha,
        "exclusions": exclusions,
        "model_p_eligible": False,
        "promotion_status": "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION",
        "limitations": (
            "baseline venue-rate factors may retain team and schedule composition effects",
            "temporal validation is required before environment_feature_validation.park_factors may be true",
        ),
    }
