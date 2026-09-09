"""Resolution-time evidence dependencies for NFL/CFB player props.

Evidence state is intentionally external to the simulation. A group can only
resolve PASS when it carries a real evidence SHA and is bound to the exact
frozen model artifact being evaluated. No missing state is inferred from market
prices, hit rates, consensus, or model outputs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from sportsedge.football_prop_extended_run_machine import (
    DEFENDER_OU_MARKETS,
    KICKER_OU_MARKETS,
    OFFENSIVE_OU_MARKETS,
    SCORER_MARKETS,
)

EVIDENCE_SCHEMA = "FOOTBALL_PROP_EVIDENCE_V1"
EVIDENCE_GROUPS = (
    "TEAM_PLAY_OPPORTUNITY",
    "PLAYER_PARTICIPATION",
    "PLAYER_USAGE",
    "OFFENSIVE_EVENT_RATE",
    "YARDAGE_TAIL",
    "TOUCHDOWN_RATE",
    "SPECIAL_TEAMS_OPPORTUNITY",
    "KICKER_PARTICIPATION",
    "KICKER_RATE",
    "DEFENSIVE_PARTICIPATION",
    "DEFENSIVE_USAGE",
    "DEFENSIVE_EVENT_RATE",
)

_OFFENSE_BASE = (
    "TEAM_PLAY_OPPORTUNITY",
    "PLAYER_PARTICIPATION",
    "PLAYER_USAGE",
    "OFFENSIVE_EVENT_RATE",
)
_YARDAGE = frozenset({
    "player_pass_longest_completion",
    "player_pass_rush_yds",
    "player_pass_yds",
    "player_reception_longest",
    "player_reception_yds",
    "player_rush_longest",
    "player_rush_reception_yds",
    "player_rush_yds",
})
_TOUCHDOWN = frozenset({
    "player_pass_tds",
    "player_reception_tds",
    "player_rush_reception_tds",
    "player_rush_tds",
    "player_anytime_td",
    "player_tds_over",
})

MARKET_EVIDENCE_DEPENDENCIES: dict[str, tuple[str, ...]] = {}
for market in OFFENSIVE_OU_MARKETS:
    MARKET_EVIDENCE_DEPENDENCIES[market] = (
        _OFFENSE_BASE
        + (("YARDAGE_TAIL",) if market in _YARDAGE else ())
        + (("TOUCHDOWN_RATE",) if market in _TOUCHDOWN else ())
    )
for market in SCORER_MARKETS:
    MARKET_EVIDENCE_DEPENDENCIES[market] = _OFFENSE_BASE + ("TOUCHDOWN_RATE",)
for market in KICKER_OU_MARKETS:
    MARKET_EVIDENCE_DEPENDENCIES[market] = (
        "TEAM_PLAY_OPPORTUNITY",
        "SPECIAL_TEAMS_OPPORTUNITY",
        "KICKER_PARTICIPATION",
        "KICKER_RATE",
    )
for market in DEFENDER_OU_MARKETS:
    MARKET_EVIDENCE_DEPENDENCIES[market] = (
        "TEAM_PLAY_OPPORTUNITY",
        "DEFENSIVE_PARTICIPATION",
        "DEFENSIVE_USAGE",
        "DEFENSIVE_EVENT_RATE",
    )


class FootballPropEvidenceError(ValueError):
    pass


def _sha256(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        raise FootballPropEvidenceError(error)
    return raw


def default_registry_path(sport: str) -> Path:
    resolved = str(sport or "").strip().lower()
    if resolved not in {"nfl", "cfb"}:
        raise FootballPropEvidenceError(f"FOOTBALL_PROP_EVIDENCE_SPORT_UNSUPPORTED:{sport}")
    return Path(f"config/{resolved}_prop_evidence.json")


def load_evidence_registry(sport: str, *, path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path is not None else default_registry_path(sport)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception as exc:
        raise FootballPropEvidenceError("FOOTBALL_PROP_EVIDENCE_REGISTRY_UNREADABLE") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != EVIDENCE_SCHEMA:
        raise FootballPropEvidenceError("FOOTBALL_PROP_EVIDENCE_REGISTRY_SCHEMA_INVALID")
    resolved = str(sport or "").strip().upper()
    if payload.get("sport") != resolved:
        raise FootballPropEvidenceError("FOOTBALL_PROP_EVIDENCE_REGISTRY_SPORT_MISMATCH")
    groups = payload.get("groups")
    if not isinstance(groups, Mapping) or set(groups) != set(EVIDENCE_GROUPS):
        raise FootballPropEvidenceError("FOOTBALL_PROP_EVIDENCE_GROUP_SET_INVALID")
    return payload


def assess_market_evidence(
    *,
    sport: str,
    provider_market: str,
    model_artifact_sha256: str,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    market = str(provider_market or "").strip()
    if market not in MARKET_EVIDENCE_DEPENDENCIES:
        raise FootballPropEvidenceError(f"FOOTBALL_PROP_EVIDENCE_MARKET_UNSUPPORTED:{market}")
    artifact_sha = _sha256(
        model_artifact_sha256,
        "FOOTBALL_PROP_EVIDENCE_MODEL_ARTIFACT_SHA256_INVALID",
    )
    payload = dict(registry) if registry is not None else load_evidence_registry(sport)
    if payload.get("schema_version") != EVIDENCE_SCHEMA:
        raise FootballPropEvidenceError("FOOTBALL_PROP_EVIDENCE_REGISTRY_SCHEMA_INVALID")
    if payload.get("sport") != str(sport).strip().upper():
        raise FootballPropEvidenceError("FOOTBALL_PROP_EVIDENCE_REGISTRY_SPORT_MISMATCH")
    groups = payload.get("groups")
    if not isinstance(groups, Mapping) or set(groups) != set(EVIDENCE_GROUPS):
        raise FootballPropEvidenceError("FOOTBALL_PROP_EVIDENCE_GROUP_SET_INVALID")

    missing: list[str] = []
    blocked: list[str] = []
    passed: list[str] = []
    for group in MARKET_EVIDENCE_DEPENDENCIES[market]:
        row = groups.get(group)
        if not isinstance(row, Mapping):
            raise FootballPropEvidenceError(f"FOOTBALL_PROP_EVIDENCE_GROUP_INVALID:{group}")
        status = str(row.get("status") or "").strip().upper()
        if status == "MISSING":
            missing.append(group)
            continue
        if status == "BLOCKED":
            blocked.append(group)
            continue
        if status != "PASS":
            raise FootballPropEvidenceError(f"FOOTBALL_PROP_EVIDENCE_STATUS_INVALID:{group}:{status}")
        evidence_sha = _sha256(
            row.get("evidence_sha256"),
            f"FOOTBALL_PROP_EVIDENCE_SHA256_INVALID:{group}",
        )
        bound_artifact = _sha256(
            row.get("model_artifact_sha256"),
            f"FOOTBALL_PROP_EVIDENCE_ARTIFACT_BINDING_INVALID:{group}",
        )
        if bound_artifact != artifact_sha:
            blocked.append(group)
            continue
        assert evidence_sha
        passed.append(group)

    blockers = [f"EVIDENCE_GROUP_MISSING:{group}" for group in missing]
    blockers.extend(f"EVIDENCE_GROUP_BLOCKED:{group}" for group in blocked)
    return {
        "ready": not blockers,
        "required_groups": list(MARKET_EVIDENCE_DEPENDENCIES[market]),
        "passed_groups": passed,
        "missing_groups": missing,
        "blocked_groups": blocked,
        "blockers": blockers,
        "model_artifact_sha256": artifact_sha,
    }
