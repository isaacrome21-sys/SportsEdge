"""2026 stability check of the live MLB context lanes (#1482, 2027 prep).

Pure decision logic for ``docs/MLB_CONTEXT_LANE_STABILITY_2026_PREREG.md``. The frozen
production configs are read from the production lane modules so the check can never
drift from what the card prices. Research only: changes no picks.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from sportsedge import mlb_opp_k_context as LANE_K
from sportsedge import mlb_opp_outs_context as LANE_O
from sportsedge import mlb_umpire_bb_context as LANE_BB

PREREG_PATH = Path(__file__).resolve().parents[1] / "docs" / "MLB_CONTEXT_LANE_STABILITY_2026_PREREG.md"
HELDOUT, RETUNE = 2026, 2025
PITCHER_SEASONS = (2024, 2025, 2026)
TEAM_SEASONS = (2023, 2024, 2025, 2026)
ECE_SLACK = 0.005

# Frozen production configs (the candidate key each research module uses) and baselines.
FROZEN = {
    "OPP-K": float(LANE_K.BETA),
    "OPP-OUTS": (str(LANE_O.INDEX), float(LANE_O.BETA)),
    "UMP-BB": (float(LANE_BB.W), float(LANE_BB.BETA)),
}
BASELINES = {"OPP-K": 0.0, "OPP-OUTS": ("base", 0.0), "UMP-BB": (0.0, 0.0)}
MARKETS = {"OPP-K": "PITCHER_K", "OPP-OUTS": "PITCHER_OUTS", "UMP-BB": "PITCHER_BB"}


class LaneStabilityError(ValueError):
    pass


def prereg_sha256() -> str:
    return hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()


def stability_decision(boot: Mapping[str, float], typical_base: Mapping[str, float],
                       typical_frozen: Mapping[str, float]) -> dict[str, Any]:
    """Apply the pre-registered rule to one lane's 2026 result.

    ``boot`` is the pitcher-cluster bootstrap of RPS(frozen) - RPS(baseline).
    """
    for k in ("diff", "lo", "hi"):
        if k not in boot:
            raise LaneStabilityError(f"bootstrap missing {k}")
    if not (boot["lo"] <= boot["diff"] <= boot["hi"]):
        raise LaneStabilityError("bootstrap interval does not contain the point estimate")
    worse = bool(boot["lo"] > 0)
    miscal = bool(float(typical_frozen["ece"]) > float(typical_base["ece"]) + ECE_SLACK)
    if worse or miscal:
        verdict = "DISABLE"
    elif boot["hi"] < 0:
        verdict = "KEEP_CONFIRMED"
    else:
        verdict = "KEEP_NOT_CONFIRMED"
    return {"rule1_significantly_worse": worse, "rule2_miscalibrated": miscal, "verdict": verdict,
            "bootstrap_frozen_minus_base": dict(boot), "typical_base": dict(typical_base),
            "typical_frozen": dict(typical_frozen)}


def verdict_text(verdict: str) -> str:
    return {
        "DISABLE": "DISABLE for 2027 (separate PR turns the lane off from 2027-01-01)",
        "KEEP_CONFIRMED": "KEEP — CONFIRMED (frozen lane still beats its baseline on 2026)",
        "KEEP_NOT_CONFIRMED": "KEEP (not confirmed: 2026 CI covers 0; no evidence of harm)",
    }[verdict]
