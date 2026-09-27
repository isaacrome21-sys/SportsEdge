"""Research-only PIT-safe MLB plate-umpire walk tendency.

The feature is intentionally separate from called-strike bias. It estimates how
frequently batters walk under an umpire relative to an expected walk probability
based on the batter's and pitcher's prior walk propensities.

All source plate appearances must precede the target date. Intentional walks are
excluded because they do not represent a plate-umpire ball/strike tendency. The
result is shrunk toward zero, sample-gated, and remains ineligible for Model_P until
walk-forward temporal validation explicitly promotes it.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import hashlib
import json
import math
from typing import Any, Iterable, Mapping

from .mlb_umpire_zone_tendency import normalize_game_umpires

SOURCE = "BASEBALL_SAVANT_STATCAST_PLUS_STATSAPI_HP_UMPIRE"
SCHEMA_VERSION = "mlb_umpire_walk_tendency_v1"
MODEL_VERSION = "batter_pitcher_eb_walk_residual_v1"
DEFAULT_MIN_PLATE_APPEARANCES = 500
DEFAULT_PRIOR_EQUIVALENT_PA = 1000
DEFAULT_BATTER_PRIOR_PA = 120
DEFAULT_PITCHER_PRIOR_PA = 180
PROB_EPS = 1e-6


class MLBUmpireWalkTendencyError(ValueError):
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


def _logit(probability: float) -> float:
    p = min(1.0 - PROB_EPS, max(PROB_EPS, float(probability)))
    return math.log(p / (1.0 - p))


def _logistic(value: float) -> float:
    z = max(-30.0, min(30.0, float(value)))
    return 1.0 / (1.0 + math.exp(-z))


def prepare_plate_appearances(
    pitch_rows: Iterable[Mapping[str, Any]],
    *,
    game_umpires: Mapping[Any, Any] | Iterable[Mapping[str, Any]],
    target_date: date,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Extract strictly-prior, umpire-bound terminal PAs suitable for walk residuals."""
    assignments = normalize_game_umpires(game_umpires)
    selected: list[dict[str, Any]] = []
    counts = {
        "input_rows": 0,
        "future_or_target_date_excluded": 0,
        "non_terminal_excluded": 0,
        "intentional_walk_excluded": 0,
        "invalid_game_date_excluded": 0,
        "missing_umpire_assignment_excluded": 0,
        "missing_batter_or_pitcher_excluded": 0,
    }
    for raw in pitch_rows:
        counts["input_rows"] += 1
        if not isinstance(raw, Mapping):
            counts["non_terminal_excluded"] += 1
            continue
        event = str(raw.get("events") or "").strip().lower()
        if not event:
            counts["non_terminal_excluded"] += 1
            continue
        if event == "intent_walk":
            counts["intentional_walk_excluded"] += 1
            continue
        game_day = _date(raw.get("game_date"))
        if game_day is None:
            counts["invalid_game_date_excluded"] += 1
            continue
        if game_day >= target_date:
            counts["future_or_target_date_excluded"] += 1
            continue
        game_pk = _int(raw.get("game_pk"))
        umpire_id = assignments.get(game_pk) if game_pk is not None else None
        if umpire_id is None:
            counts["missing_umpire_assignment_excluded"] += 1
            continue
        batter = _int(raw.get("batter"))
        pitcher = _int(raw.get("pitcher"))
        if batter is None or pitcher is None:
            counts["missing_batter_or_pitcher_excluded"] += 1
            continue
        selected.append({
            "game_pk": int(game_pk),
            "game_date": game_day.isoformat(),
            "umpire_id": int(umpire_id),
            "batter": int(batter),
            "pitcher": int(pitcher),
            "event": event,
            "walk": 1 if event == "walk" else 0,
        })
    return selected, counts


def _entity_counts(rows: Iterable[Mapping[str, Any]], key: str) -> dict[int, tuple[int, int]]:
    counts: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for row in rows:
        entity = int(row[key])
        counts[entity][0] += 1
        counts[entity][1] += int(row["walk"])
    return {entity: (values[0], values[1]) for entity, values in counts.items()}


def _eb_rate(*, walks: int, pa: int, league_rate: float, prior_pa: int) -> float:
    if pa < 0 or walks < 0 or walks > pa or prior_pa < 1:
        raise MLBUmpireWalkTendencyError("INVALID_EB_COUNTS")
    return (walks + float(league_rate) * int(prior_pa)) / (pa + int(prior_pa))


