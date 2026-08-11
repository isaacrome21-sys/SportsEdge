from dataclasses import dataclass
from typing import Any, Mapping


class BindingError(ValueError):
    pass


@dataclass(frozen=True)
class CandidateKey:
    game_id: str
    market: str
    entity_id: str
    line: str
    side: str


def _strict_equal(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


def _key(m: Mapping[str, Any]) -> CandidateKey:
    required = ("game_id", "market", "entity_id", "line", "side")
    missing = [k for k in required if k not in m or m[k] in (None, "")]
    if missing:
        raise BindingError(f"missing candidate identity fields: {','.join(missing)}")
    return CandidateKey(*(m[k] for k in required))


def bind_candidate(model_output: Mapping[str, Any], sportsbook_quote: Mapping[str, Any], deployment_attestation: Mapping[str, Any] | None) -> CandidateKey:
    """Bind model output to the exact quote and deployment market identity.

    Deployment *eligibility* is intentionally not authorization at this layer.
    A well-formed eligible=False record is valid binding metadata and is enforced
    later by the Truth Gate. This keeps model capability separate from permission
    to publish an OFFICIAL_BET while malformed/truthy deployment values still
    fail closed.
    """
    if deployment_attestation is None or not isinstance(deployment_attestation, Mapping):
        raise BindingError("deployment attestation missing or malformed")
    if type(deployment_attestation.get("eligible")) is not bool:
        raise BindingError("deployment eligible must be boolean")

    model_key = _key(model_output)
    quote_key = _key(sportsbook_quote)
    for field in CandidateKey.__dataclass_fields__:
        if not _strict_equal(getattr(model_key, field), getattr(quote_key, field)):
            raise BindingError(f"candidate mismatch: {field}")

    deployed_market = deployment_attestation.get("market")
    if not _strict_equal(deployed_market, model_key.market):
        raise BindingError("deployment market mismatch")
    return model_key
