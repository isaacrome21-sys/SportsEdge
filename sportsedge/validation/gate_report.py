from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class GateReport:
    sport: str
    market: str
    market_status: str
    candidate_decision: str
    policy_version: str
    policy_sha256: str
    hard_gate_pass: bool
    market_failures: Tuple[str, ...]
    candidate_failures: Tuple[str, ...]
    metrics: Tuple[Tuple[str, Any], ...]
    diagnostics: Tuple[Tuple[str, Any], ...]
    edge: Optional[float]
    notes: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sport": self.sport,
            "market": self.market,
            "market_status": self.market_status,
            "candidate_decision": self.candidate_decision,
            "policy_version": self.policy_version,
            "policy_sha256": self.policy_sha256,
            "hard_gate_pass": self.hard_gate_pass,
            "market_failures": list(self.market_failures),
            "candidate_failures": list(self.candidate_failures),
            "metrics": dict(self.metrics),
            "diagnostics": dict(self.diagnostics),
            "edge": self.edge,
            "notes": list(self.notes),
        }

    def content_hash(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
