from __future__ import annotations

from pathlib import Path
from typing import Any

from sportsedge.validation.gate_report import GateReport
from sportsedge.validation.truth_gate_core import (
    CandidateDecision,
    EvidenceError,
    MarketStatus,
    TruthGateCore,
    TruthGatePolicyError,
)


class CFBTruthGate(TruthGateCore):
    EXPECTED_MARKETS = frozenset({"MONEYLINE", "SPREAD", "TOTAL"})

    def __init__(self, policy_path: str | Path = "config/cfb_truth_gate_v1.json"):
        super().__init__(policy_path)
        if self.policy["policy_id"] != "CFB_TRUTH_GATE_V1":
            raise TruthGatePolicyError("CFB_TRUTH_GATE_POLICY_ID_INVALID")
        if self.allowed_markets != self.EXPECTED_MARKETS:
            raise TruthGatePolicyError("CFB_TRUTH_GATE_MARKET_SURFACE_INVALID")
        if type(self.gates.get("require_paired_historical_price_evidence")) is not bool:
            raise TruthGatePolicyError("CFB_TRUTH_GATE_PAIRED_PRICE_POLICY_REQUIRED")

    @property
    def markets(self):
        return self.allowed_markets

    def evaluate(self, market: str, **kwargs: Any) -> GateReport:
        failures = dict(kwargs.pop("sport_specific_failures", {}) or {})
        paired = kwargs.pop("paired_historical_price_evidence_complete", None)
        if type(paired) is not bool:
            failures[True] = "paired_historical_price_evidence_complete:BOOL_REQUIRED"
        elif self.gates["require_paired_historical_price_evidence"] and not paired:
            failures[True] = "PAIRED_HISTORICAL_PRICE_EVIDENCE_REQUIRED"
        kwargs["sport_specific_failures"] = failures
        return super().evaluate(sport="CFB", market=market, **kwargs)

    def evaluate_market(self, market: str, **kwargs: Any) -> GateReport:
        return self.evaluate(market, **kwargs)


TruthGate = CFBTruthGate
TruthGateError = EvidenceError
PromotionState = MarketStatus
CandidateBetStatus = CandidateDecision
