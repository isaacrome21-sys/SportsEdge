#!/usr/bin/env python3
"""Strict identity binding between SportsEdge model output and sportsbook quote."""
from dataclasses import dataclass
from typing import Any, Optional

BIND_FIELDS = ("game_id", "market", "entity_id", "line", "side")


@dataclass(frozen=True)
class BindingResult:
    ok: bool
    reason: str
    mismatched_fields: tuple = ()


def _strict_eq(a: Any, b: Any) -> bool:
    """Identity fields must match in both value and type (True must not equal 1)."""
    return type(a) is type(b) and a == b


def check_binding(model_output: dict, sportsbook_quote: dict,
                  deployment_attestation: Optional[dict]) -> BindingResult:
    if not isinstance(model_output, dict) or not isinstance(sportsbook_quote, dict):
        return BindingResult(False, "model_output and sportsbook_quote must be dicts")
    if not isinstance(deployment_attestation, dict):
        return BindingResult(False, "deployment_attestation missing or invalid")
    missing = [f for f in BIND_FIELDS if f not in model_output or f not in sportsbook_quote]
    if missing:
        return BindingResult(False, f"missing identity field(s): {missing}")
    mismatches = tuple(f for f in BIND_FIELDS if not _strict_eq(model_output[f], sportsbook_quote[f]))
    if mismatches:
        return BindingResult(False, f"binding mismatch on: {mismatches}", mismatches)
    dep_market = deployment_attestation.get("market")
    if not _strict_eq(dep_market, model_output["market"]):
        return BindingResult(False, f"deployment-market mismatch: attested={dep_market} vs model={model_output['market']}")
    if deployment_attestation.get("eligible") is not True:
        return BindingResult(False, "deployment not eligible")
    return BindingResult(True, "bound")
