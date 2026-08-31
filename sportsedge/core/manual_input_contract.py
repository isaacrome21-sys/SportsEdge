"""Shared Manual/Hybrid input contract.

Manual acquisition is never permission to bypass the same schema, PIT, identity and
market-blind validation applied to Hybrid. This helper validates a normalized feature
payload against an explicit schema and rejects market-derived predictive fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


class ManualInputContractError(ValueError):
    pass


FORBIDDEN_PREDICTIVE_NAMES = frozenset({
    "spread", "market_spread", "moneyline", "market_moneyline", "total", "market_total",
    "american_odds", "decimal_odds", "implied_probability", "no_vig_probability",
    "novig_probability", "closing_line", "opening_line", "consensus", "ticket_pct",
    "tickets_pct", "money_pct", "handle_pct", "steam", "reverse_line_movement",
})


@dataclass(frozen=True)
class FeatureSchemaContract:
    schema_id: str
    required_fields: frozenset[str]
    optional_fields: frozenset[str] = frozenset()

    def validate(self) -> "FeatureSchemaContract":
        if not self.schema_id:
            raise ManualInputContractError("FEATURE_SCHEMA_ID_REQUIRED")
        if self.required_fields & self.optional_fields:
            raise ManualInputContractError("FEATURE_SCHEMA_REQUIRED_OPTIONAL_OVERLAP")
        return self


def _scan_market_leakage(value: Any, *, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
            if normalized in FORBIDDEN_PREDICTIVE_NAMES:
                raise ManualInputContractError(f"MARKET_DERIVED_PREDICTIVE_FIELD_FORBIDDEN:{path}.{key}")
            _scan_market_leakage(child, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, child in enumerate(value):
            _scan_market_leakage(child, path=f"{path}[{idx}]")


def validate_normalized_feature_payload(
    payload: Mapping[str, Any],
    *,
    schema: FeatureSchemaContract,
) -> dict[str, Any]:
    schema.validate()
    row = dict(payload)
    _scan_market_leakage(row)
    keys = frozenset(row)
    missing = sorted(schema.required_fields - keys)
    extra = sorted(keys - schema.required_fields - schema.optional_fields)
    if missing:
        raise ManualInputContractError("FEATURE_SCHEMA_MISSING:" + ",".join(missing))
    if extra:
        raise ManualInputContractError("FEATURE_SCHEMA_EXTRA:" + ",".join(extra))
    return row


def assert_manual_hybrid_feature_identity(
    manual_payload: Mapping[str, Any],
    hybrid_payload: Mapping[str, Any],
    *,
    schema: FeatureSchemaContract,
) -> None:
    manual = validate_normalized_feature_payload(manual_payload, schema=schema)
    hybrid = validate_normalized_feature_payload(hybrid_payload, schema=schema)
    if manual != hybrid:
        raise ManualInputContractError("MANUAL_HYBRID_FEATURE_IDENTITY_FAILED")
