from __future__ import annotations

from pathlib import Path
from typing import Any

from sportsedge.validation.gate_report import GateReport
from sportsedge.validation.truth_gate_core import TruthGateCore, TruthGatePolicyError


class MLBTruthGate(TruthGateCore):
    EXPECTED_FAMILIES = frozenset(
        {"V7_GAME", "HITTER_JOINT", "PITCHER_JOINT", "F5", "SPECIALIZED"}
    )

    def __init__(self, policy_path: str | Path = "config/mlb_truth_gate_v1.json"):
        super().__init__(policy_path)
        if self.policy["policy_id"] != "MLB_TRUTH_GATE_V1":
            raise TruthGatePolicyError("MLB_TRUTH_GATE_POLICY_ID_INVALID")
        if self.allowed_markets != self.EXPECTED_FAMILIES:
            raise TruthGatePolicyError("MLB_TRUTH_GATE_FAMILY_SURFACE_INVALID")
        if type(self.gates.get("require_coherent_joint_constraints")) is not bool:
            raise TruthGatePolicyError("MLB_TRUTH_GATE_JOINT_COHERENCE_POLICY_REQUIRED")

    def evaluate_family(self, family: str, **kwargs: Any) -> GateReport:
        return super().evaluate(sport="MLB", market=family, **kwargs)


TruthGate = MLBTruthGate
