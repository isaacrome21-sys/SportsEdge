"""Versioned MLB family registry v2 (research registration only).

Adds families the frozen 38-family v1 catalog omits, without mutating that
catalog or the pinned v1 evidence groups (#2264 audit, 2026-10-14/15).
Registration here grants no pricing, promotion, or betting authority.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from sportsedge import prop_evidence

_PATH = Path(__file__).resolve().parents[1] / "config" / "mlb_family_registry_v2.json"
V1_CATALOG_SHA256 = "f06b7193a047d62529d653b2a81126357c336bb05b26c79c0c6a5f798bb3117e"
PITCHER_PITCH_COUNT_V2 = "PITCHER_PITCH_COUNT_V2"


def load_registry_v2() -> dict[str, Any]:
    reg = json.loads(_PATH.read_text())
    if reg["extends"]["catalog_sha256"] != V1_CATALOG_SHA256:
        raise ValueError("REGISTRY_V2_CATALOG_PIN_MISMATCH")
    for name, fam in reg["families"].items():
        if fam.get("promotable") is not False:
            raise ValueError(f"REGISTRY_V2_PROMOTABLE_FORBIDDEN:{name}")
    return reg


REGISTRY_V2 = load_registry_v2()


def evidence_dependencies_v2() -> dict[str, frozenset[str]]:
    deps = dict(prop_evidence.MARKET_EVIDENCE_DEPENDENCIES)
    for name, fam in REGISTRY_V2["families"].items():
        if name in deps:
            raise ValueError(f"REGISTRY_V2_SHADOWS_V1:{name}")
        deps[name] = frozenset({fam["evidence_group"]})
    return deps


def settle_pitcher_pitches(stat: Mapping[str, Any], line: float, side: str) -> str:
    n = stat.get("numberOfPitches") if isinstance(stat, Mapping) else None
    if isinstance(n, bool) or not isinstance(n, int) or n < 0:
        raise ValueError("PITCHER_PITCHES_OFFICIAL_COUNT_MISSING")
    s = str(side).strip().upper()
    if s not in {"OVER", "UNDER"}:
        raise ValueError(f"PITCHER_PITCHES_SIDE_INVALID:{side}")
    if n == line:
        return "PUSH"
    over = n > line
    return "WIN" if over == (s == "OVER") else "LOSS"
