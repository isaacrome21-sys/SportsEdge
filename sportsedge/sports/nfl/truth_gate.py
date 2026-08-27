from __future__ import annotations

from pathlib import Path
from typing import Any

from sportsedge.validation.gate_report import GateReport
from sportsedge.validation.truth_gate_core import TruthGateCore, TruthGatePolicyError


class NFLTruthGate(TruthGateCore):
    EXPECTED_SURFACES = frozenset({"GAME", "PERIOD", "PLAYER", "DEFENSE", "KICKING"})

    def __init__(self, policy_path: str | Path = "config/nfl_truth_gate_v1.json"):
        super().__init__(policy_path)
        if self.policy["policy_id"] != "NFL_TRUTH_GATE_V1":
            raise TruthGatePolicyError("NFL_TRUTH_GATE_POLICY_ID_INVALID")
        if self.allowed_markets != self.EXPECTED_SURFACES:
            raise TruthGatePolicyError("NFL_TRUTH_GATE_SURFACE_INVALID")
        if type(self.gates.get("require_shared_path_coherence")) is not bool:
            raise TruthGatePolicyError("NFL_TRUTH_GATE_SHARED_PATH_POLICY_REQUIRED")

    def evaluate_surface(self, surface: str, **kwargs: Any) -> GateReport:
        return super().evaluate(sport="NFL", market=surface, **kwargs)


TruthGate = NFLTruthGate
