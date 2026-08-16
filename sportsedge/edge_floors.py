from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping


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
