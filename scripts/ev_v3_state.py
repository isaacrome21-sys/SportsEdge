"""Build V3 transition records. Caller persists them create-only/append-only."""
from __future__ import annotations
import hashlib
import json
from typing import Mapping


def policy_sha(policy: Mapping) -> str:
    raw = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def transition_record(*, from_state: str, to_state: str, effective_at: str, reason_code: str,
                      policy_id: str, policy_sha256: str, prior_policy_id: str,
                      prior_policy_sha256: str) -> dict:
    if not effective_at or not reason_code or not policy_sha256 or not prior_policy_sha256:
        raise ValueError("TRANSITION_BINDING_INCOMPLETE")
    return {
        "record_type": "EV_V3_STATE_TRANSITION",
        "from_state": from_state,
        "to_state": to_state,
        "effective_at": effective_at,
        "reason_code": reason_code,
        "policy_id": policy_id,
        "policy_sha256": policy_sha256,
        "prior_policy_id": prior_policy_id,
        "prior_policy_sha256": prior_policy_sha256,
        "append_only": True,
        "retroactive_effect": False,
    }
