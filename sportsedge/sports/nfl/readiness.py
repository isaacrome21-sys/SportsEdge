"""Evidence-derived OFFICIAL resolution for the canonical NFL M2 run machine."""
from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from typing import Any, Mapping

from sportsedge.edge_floors import FrozenEdgeFloor, require_production_edge_floor
from sportsedge.truth_gate import decide_bet

from .m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID
from .run_machine import (
    NFLMachineReport,
    NFLMachineResult,
    SUPPORTED_GAME_MARKETS,
    run_nfl_machine,
)

PROMOTION_SCHEMA_VERSION = 9


class NFLReadinessError(ValueError):
    pass


def load_nfl_promotion_registry(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise NFLReadinessError("NFL_PROMOTION_REGISTRY_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise NFLReadinessError("NFL_PROMOTION_REGISTRY_INVALID")
    return payload


def _sha256(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 64 or any(ch not in "0123456789abcdef" for ch in raw):
        raise NFLReadinessError(error)
    return raw


def _git_sha(value: Any, error: str) -> str:
    raw = str(value or "").strip().lower()
    if len(raw) != 40 or any(ch not in "0123456789abcdef" for ch in raw):
        raise NFLReadinessError(error)
    return raw


def _validate_registry(
    registry: Mapping[str, Any],
    *,
    artifact_payload: Mapping[str, Any],
    runtime_code_git_sha: str,
) -> dict[str, Mapping[str, Any]]:
    if registry.get("schema_version") != PROMOTION_SCHEMA_VERSION:
        raise NFLReadinessError("NFL_PROMOTION_REGISTRY_SCHEMA_INVALID")
    if str(registry.get("sport") or "").lower() != "nfl":
        raise NFLReadinessError("NFL_PROMOTION_REGISTRY_SPORT_INVALID")
    if registry.get("model_id") != PRODUCTION_NFL_M2_MODEL_ID:
        raise NFLReadinessError("NFL_PROMOTION_REGISTRY_MODEL_ID_MISMATCH")
    if registry.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
        raise NFLReadinessError("NFL_PROMOTION_REGISTRY_FEATURE_CONTRACT_MISMATCH")

    registry_code = _git_sha(
        registry.get("code_git_sha"), "NFL_PROMOTION_REGISTRY_CODE_GIT_SHA_INVALID"
    )
    runtime_code = _git_sha(runtime_code_git_sha, "NFL_RUNTIME_CODE_GIT_SHA_INVALID")
    artifact_code = _git_sha(
        artifact_payload.get("code_git_sha"), "NFL_MODEL_ARTIFACT_CODE_GIT_SHA_INVALID"
    )
    if {registry_code, runtime_code, artifact_code} != {runtime_code}:
        raise NFLReadinessError("NFL_PROMOTION_REGISTRY_CODE_BINDING_MISMATCH")

    registry_source = _sha256(
        registry.get("source_manifest_sha256"),
        "NFL_PROMOTION_REGISTRY_SOURCE_MANIFEST_SHA256_INVALID",
    )
    artifact_source = _sha256(
        artifact_payload.get("source_manifest_sha256"),
        "NFL_MODEL_ARTIFACT_SOURCE_SHA256_INVALID",
    )
    if registry_source != artifact_source:
        raise NFLReadinessError("NFL_PROMOTION_REGISTRY_SOURCE_BINDING_MISMATCH")

    markets = registry.get("markets")
    if not isinstance(markets, Mapping):
        raise NFLReadinessError("NFL_PROMOTION_REGISTRY_MARKETS_INVALID")
    out: dict[str, Mapping[str, Any]] = {}
    for market in SUPPORTED_GAME_MARKETS:
        key = market.lower()
        row = markets.get(key)
        if not isinstance(row, Mapping):
            raise NFLReadinessError(f"NFL_PROMOTION_MARKET_MISSING:{key}")
        stage = str(row.get("stage") or "").strip().upper()
        eligible = row.get("eligible")
        if not isinstance(eligible, bool):
            raise NFLReadinessError(f"NFL_PROMOTION_ELIGIBLE_INVALID:{key}")
        if eligible is not (stage == "DEPLOYED"):
            raise NFLReadinessError(f"NFL_PROMOTION_STAGE_CONTRADICTION:{key}")
        out[market] = row
    return out


def _floor_key(market: str) -> str:
    resolved = str(market or "").strip().upper()
    if resolved not in SUPPORTED_GAME_MARKETS:
        raise NFLReadinessError(f"NFL_PROMOTION_MARKET_UNSUPPORTED:{resolved}")
    return f"NFL_{resolved}"


def run_nfl_ready(
    *,
    promotion_registry: Mapping[str, Any],
    floor_path: str | Path = "config/truth_gate_floors.json",
    **kwargs: Any,
) -> NFLMachineReport:
    """Run canonical M2 and resolve real promotion/floor/price gates.

    Promotion is not a manual runtime flag.  The exact-head registry is rebuilt
    from historical validation, CI attestation and forward CLV evidence.  A
    market whose derived stage is DEPLOYED must resolve its NFL-namespaced frozen
    floor before M2 inference is permitted.  The existing Truth Gate owns the
    final OFFICIAL_BET decision.
    """
    artifact_payload = kwargs.get("model_artifact")
    if not isinstance(artifact_payload, Mapping):
        raise NFLReadinessError("NFL_MODEL_ARTIFACT_REQUIRED")
    runtime_code = str(kwargs.get("runtime_code_git_sha") or "")
    market_registry = _validate_registry(
        promotion_registry,
        artifact_payload=artifact_payload,
        runtime_code_git_sha=runtime_code,
    )

    floors: dict[str, FrozenEdgeFloor] = {}
    for market, state in market_registry.items():
        if state.get("eligible") is True:
            floors[market] = require_production_edge_floor(
                market=_floor_key(market), path=floor_path
            )

    report = run_nfl_machine(**kwargs)
    resolved_results: list[NFLMachineResult] = []
    truth_gate_rows = 0
    official_bets = 0
    deployed_rows = 0

    for row in report.results:
        state = market_registry[row.market]
        deployed = state.get("eligible") is True
        if not deployed:
            resolved_results.append(replace(
                row,
                bet_status="BLOCKED",
                reason=f"NFL_PROMOTION_EVIDENCE_REQUIRED:{row.market}",
            ))
            continue
        deployed_rows += 1
        floor = floors.get(row.market)
        if floor is None:
            raise NFLReadinessError(
                f"NFL_FROZEN_FLOOR_PREFLIGHT_MISSING:{_floor_key(row.market)}"
            )
        if row.reason == "NFL_QUOTE_STALE" or row.fair_market_p is None:
            resolved_results.append(replace(row, bet_status="BLOCKED"))
            continue

        decision = decide_bet(
            float(row.model_p),
            float(row.american_odds),
            fair_market_probability=float(row.fair_market_p),
            bound=True,
            fresh=True,
            deployed=True,
            edge_floor=float(floor.value_probability_points),
            push_probability=float(row.push_p or 0.0),
        )
        truth_gate_rows += 1
        if decision.bet_status == "OFFICIAL_BET":
            official_bets += 1
        resolved_results.append(replace(
            row,
            bet_status=decision.bet_status,
            reason="TRUTH_GATE_RESOLVED",
            edge=decision.edge,
            ev_per_dollar=decision.ev_per_dollar,
        ))

    ordered = tuple(resolved_results)
    summary = dict(report.summary)
    summary.update({
        "blocked": sum(row.bet_status == "BLOCKED" for row in ordered),
        "official_bets": official_bets,
        "deployed_rows": deployed_rows,
        "truth_gate_rows": truth_gate_rows,
        "deployed_markets": sorted(
            market for market, state in market_registry.items()
            if state.get("eligible") is True
        ),
        "manual_eligible_toggle_required": False,
        "floor_keys": sorted(_floor_key(market) for market in floors),
    })
    if truth_gate_rows:
        run_status = "SUCCESS"
    elif deployed_rows:
        run_status = "BLOCKED"
    else:
        run_status = "BLOCKED"
    return replace(report, results=ordered, summary=summary, run_status=run_status)
