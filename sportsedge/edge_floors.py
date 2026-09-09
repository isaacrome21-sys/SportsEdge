from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_EDGE_FLOOR_CONFIG = "config/truth_gate_floors.json"
EDGE_FLOOR_SCHEMA_VERSION = 2
DEVIG_POLICY_ID = "EDGE_FLOOR_DEVIG_V1"
DEVIG_POLICY_STATUS = "FROZEN_PRE_DERIVATION"
SUPPORTED_DEVIG_METHODS = ("MULTIPLICATIVE_V1", "POWER_V1", "SHIN_V1")


class EdgeFloorError(ValueError):
    pass


class FloorStatus(str, Enum):
    UNPROVEN = "UNPROVEN"
    FROZEN = "FROZEN"


@dataclass(frozen=True)
class FrozenDevigPolicy:
    policy_id: str
    longshot_trigger_american_odds: int
    longshot_trigger_rule: str
    sensitivity_methods: tuple[str, ...]
    sensitivity_limit_absolute_probability_points: Decimal
    stable_candidate_estimator: str
    longshot_candidate_estimator: str
    haircut_probability_points: Decimal
    aggregation_rule: str
    sensitivity_failure: str


@dataclass(frozen=True)
class FrozenEdgeFloor:
    market: str
    value_probability_points: Decimal
    method_version: str
    evidence_sha256: str
    derivation_code_sha256: str
    oos_cutoff_utc: str
    frozen_by_commit: str


