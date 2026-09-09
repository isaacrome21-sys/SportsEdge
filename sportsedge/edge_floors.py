from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_EDGE_FLOOR_CONFIG = "config/truth_gate_floors.json"


class EdgeFloorError(ValueError):
    pass


class FloorStatus(str, Enum):
    UNPROVEN = "UNPROVEN"
    FROZEN = "FROZEN"


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


def require_frozen_edge_floor(*, market: str, config: Mapping[str, Any]) -> FrozenEdgeFloor:
    if not isinstance(market, str) or not market.strip():
        raise EdgeFloorError("market must be a non-empty string")

    truth_gate = config.get("truth_gate")
    if not isinstance(truth_gate, Mapping):
        raise EdgeFloorError("missing truth_gate config")

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
        raise EdgeFloorError(f"no edge-floor record for {market}")

    if record.get("status") != FloorStatus.FROZEN.value:
        raise EdgeFloorError(f"{market} has not earned a frozen production floor")

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
