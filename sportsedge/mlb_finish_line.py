"""Executable finish-line inventory for the complete SportsEdge MLB catalog.

Engineering completion and evidence completion are deliberately different states.
This module proves that every canonical market has named runtime/settlement code and
then classifies what still prevents operational promotion: external acquisition,
book-rule policy, structural/behavioral revalidation, or the six evidence gates.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .engine_registry import engine_registry
from .mlb_acceptance_matrix import build_acceptance_matrix
from .mlb_catalog_prediction_settlement import (
    ADDITIONAL_MARKETS,
    EITHER_PITCHER_MARKETS,
    GAME_MARKETS,
)
from .mlb_settlement_evidence import _BATTER_FIELD_BY_MARKET, _PITCHER_FIELD_BY_MARKET

DEFAULT_SURFACE = Path("config/mlb_market_surface.json")
DEFAULT_DEPLOYMENTS = Path("config/deployments.json")
DEFAULT_BEHAVIORAL = Path("config/mlb_behavioral_disposition.json")
DEFAULT_VALIDATION = Path("config/mlb_validation_evidence.json")
DEFAULT_PROVIDER_CAPABILITY = Path("config/mlb_provider_capability_audit.json")

# These are not guesses about sportsbook rules. They identify catalog families where
# the repo already knows a book-specific policy must be validated before settlement.
BOOK_POLICY_MARKETS = frozenset({"FIRST_HOME_RUN"})
BOOK_RULE_VALIDATION_MARKETS = frozenset(EITHER_PITCHER_MARKETS)

# _resolve_prediction covers these families after the Either-Pitcher interpreter is
# installed. F5_TEAM_TOTALS is the one F5 market settled outside ADDITIONAL_MARKETS.
SETTLEMENT_CODE_MARKETS = frozenset(
    set(GAME_MARKETS)
    | {"F5_TEAM_TOTALS"}
    | set(ADDITIONAL_MARKETS)
    | set(EITHER_PITCHER_MARKETS)
    | set(_BATTER_FIELD_BY_MARKET)
    | set(_PITCHER_FIELD_BY_MARKET)
)


class MLBFinishLineError(ValueError):
    pass


def _load(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MLBFinishLineError(f"expected JSON object: {path}")
    return payload


def _surface_index(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    rows = payload.get("markets")
    if not isinstance(rows, list):
        raise MLBFinishLineError("market surface requires markets list")
    out: dict[str, dict[str, Any]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise MLBFinishLineError("market surface row must be object")
        market = str(raw.get("market") or "").strip().upper()
        if not market or market in out:
            raise MLBFinishLineError(f"market surface identity invalid/duplicate:{market}")
        out[market] = dict(raw)
    return out


def _provider_capability_index(payload: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if str(payload.get("provider") or "").strip().upper() != "THE_ODDS_API":
        raise MLBFinishLineError("provider capability audit must identify THE_ODDS_API")
    verified_at = str(payload.get("verified_at_utc") or "").strip()
    scope = str(payload.get("scope") or "").strip()
    source = payload.get("source")
    rows = payload.get("external_markets")
    if not verified_at or not scope or not isinstance(source, Mapping) or not isinstance(rows, Mapping):
        raise MLBFinishLineError("provider capability audit metadata incomplete")
    if not str(source.get("betting_market_catalog") or "").startswith("https://"):
        raise MLBFinishLineError("provider capability market-catalog source missing")
    if not str(source.get("event_odds_documentation") or "").startswith("https://"):
        raise MLBFinishLineError("provider capability event-odds source missing")
    out: dict[str, dict[str, Any]] = {}
    for market, raw in rows.items():
        name = str(market).strip().upper()
        if not name or name in out or not isinstance(raw, Mapping):
            raise MLBFinishLineError(f"provider capability row invalid/duplicate:{name}")
        row = dict(raw)
        if str(row.get("status") or "") != "NO_PUBLISHED_EQUIVALENT":
            raise MLBFinishLineError(f"unsupported provider capability status:{name}")
        if not str(row.get("checked_equivalent") or "").strip() or not str(row.get("reason") or "").strip():
            raise MLBFinishLineError(f"provider capability row incomplete:{name}")
        out[name] = row
    try:
        declared_count = int(payload.get("external_market_count"))
    except (TypeError, ValueError) as exc:
        raise MLBFinishLineError("provider capability external_market_count invalid") from exc
    if declared_count != len(out):
        raise MLBFinishLineError("provider capability external_market_count mismatch")
    metadata = {
        "provider": "THE_ODDS_API",
        "verified_at_utc": verified_at,
        "scope": scope,
        "source": dict(source),
        "external_market_count": declared_count,
    }
    return out, metadata


def _requires_structural_revalidation(dep: Mapping[str, Any], beh: Mapping[str, Any]) -> bool:
    remediation = str(beh.get("remediation_state") or "").upper()
    status = str(beh.get("status") or "UNVERIFIED").upper()
    stage = str(dep.get("stage") or "").upper()
    if "PARAMETERS_UNVALIDATED" in remediation:
        return True
    if not any(token in remediation for token in ("REVALIDATION_REQUIRED", "EVIDENCE_REQUIRED")):
        return False
    # A measured incumbent does not become structurally unmeasured merely because
    # an unpromoted challenger exists. Candidate deployments, however, must earn
    # their own behavioral evidence before promotion.
    return status != "KEEP_MEASURED" or "CANDIDATE" in stage


def build_mlb_finish_line(
    *,
    surface_path: str | Path = DEFAULT_SURFACE,
    deployments_path: str | Path = DEFAULT_DEPLOYMENTS,
    behavioral_path: str | Path = DEFAULT_BEHAVIORAL,
    validation_path: str | Path = DEFAULT_VALIDATION,
    provider_capability_path: str | Path = DEFAULT_PROVIDER_CAPABILITY,
) -> dict[str, Any]:
    acceptance = build_acceptance_matrix(
        deployments_path=deployments_path,
        behavioral_path=behavioral_path,
        validation_path=validation_path,
    )
    acceptance_rows = {str(row["market"]): dict(row) for row in acceptance["markets"]}
    catalog = set(acceptance_rows)
    surface = _surface_index(_load(surface_path))
    provider_capability, provider_metadata = _provider_capability_index(_load(provider_capability_path))
    deployments = _load(deployments_path).get("markets")
    behavioral = _load(behavioral_path).get("markets")
    validation = _load(validation_path).get("markets")
    if not all(isinstance(x, Mapping) for x in (deployments, behavioral, validation)):
        raise MLBFinishLineError("canonical registries require markets objects")
    engines = engine_registry()

    registries = {
        "surface": set(surface),
        "deployments": set(map(str, deployments)),
        "behavioral": set(map(str, behavioral)),
        "validation": set(map(str, validation)),
        "settlement_code": set(SETTLEMENT_CODE_MARKETS),
    }
    for label, names in registries.items():
        if names != catalog:
            raise MLBFinishLineError(
                f"finish-line catalog mismatch {label}: missing={sorted(catalog-names)} extra={sorted(names-catalog)}"
            )

    surface_external = {
        market for market, spec in surface.items() if spec.get("provider_expected") is not True
    }
    if set(provider_capability) != surface_external:
        raise MLBFinishLineError(
            "provider capability/surface mismatch "
            f"missing={sorted(surface_external-set(provider_capability))} "
            f"extra={sorted(set(provider_capability)-surface_external)}"
        )

    rows = []
    for market in sorted(catalog):
        dep = dict(deployments[market])
        beh = dict(behavioral[market])
        val = dict(validation[market])
        spec = surface[market]
        acceptance_row = acceptance_rows[market]
        runtime_engine = market in engines
        registered = market in deployments
        settlement_code = market in SETTLEMENT_CODE_MARKETS
        code_complete = bool(runtime_engine and registered and settlement_code)

        provider_expected = spec.get("provider_expected") is True
        acquisition_route = str(spec.get("acquisition_route") or "").strip()
        acquisition_external = not provider_expected
        if provider_expected and (not acquisition_route or acquisition_route == "UNMAPPED_PROVIDER_MARKET"):
            raise MLBFinishLineError(f"provider-expected market lacks acquisition route:{market}")
        if acquisition_external and str(spec.get("terminal_if_absent") or "") != "PROVIDER_UNSUPPORTED":
            raise MLBFinishLineError(f"external-provider market lacks fail-closed terminal state:{market}")

        validation_missing = list(acceptance_row["current_state"]["validation_missing"])
        blockers: list[str] = []
        if not code_complete:
            blockers.append("CODE_MISSING")
        if acquisition_external:
            blockers.append("EXTERNAL_PROVIDER_REQUIRED")
        if market in BOOK_POLICY_MARKETS:
            blockers.append("BOOK_POLICY_NORMALIZATION_REQUIRED")
        if market in BOOK_RULE_VALIDATION_MARKETS:
            blockers.append("BOOK_RULE_VALIDATION_REQUIRED")
        remediation = str(beh.get("remediation_state") or "")
        if _requires_structural_revalidation(dep, beh):
            blockers.append("STRUCTURAL_OR_BEHAVIORAL_REVALIDATION_REQUIRED")
        if validation_missing:
            blockers.append("VALIDATION_EVIDENCE_REQUIRED")

        if "CODE_MISSING" in blockers:
            primary = "CODE_MISSING"
        elif "EXTERNAL_PROVIDER_REQUIRED" in blockers:
            primary = "EXTERNAL_PROVIDER_REQUIRED"
        elif "BOOK_POLICY_NORMALIZATION_REQUIRED" in blockers:
            primary = "BOOK_POLICY_NORMALIZATION_REQUIRED"
        elif "BOOK_RULE_VALIDATION_REQUIRED" in blockers:
            primary = "BOOK_RULE_VALIDATION_REQUIRED"
        elif "STRUCTURAL_OR_BEHAVIORAL_REVALIDATION_REQUIRED" in blockers:
            primary = "STRUCTURAL_OR_BEHAVIORAL_REVALIDATION_REQUIRED"
        elif "VALIDATION_EVIDENCE_REQUIRED" in blockers:
            primary = "VALIDATION_EVIDENCE_REQUIRED"
        else:
            primary = "ACCEPTANCE_COMPLETE" if acceptance_row["acceptance_complete"] else "REVIEW_REQUIRED"

        rows.append({
            "market": market,
            "runtime_engine_present": runtime_engine,
            "deployment_registered": registered,
            "deployment_stage": str(dep.get("stage") or ""),
            "deployment_eligible": dep.get("eligible") is True,
            "settlement_interpreter_present": settlement_code,
            "engineering_code_complete": code_complete,
            "provider_expected": provider_expected,
            "acquisition_route": acquisition_route,
            "acquisition_state": "PROVIDER_ROUTE_DECLARED" if provider_expected else "EXTERNAL_PROVIDER_REQUIRED",
            "provider_capability_basis": None if provider_expected else dict(provider_capability[market]),
            "behavioral_status": str(beh.get("status") or ""),
            "remediation_state": remediation,
            "validation_missing": validation_missing,
            "acceptance_complete": bool(acceptance_row["acceptance_complete"]),
            "primary_blocker": primary,
            "blockers": blockers,
        })

    code_missing = [row["market"] for row in rows if not row["engineering_code_complete"]]
    external = [row["market"] for row in rows if row["acquisition_state"] == "EXTERNAL_PROVIDER_REQUIRED"]
    book_policy = [row["market"] for row in rows if "BOOK_POLICY_NORMALIZATION_REQUIRED" in row["blockers"]]
    book_rule = [row["market"] for row in rows if "BOOK_RULE_VALIDATION_REQUIRED" in row["blockers"]]
    structural = [row["market"] for row in rows if "STRUCTURAL_OR_BEHAVIORAL_REVALIDATION_REQUIRED" in row["blockers"]]
    return {
        "schema_version": 2,
        "market_count": len(rows),
        "engineering_finish_line_complete": not code_missing,
        "evidence_finish_line_complete": all(bool(row["acceptance_complete"]) for row in rows),
        "code_missing_markets": code_missing,
        "external_provider_markets": external,
        "provider_capability_audit": provider_metadata,
        "book_policy_markets": book_policy,
        "book_rule_validation_markets": book_rule,
        "structural_revalidation_markets": structural,
        "acceptance_complete_count": sum(bool(row["acceptance_complete"]) for row in rows),
        "markets": rows,
    }
