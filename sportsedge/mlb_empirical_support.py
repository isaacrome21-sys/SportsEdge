"""Read-only empirical support evidence and presentation guard; no model changes."""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any, Mapping

EMPIRICAL_PREFIXES = ("mlb_pitcher_joint_empirical_", "mlb_hitter_joint_empirical_")
MIN_TAIL_SAMPLE = 30
THIN_TAIL_CUTOFF = 0.10


def is_empirical(row: Mapping[str, Any]) -> bool:
    return str(row.get("engine_version") or "").startswith(EMPIRICAL_PREFIXES)


def support_evidence(feature: Mapping[str, Any], row: Mapping[str, Any]) -> dict | None:
    """Count the exact pool supplied to the engine, not a newly fetched sample."""
    if not is_empirical(row):
        return None
    features = feature.get("features") or {}
    pool = features.get("history_pool")
    if not isinstance(pool, list) or not pool:
        return None
    # Reuse the engine's stat mapping, without calling or modifying its pricing.
    if str(row["engine_version"]).startswith("mlb_pitcher_"):
        from .pitcher_joint_engine import _value
        unit = "starts"
    else:
        from .hitter_joint_engine import _value
        unit = "games"
    values = [_value(item, str(row["market"])) for item in pool]
    line = float(row["line"])
    over = sum(value > line for value in values)
    under = sum(value < line for value in values)
    return {
        "sample_size": len(pool), "sample_unit": unit,
        "wins": over if row["side"] == "OVER" else under,
        "pushes": sum(value == line for value in values),
        "weighted": features.get("history_weights") is not None,
        "source_subset_hash": feature.get("source_subset_hash"),
        "pool_sha256": hashlib.sha256(json.dumps(pool, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    }


def empirical_guard_reason(row: Mapping[str, Any], conditional_p: float | None) -> str | None:
    if not is_empirical(row) or row.get("model_p") is None:
        return None
    evidence = row.get("empirical_evidence")
    if not isinstance(evidence, Mapping):
        return "EMPIRICAL_SAMPLE_UNKNOWN: exact engine pool evidence unavailable"
    n = evidence.get("sample_size")
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0 or not evidence.get("pool_sha256"):
        return "EMPIRICAL_SAMPLE_UNKNOWN: invalid or unbound engine pool evidence"
    p = float(row["model_p"])
    if not isfinite(p) or not 0 <= p <= 1:
        return "EMPIRICAL_PROBABILITY_INVALID"
    endpoint = any(value is not None and (abs(value) <= 1e-12 or abs(value - 1.0) <= 1e-12)
                   for value in (p, conditional_p))
    tail = min(p, conditional_p if conditional_p is not None else p) <= THIN_TAIL_CUTOFF + 1e-12 or max(p, conditional_p if conditional_p is not None else p) >= 1 - THIN_TAIL_CUTOFF - 1e-12
    if not endpoint and not (n < MIN_TAIL_SAMPLE and tail):
        return None
    if endpoint:
        code = "EMPIRICAL_TAIL_UNSUPPORTED" if n < MIN_TAIL_SAMPLE else "EMPIRICAL_BOUNDARY_UNCALIBRATED"
    else:
        code = "EMPIRICAL_THIN_TAIL_UNSUPPORTED"
    wins = evidence.get("wins")
    count = f"{wins}/{n}" if isinstance(wins, int) and not isinstance(wins, bool) and 0 <= wins <= n else f"n={n}"
    unit = evidence.get("sample_unit", "observations")
    weighted = "; weighted estimate, counts are unweighted" if evidence.get("weighted") else ""
    return f"{code}: {count} prior {unit} {str(row.get('side', '')).lower()} {row.get('line'):g}; raw p={p:.1%}{weighted}"
