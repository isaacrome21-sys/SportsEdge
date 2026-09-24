"""PIT-safe qualification flags for bettor-facing NFL RUN IT Score B.

Sportsbook price, implied probability, edge and EV are forbidden inputs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from sports.common.ev_math import parse_utc
from sportsedge.nfl_run_it_scoring import QUALIFICATION_FLAGS


class NflRunItQualificationError(ValueError):
    pass


FORBIDDEN_MARKET_KEYS = frozenset({
    "price", "price_american", "american_odds", "decimal_odds", "odds",
    "implied_probability", "market_no_vig_p", "edge", "edge_probability_points",
    "ev", "ev_per_dollar", "fair_american", "fair_probability",
})


def _strict_bool(row: Mapping[str, Any], key: str) -> bool:
    value = row.get(key)
    if type(value) is not bool:
        raise NflRunItQualificationError(f"QUALIFICATION_BOOL_REQUIRED:{key}")
    return value


def _utc(value: Any, code: str) -> datetime:
    try:
        dt = parse_utc(value)
    except Exception as exc:
        raise NflRunItQualificationError(code) from exc
    return dt.astimezone(timezone.utc)


def qualification_flags_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, bool]:
    if not isinstance(snapshot, Mapping):
        raise NflRunItQualificationError("QUALIFICATION_SNAPSHOT_REQUIRED")
    forbidden = FORBIDDEN_MARKET_KEYS.intersection(snapshot)
    if forbidden:
        raise NflRunItQualificationError("MARKET_INPUT_FORBIDDEN:" + ",".join(sorted(forbidden)))
    captured = _utc(snapshot.get("captured_at"), "CAPTURED_AT_REQUIRED")
    kickoff = _utc(snapshot.get("kickoff_at"), "KICKOFF_AT_REQUIRED")
    if captured >= kickoff:
        raise NflRunItQualificationError("PIT_LEAKAGE_CAPTURE_NOT_BEFORE_KICKOFF")
    source_version = str(snapshot.get("source_version") or "").strip()
    feature_digest = str(snapshot.get("feature_digest") or "").strip()
    if not source_version:
        raise NflRunItQualificationError("SOURCE_VERSION_REQUIRED")
    if not feature_digest:
        raise NflRunItQualificationError("FEATURE_DIGEST_REQUIRED")
    flags = {
        "model_ready": _strict_bool(snapshot, "model_ready"),
        "pit_safe": _strict_bool(snapshot, "pit_safe") and captured < kickoff,
        "role_stable": _strict_bool(snapshot, "role_stable"),
        "usage_supported": _strict_bool(snapshot, "usage_supported"),
        "matchup_supported": _strict_bool(snapshot, "matchup_supported"),
        "injury_context_ready": _strict_bool(snapshot, "injury_context_ready"),
        "shared_simulation_ready": _strict_bool(snapshot, "shared_simulation_ready"),
        "market_binding_ready": _strict_bool(snapshot, "market_binding_ready"),
    }
    if set(flags) != set(QUALIFICATION_FLAGS):
        raise NflRunItQualificationError("QUALIFICATION_SCHEMA_DRIFT")
    return flags
