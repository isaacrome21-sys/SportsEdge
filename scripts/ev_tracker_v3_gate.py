"""V3 admission gate for EV tracker. Reads machine state; never mutates prior ledger records."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sportsedge.ev_suspension_v3 import State, admission_disposition


def evaluate(payload: dict) -> dict:
    state = State(str(payload.get("state") or "ACTIVE"), int(payload.get("recovery_streak") or 0))
    disposition = admission_disposition(state)
    return {
        "state": state.name,
        "recovery_streak": state.recovery_streak,
        "admission": disposition,
        "admit_evidence": disposition == "EVIDENCE_ALLOWED",
        "mutates_prior_records": False,
    }


def main() -> int:
    result = evaluate(json.load(sys.stdin))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["admit_evidence"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