def expected_walk_probabilities(
    rows: Iterable[Mapping[str, Any]],
    *,
    batter_prior_pa: int = DEFAULT_BATTER_PRIOR_PA,
    pitcher_prior_pa: int = DEFAULT_PITCHER_PRIOR_PA,
) -> list[float]:
    """Return leave-one-out batter/pitcher adjusted expected walk probabilities.

    For each PA, batter and pitcher walk propensities are empirical-Bayes shrunk to
    a leave-one-out league walk rate. The two deviations are combined additively on
    the log-odds scale. The current PA outcome is removed from every component used
    to score that PA, preventing self-outcome leakage.
    """
    materialized = [dict(row) for row in rows]
    if len(materialized) < 3:
        raise MLBUmpireWalkTendencyError("INSUFFICIENT_PRIOR_PLATE_APPEARANCES")
    if int(batter_prior_pa) < 1 or int(pitcher_prior_pa) < 1:
        raise MLBUmpireWalkTendencyError("INVALID_PROPENSITY_PRIOR")

    total_pa = len(materialized)
    total_walks = sum(int(row["walk"]) for row in materialized)
    if total_walks <= 0 or total_walks >= total_pa:
        raise MLBUmpireWalkTendencyError("WALK_MODEL_REQUIRES_WALKS_AND_NON_WALKS")

    batter_counts = _entity_counts(materialized, "batter")
    pitcher_counts = _entity_counts(materialized, "pitcher")
    expected: list[float] = []
    for row in materialized:
        observed = int(row["walk"])
        league_pa = total_pa - 1
        league_walks = total_walks - observed
        if league_pa <= 0 or league_walks <= 0 or league_walks >= league_pa:
            raise MLBUmpireWalkTendencyError("DEGENERATE_LEAVE_ONE_OUT_LEAGUE_RATE")
        league_rate = league_walks / league_pa

        batter = int(row["batter"])
        pitcher = int(row["pitcher"])
        batter_pa, batter_walks = batter_counts[batter]
        pitcher_pa, pitcher_walks = pitcher_counts[pitcher]
        batter_rate = _eb_rate(
            walks=batter_walks - observed,
            pa=batter_pa - 1,
            league_rate=league_rate,
            prior_pa=int(batter_prior_pa),
        )
        pitcher_rate = _eb_rate(
            walks=pitcher_walks - observed,
            pa=pitcher_pa - 1,
            league_rate=league_rate,
            prior_pa=int(pitcher_prior_pa),
        )
        expected_logit = (
            _logit(league_rate)
            + (_logit(batter_rate) - _logit(league_rate))
            + (_logit(pitcher_rate) - _logit(league_rate))
        )
        expected.append(_logistic(expected_logit))
    return expected


def build_umpire_walk_tendency(
    *,
    pitch_rows: Iterable[Mapping[str, Any]],
    game_umpires: Mapping[Any, Any] | Iterable[Mapping[str, Any]],
    target_date: date,
    umpire_id: int,
    min_plate_appearances: int = DEFAULT_MIN_PLATE_APPEARANCES,
    prior_equivalent_pa: int = DEFAULT_PRIOR_EQUIVALENT_PA,
    batter_prior_pa: int = DEFAULT_BATTER_PRIOR_PA,
    pitcher_prior_pa: int = DEFAULT_PITCHER_PRIOR_PA,
) -> dict[str, Any]:
    if int(min_plate_appearances) < 1 or int(prior_equivalent_pa) < 1:
        raise MLBUmpireWalkTendencyError("INVALID_SAMPLE_POLICY")
    selected, exclusions = prepare_plate_appearances(
        pitch_rows,
        game_umpires=game_umpires,
        target_date=target_date,
    )
    base = {
        "schema_version": SCHEMA_VERSION,
        "model_version": MODEL_VERSION,
        "source": SOURCE,
        "target_date": target_date.isoformat(),
        "umpire_id": int(umpire_id),
        "model_p_eligible": False,
        "promotion_status": "RESEARCH_ONLY_UNTIL_TEMPORAL_VALIDATION",
        "exclusions": exclusions,
    }
    if len(selected) < 3:
        return {
            **base,
            "status": "MISSING_PRIOR_PLATE_APPEARANCES",
            "walk_tendency": None,
        }

    expected = expected_walk_probabilities(
        selected,
        batter_prior_pa=int(batter_prior_pa),
        pitcher_prior_pa=int(pitcher_prior_pa),
    )
    target_indices = [
        idx for idx, row in enumerate(selected)
        if int(row["umpire_id"]) == int(umpire_id)
    ]
    source_rows = [
        {
            "game_pk": int(row["game_pk"]),
            "game_date": str(row["game_date"]),
            "umpire_id": int(row["umpire_id"]),
            "batter": int(row["batter"]),
            "pitcher": int(row["pitcher"]),
            "event": str(row["event"]),
        }
        for row in selected
    ]
    source_sha = _content_sha(source_rows)
    if not target_indices:
        return {
            **base,
            "status": "MISSING_UMPIRE_HISTORY",
            "walk_tendency": None,
            "prior_plate_appearances": len(selected),
            "source_subset_sha256": source_sha,
        }

    observed = sum(int(selected[idx]["walk"]) for idx in target_indices) / len(target_indices)
    expected_rate = sum(float(expected[idx]) for idx in target_indices) / len(target_indices)
    raw_bias = observed - expected_rate
    n = len(target_indices)
    shrink_weight = n / (n + int(prior_equivalent_pa))
    shrunk_bias = raw_bias * shrink_weight
    sample_pass = n >= int(min_plate_appearances)

    return {
        **base,
        "status": "AVAILABLE" if sample_pass else "BELOW_MIN_PLATE_APPEARANCES",
        "sample_gate": "PASS" if sample_pass else "BELOW_MIN_PLATE_APPEARANCES",
        "min_plate_appearances": int(min_plate_appearances),
        "prior_equivalent_pa": int(prior_equivalent_pa),
        "batter_prior_pa": int(batter_prior_pa),
        "pitcher_prior_pa": int(pitcher_prior_pa),
        "umpire_plate_appearances": n,
        "prior_plate_appearances": len(selected),
        "observed_walk_rate": round(observed, 6),
        "expected_walk_rate": round(expected_rate, 6),
        "raw_walk_bias": round(raw_bias, 6),
        "shrink_weight": round(shrink_weight, 6),
        "shrunk_walk_bias": round(shrunk_bias, 6),
        "walk_tendency": round(shrunk_bias, 6) if sample_pass else None,
        "source_subset_sha256": source_sha,
    }