def load_edge_floor_config(path: str = DEFAULT_EDGE_FLOOR_CONFIG) -> Mapping[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise EdgeFloorError(f"unable to load edge-floor config: {path}") from exc
    if not isinstance(raw, Mapping):
        raise EdgeFloorError("edge-floor config root must be an object")
    return raw


def _as_positive_decimal(value: Any) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise EdgeFloorError("edge floor must be numeric") from exc
    if not d.is_finite() or d <= 0:
        raise EdgeFloorError("production edge floor must be finite and > 0")
    return d


def _as_nonnegative_decimal(value: Any, *, field: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise EdgeFloorError(f"{field} must be numeric") from exc
    if not d.is_finite() or d < 0:
        raise EdgeFloorError(f"{field} must be finite and >= 0")
    return d


def _truth_gate(config: Mapping[str, Any]) -> Mapping[str, Any]:
    truth_gate = config.get("truth_gate")
    if not isinstance(truth_gate, Mapping):
        raise EdgeFloorError("missing truth_gate config")
    return truth_gate


def require_frozen_devig_policy(*, config: Mapping[str, Any]) -> FrozenDevigPolicy:
    """Resolve the pre-derivation devig contract from the existing floor schema.

    The policy is deliberately stored beside edge floors rather than in a second
    configuration/schema.  It chooses one estimator explicitly; sensitivity
    methods are diagnostics/gates and are never aggregated by taking a minimum.
    """
    truth_gate = _truth_gate(config)
    schema_version = truth_gate.get("schema_version")
    if type(schema_version) is not int or schema_version != EDGE_FLOOR_SCHEMA_VERSION:
        raise EdgeFloorError("EDGE_FLOOR_SCHEMA_VERSION_MISMATCH")

    raw = truth_gate.get("devig_policy")
    if not isinstance(raw, Mapping):
        raise EdgeFloorError("DEVIG_POLICY_REQUIRED")
    if raw.get("policy_id") != DEVIG_POLICY_ID:
        raise EdgeFloorError("DEVIG_POLICY_ID_MISMATCH")
    if raw.get("status") != DEVIG_POLICY_STATUS:
        raise EdgeFloorError("DEVIG_POLICY_NOT_FROZEN_PRE_DERIVATION")

    trigger = raw.get("longshot_trigger_american_odds")
    if type(trigger) is not int or trigger < 100:
        raise EdgeFloorError("DEVIG_LONGSHOT_TRIGGER_INVALID")
    trigger_rule = raw.get("longshot_trigger_rule")
    if trigger_rule != "EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400":
        raise EdgeFloorError("DEVIG_LONGSHOT_TRIGGER_RULE_INVALID")

    methods_raw = raw.get("sensitivity_methods")
    if not isinstance(methods_raw, list) or not methods_raw:
        raise EdgeFloorError("DEVIG_SENSITIVITY_METHODS_REQUIRED")
    methods = tuple(str(x) for x in methods_raw)
    if methods != SUPPORTED_DEVIG_METHODS:
        raise EdgeFloorError("DEVIG_SENSITIVITY_METHODS_MISMATCH")

    limit = _as_nonnegative_decimal(
        raw.get("sensitivity_limit_absolute_probability_points"),
        field="sensitivity_limit_absolute_probability_points",
    )
    if limit <= 0 or limit >= 1:
        raise EdgeFloorError("DEVIG_SENSITIVITY_LIMIT_INVALID")

    stable = str(raw.get("stable_candidate_estimator") or "")
    longshot = str(raw.get("longshot_candidate_estimator") or "")
    if stable not in methods:
        raise EdgeFloorError("DEVIG_STABLE_ESTIMATOR_INVALID")
    if longshot not in methods:
        raise EdgeFloorError("DEVIG_LONGSHOT_ESTIMATOR_INVALID")

    haircut = _as_nonnegative_decimal(
        raw.get("haircut_probability_points"), field="haircut_probability_points"
    )
    if haircut >= 1:
        raise EdgeFloorError("DEVIG_HAIRCUT_INVALID")

    aggregation_rule = str(raw.get("aggregation_rule") or "")
    if aggregation_rule != "ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS":
        raise EdgeFloorError("DEVIG_AGGREGATION_RULE_INVALID")
    sensitivity_failure = str(raw.get("sensitivity_failure") or "")
    if sensitivity_failure != "BLOCK":
        raise EdgeFloorError("DEVIG_SENSITIVITY_FAILURE_MUST_BLOCK")

    return FrozenDevigPolicy(
        policy_id=DEVIG_POLICY_ID,
        longshot_trigger_american_odds=trigger,
        longshot_trigger_rule=trigger_rule,
        sensitivity_methods=methods,
        sensitivity_limit_absolute_probability_points=limit,
        stable_candidate_estimator=stable,
        longshot_candidate_estimator=longshot,
        haircut_probability_points=haircut,
        aggregation_rule=aggregation_rule,
        sensitivity_failure=sensitivity_failure,
    )


def require_frozen_edge_floor(*, market: str, config: Mapping[str, Any]) -> FrozenEdgeFloor:
    if not isinstance(market, str) or not market.strip():
        raise EdgeFloorError("market must be a non-empty string")

    truth_gate = _truth_gate(config)

    production = truth_gate.get("production")
    if not isinstance(production, Mapping) or production.get("fail_closed") is not True:
        raise EdgeFloorError("truth_gate.production.fail_closed must be true")
    if production.get("allow_cli_floor_override") is not False:
        raise EdgeFloorError("production CLI floor overrides must be disabled")

    if production.get("require_frozen_floor_for_eligible_market") is not True:
        raise EdgeFloorError("FROZEN_FLOOR_POLICY_REQUIRED")

    floors = truth_gate.get("edge_floors")
    if not isinstance(floors, Mapping):
        raise EdgeFloorError("missing truth_gate.edge_floors config")

    record = floors.get(market)
    if not isinstance(record, Mapping):
        raise EdgeFloorError(f"ELIGIBLE_MARKET_MISSING_OR_UNFROZEN_EDGE_FLOOR:{market}")

    if record.get("status") != FloorStatus.FROZEN.value:
        raise EdgeFloorError(f"ELIGIBLE_MARKET_MISSING_OR_UNFROZEN_EDGE_FLOOR:{market}")

    value = _as_positive_decimal(record.get("value_probability_points"))
    method_version = record.get("method_version")
    evidence = record.get("evidence")
    frozen = record.get("frozen")

    if not isinstance(method_version, str) or not method_version.strip():
        raise EdgeFloorError(f"{market} floor lacks method_version")
    if not isinstance(evidence, Mapping):
        raise EdgeFloorError(f"{market} floor lacks evidence metadata")
    if not isinstance(frozen, Mapping):
        raise EdgeFloorError(f"{market} floor lacks frozen metadata")

    required_evidence = ("evidence_sha256", "derivation_code_sha256", "oos_cutoff_utc")
    missing_evidence = [key for key in required_evidence if not isinstance(evidence.get(key), str) or not evidence.get(key).strip()]
    if missing_evidence:
        raise EdgeFloorError(f"{market} floor missing evidence fields: {','.join(missing_evidence)}")

    frozen_by_commit = frozen.get("frozen_by_commit")
    if not isinstance(frozen_by_commit, str) or not frozen_by_commit.strip():
        raise EdgeFloorError(f"{market} floor lacks frozen_by_commit")

    return FrozenEdgeFloor(
        market=market,
        value_probability_points=value,
        method_version=method_version,
        evidence_sha256=evidence["evidence_sha256"],
        derivation_code_sha256=evidence["derivation_code_sha256"],
        oos_cutoff_utc=evidence["oos_cutoff_utc"],
        frozen_by_commit=frozen_by_commit,
    )


def require_production_edge_floor(*, market: str, path: str = DEFAULT_EDGE_FLOOR_CONFIG) -> FrozenEdgeFloor:
    return require_frozen_edge_floor(market=market, config=load_edge_floor_config(path))
