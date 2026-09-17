"""Pre-window EV provider credential-health classifier. Diagnostic only; creates no evidence."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sportsedge.ev_suspension_v3 import credential_health


def classify(payload: dict) -> dict:
    slots = payload.get("slots") or []
    errors = [str(s.get("error_code")) for s in slots if s.get("error_code")]
    remaining = [s.get("remaining_credits") for s in slots if s.get("remaining_credits") is not None]
    dead = [s for s in slots if s.get("dead") or s.get("exhausted")]
    if dead:
        state = "DEGRADED_DEAD_SLOT"
    else:
        state = credential_health(remaining_credits=min(remaining) if remaining else None, error_codes=errors)
    return {
        "state": state,
        "healthy": state == "HEALTHY",
        "diagnostic_only": True,
        "creates_evidence": False,
        "slot_count": len(slots),
    }


def main() -> int:
    payload = json.load(sys.stdin)
    result = classify(payload)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["healthy"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
