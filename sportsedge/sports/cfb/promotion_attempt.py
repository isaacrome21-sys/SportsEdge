"""CFB historical promotion attempt under the frozen CFB_TRUTH_GATE_V1.

Older generic football promotion stages are not authoritative for CFB v1.2. A CFB
main market is OFFICIAL only when the complete frozen CFB gate passes for that market.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from .truth_gate_v1 import CFBTruthGateEvidence, evaluate_cfb_truth_gate_v1


@dataclass(frozen=True)
class CFBPromotionAttempt:
    market: str
    as_of_date: str
    stage: str
    official_plays: tuple[dict, ...]
    zero_is_valid: bool
    failures: tuple[str, ...]


def run_cfb_promotion_attempt(
    *,
    market: str,
    evidence: CFBTruthGateEvidence,
    candidates: Iterable[dict],
    as_of_date: str,
) -> CFBPromotionAttempt:
    market_name = str(market).strip().upper()
    if not market_name:
        raise ValueError("MARKET_MISSING")
    parsed = date.fromisoformat(str(as_of_date))
    if str(evidence.market).upper() != market_name:
        raise ValueError("CFB_PROMOTION_EVIDENCE_MARKET_MISMATCH")
    gate = evaluate_cfb_truth_gate_v1(evidence)
    official = tuple(
        row for row in candidates
        if gate.official and row.get("qualifies") is True
    )
    return CFBPromotionAttempt(
        market=market_name,
        as_of_date=parsed.isoformat(),
        stage=gate.status,
        official_plays=official,
        zero_is_valid=True,
        failures=gate.failures,
    )
