"""SportsEdge RUN IT v1.1 engine/model/validation/eligibility registry."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping

DEFAULT_REGISTER_PATH = "config/engine_status_register.json"
ENGINE_STATES = frozenset({"PRICED", "NO_ENGINE", "UNKNOWN", "INPUT_MISSING", "ENGINE_BLOCKED"})
MODEL_P_STATES = frozenset({"AVAILABLE", "NONE", "UNKNOWN"})
VALIDATION_STATES = frozenset({"RESEARCH", "SHADOW", "MODEL", "UNVERIFIED", "N/A"})
ELIGIBILITY_STATES = frozenset({"BLOCKED", "ELIGIBLE"})


class EngineStatusRegisterError(ValueError):
    pass


@dataclass(frozen=True)
class EngineStatus:
    sport: str
    market: str
    engine_status: str
    model_p_status: str
    validation_status: str
    betting_eligibility: str


def _key(sport: Any, market: Any) -> tuple[str, str]:
    return str(sport or "").strip().upper(), str(market or "").strip().upper()


def _validate_entry(raw: Mapping[str, Any]) -> EngineStatus:
    sport, market = _key(raw.get("sport"), raw.get("market"))
    engine = str(raw.get("engine_status") or "").strip().upper()
    model = str(raw.get("model_p_status") or "").strip().upper()
    validation = str(raw.get("validation_status") or "").strip().upper()
    eligibility = str(raw.get("betting_eligibility") or "").strip().upper()
    if not sport or not market:
        raise EngineStatusRegisterError("ENGINE_STATUS_IDENTITY_REQUIRED")
    if engine not in ENGINE_STATES:
        raise EngineStatusRegisterError(f"ENGINE_STATUS_INVALID:{sport}:{market}:{engine}")
    if model not in MODEL_P_STATES:
        raise EngineStatusRegisterError(f"MODEL_P_STATUS_INVALID:{sport}:{market}:{model}")
    if validation not in VALIDATION_STATES:
        raise EngineStatusRegisterError(f"VALIDATION_STATUS_INVALID:{sport}:{market}:{validation}")
    if eligibility not in ELIGIBILITY_STATES:
        raise EngineStatusRegisterError(f"BETTING_ELIGIBILITY_INVALID:{sport}:{market}:{eligibility}")
    if engine == "NO_ENGINE" and model == "AVAILABLE":
        raise EngineStatusRegisterError(f"NO_ENGINE_MODEL_P_CONTRADICTION:{sport}:{market}")
    if engine == "NO_ENGINE" and eligibility == "ELIGIBLE":
        raise EngineStatusRegisterError(f"NO_ENGINE_ELIGIBILITY_CONTRADICTION:{sport}:{market}")
    if model == "NONE" and eligibility == "ELIGIBLE":
        raise EngineStatusRegisterError(f"NO_MODEL_P_ELIGIBILITY_CONTRADICTION:{sport}:{market}")
    return EngineStatus(sport, market, engine, model, validation, eligibility)


def load_engine_status_register(path: str | Path = DEFAULT_REGISTER_PATH) -> tuple[dict[str, Any], dict[tuple[str, str], EngineStatus]]:
    raw = json.loads(Path(path).read_text())
    if not isinstance(raw, Mapping) or int(raw.get("schema_version", 0)) != 1:
        raise EngineStatusRegisterError("ENGINE_STATUS_REGISTER_SCHEMA_INVALID")
    if str(raw.get("governance_state") or "").strip().upper() not in {"DEFINED", "IMPLEMENTED", "VERIFIED"}:
        raise EngineStatusRegisterError("ENGINE_STATUS_GOVERNANCE_STATE_INVALID")
    entries = raw.get("entries")
    if not isinstance(entries, list):
        raise EngineStatusRegisterError("ENGINE_STATUS_ENTRIES_REQUIRED")
    out: dict[tuple[str, str], EngineStatus] = {}
    for item in entries:
        if not isinstance(item, Mapping):
            raise EngineStatusRegisterError("ENGINE_STATUS_ENTRY_INVALID")
        row = _validate_entry(item)
        key = (row.sport, row.market)
        if key in out:
            raise EngineStatusRegisterError(f"ENGINE_STATUS_DUPLICATE:{row.sport}:{row.market}")
        out[key] = row
    return dict(raw), out


def resolve_engine_status(sport: Any, market: Any, *, path: str | Path = DEFAULT_REGISTER_PATH) -> EngineStatus:
    _meta, registry = load_engine_status_register(path)
    key = _key(sport, market)
    row = registry.get(key)
    if row is None:
        raise EngineStatusRegisterError(f"ENGINE_STATUS_UNREGISTERED:{key[0]}:{key[1]}")
    return row


def validate_runtime_status(
    sport: Any,
    market: Any,
    *,
    runtime_engine_status: str,
    model_p: float | None,
    decision_status: str | None = None,
    path: str | Path = DEFAULT_REGISTER_PATH,
) -> EngineStatus:
    row = resolve_engine_status(sport, market, path=path)
    runtime = str(runtime_engine_status or "").strip().upper()
    decision = str(decision_status or "").strip().upper()
    if runtime == "PRICED" and row.engine_status != "PRICED":
        raise EngineStatusRegisterError(f"RUNTIME_ENGINE_REGISTER_CONTRADICTION:{row.sport}:{row.market}")
    if model_p is not None and row.model_p_status != "AVAILABLE":
        raise EngineStatusRegisterError(f"RUNTIME_MODEL_P_REGISTER_CONTRADICTION:{row.sport}:{row.market}")
    if decision == "OFFICIAL_BET" and row.betting_eligibility != "ELIGIBLE":
        raise EngineStatusRegisterError(f"OFFICIAL_BET_NOT_ELIGIBLE:{row.sport}:{row.market}")
    return row
