#!/usr/bin/env python3
"""Strict identity binding between SportsEdge model output and sportsbook quote."""
from dataclasses import dataclass

BIND_FIELDS = ("game_id", "market", "entity_id", "line", "side")


@dataclass(frozen=True)
class BindingResult:
    ok: bool
    reason: str
    mismatched_fields: tuple = ()


def check_binding(model_output: dict, sportsbook_quote: dict,
                  deployment_attestation: dict) -> BindingResult:
    missing = [f for f in BIND_FIELDS if f not in model_output or f not in sportsbook_quote]
    if missing:
        return BindingResult(False, f"missing identity field(s): {missing}")
    mismatches = tuple(f for f in BIND_FIELDS if model_output[f] != sportsbook_quote[f])
    if mismatches:
        return BindingResult(False, f"binding mismatch on: {mismatches}", mismatches)
    dep_market = deployment_attestation.get("market")
    if dep_market != model_output["market"]:
        return BindingResult(False, f"deployment-market mismatch: attested={dep_market} vs model={model_output['market']}")
    if deployment_attestation.get("eligible") is not True:
        return BindingResult(False, "deployment not eligible")
    return BindingResult(True, "bound")
