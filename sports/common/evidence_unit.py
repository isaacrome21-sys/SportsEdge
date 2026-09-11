"""Shared fail-closed evidence-unit validation for Promotion Evidence V2.

This module does not promote a market, choose a bet, or create Model_P. It only
validates immutable identities and forward-record chronology so sport-specific
lanes cannot silently diverge on evidence semantics.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_LABELS = {"LOVE", "LIKE", "WATCH", "NO_PLAY"}
_CERTIFICATION = {"CANDIDATE", "PROBATION", "OFFICIAL", "BLOCKED"}
_PRICE_SOURCES = {"API", "MANUAL_SCREENSHOT", "MANUAL_FILE"}
_FORBIDDEN_FEATURE_TOKENS = {
    "odds",
    "price",
    "bookmaker",
    "market_price",
    "ticket_pct",
    "money_pct",
    "handle_pct",
    "vig",
}
_FORBIDDEN_MODEL_IMPORT_FRAGMENTS = {
    "odds_source",
    "price_adapter",
    "market_adapter",
    "bookmaker",
}


class EvidenceContractError(ValueError):
    pass


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    return sha256(raw).hexdigest()


def _sha(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if not _SHA256.fullmatch(text):
        raise EvidenceContractError(code)
    return text


def _dt(value: Any, code: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise EvidenceContractError(code)
    try:
        out = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise EvidenceContractError(code) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise EvidenceContractError(code)
    return out.astimezone(timezone.utc)


def validate_evidence_unit_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "artifact_sha256",
        "feature_schema_sha256",
        "predictive_code_manifest_sha256",
        "acquisition_code_manifest_sha256",
        "policy_sha256",
        "close_definition_id",
    )
    missing = [key for key in required if not str(value.get(key) or "").strip()]
    if missing:
        raise EvidenceContractError("EVIDENCE_UNIT_FIELDS_MISSING:" + ",".join(missing))
    out = dict(value)
    for key in required[:-1]:
        out[key] = _sha(value.get(key), f"EVIDENCE_UNIT_SHA_INVALID:{key}")
    close_id = str(value.get("close_definition_id") or "").strip()
    if not close_id:
        raise EvidenceContractError("EVIDENCE_UNIT_CLOSE_DEFINITION_ID_MISSING")
    out["close_definition_id"] = close_id
    out["evidence_unit_id"] = canonical_sha256({key: out[key] for key in required})
    return out


def assert_market_blind_feature_schema(names: Iterable[str]) -> None:
    violations = []
    for raw in names:
        name = str(raw).strip().lower()
        if not name:
            raise EvidenceContractError("FEATURE_SCHEMA_EMPTY_NAME")
        for token in _FORBIDDEN_FEATURE_TOKENS:
            if token in name:
                violations.append((name, token))
    if violations:
        details = ",".join(f"{name}:{token}" for name, token in violations)
        raise EvidenceContractError("FEATURE_SCHEMA_MARKET_FIELD_FORBIDDEN:" + details)


def assert_model_stage_market_blind(source_text: str) -> None:
    try:
        tree = ast.parse(source_text)
    except SyntaxError as exc:
        raise EvidenceContractError("MODEL_STAGE_SOURCE_INVALID") from exc
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    bad = sorted({name for name in imports for token in _FORBIDDEN_MODEL_IMPORT_FRAGMENTS if token in name.lower()})
    if bad:
        raise EvidenceContractError("MODEL_STAGE_PRICE_IMPORT_FORBIDDEN:" + ",".join(bad))


def validate_decision_record(
    value: Mapping[str, Any],
    *,
    expected_evidence_unit_id: str | None = None,
) -> dict[str, Any]:
    required = (
        "decision_id",
        "evidence_unit_id",
        "sport",
        "lane",
        "game_id",
        "game_start_ts",
        "input_manifest_sha256",
        "model_p",
        "model_p_computed_at",
        "price_observed_at",
        "book",
        "price_source",
        "candidate_label",
        "certification_status",
        "qualifying_threshold_id",
        "qualifies_for_evidence",
        "actual_bet_placed",
        "kelly_fraction_information_only",
    )
    missing = [key for key in required if key not in value or value.get(key) in (None, "")]
    if missing:
        raise EvidenceContractError("DECISION_FIELDS_MISSING:" + ",".join(missing))
    out = dict(value)
    if expected_evidence_unit_id and str(out["evidence_unit_id"]) != expected_evidence_unit_id:
        raise EvidenceContractError("DECISION_EVIDENCE_UNIT_MISMATCH")
    _sha(out.get("input_manifest_sha256"), "DECISION_INPUT_MANIFEST_SHA_INVALID")
    start = _dt(out.get("game_start_ts"), "DECISION_GAME_START_INVALID")
    model_at = _dt(out.get("model_p_computed_at"), "DECISION_MODEL_P_TS_INVALID")
    price_at = _dt(out.get("price_observed_at"), "DECISION_PRICE_TS_INVALID")
    if model_at >= start:
        raise EvidenceContractError("DECISION_MODEL_P_NOT_PREGAME")
    if price_at >= start:
        raise EvidenceContractError("DECISION_PRICE_NOT_PREGAME")
    try:
        p = float(out.get("model_p"))
        kelly = float(out.get("kelly_fraction_information_only"))
    except (TypeError, ValueError) as exc:
        raise EvidenceContractError("DECISION_NUMERIC_FIELD_INVALID") from exc
    if not 0.0 <= p <= 1.0:
        raise EvidenceContractError("DECISION_MODEL_P_OUT_OF_RANGE")
    if kelly < 0.0:
        raise EvidenceContractError("DECISION_KELLY_INFORMATION_INVALID")
    if str(out.get("candidate_label")) not in _CANDIDATE_LABELS:
        raise EvidenceContractError("DECISION_CANDIDATE_LABEL_INVALID")
    if str(out.get("certification_status")) not in _CERTIFICATION:
        raise EvidenceContractError("DECISION_CERTIFICATION_STATUS_INVALID")
    if str(out.get("price_source")) not in _PRICE_SOURCES:
        raise EvidenceContractError("DECISION_PRICE_SOURCE_INVALID")
    if not isinstance(out.get("qualifies_for_evidence"), bool) or not isinstance(out.get("actual_bet_placed"), bool):
        raise EvidenceContractError("DECISION_BOOLEAN_FIELD_INVALID")

    selected_price = out.get("selected_price")
    opposite_price = out.get("opposite_price")
    two_sided = selected_price not in (None, "") and opposite_price not in (None, "")
    if out["qualifies_for_evidence"] and not two_sided:
        raise EvidenceContractError("V2_INELIGIBLE_ONE_SIDED")
    if selected_price in (None, ""):
        raise EvidenceContractError("DECISION_SELECTED_PRICE_MISSING")
    out["v2_price_eligible"] = two_sided
    if not two_sided:
        out["v2_ineligibility_reason"] = "V2_INELIGIBLE_ONE_SIDED"
    return out


def validate_close_observation(value: Mapping[str, Any], *, decision: Mapping[str, Any]) -> dict[str, Any]:
    required = ("close_id", "decision_id", "observed_at", "book", "selected_price", "opposite_price", "snapshot_sha256")
    missing = [key for key in required if key not in value or value.get(key) in (None, "")]
    if missing:
        raise EvidenceContractError("CLOSE_FIELDS_MISSING:" + ",".join(missing))
    if str(value.get("decision_id")) != str(decision.get("decision_id")):
        raise EvidenceContractError("CLOSE_DECISION_ID_MISMATCH")
    observed = _dt(value.get("observed_at"), "CLOSE_TS_INVALID")
    start = _dt(decision.get("game_start_ts"), "DECISION_GAME_START_INVALID")
    if observed >= start:
        raise EvidenceContractError("CLOSE_NOT_PREGAME")
    if str(value.get("book")) != str(decision.get("book")):
        raise EvidenceContractError("CLOSE_BOOK_MISMATCH")
    _sha(value.get("snapshot_sha256"), "CLOSE_SNAPSHOT_SHA_INVALID")
    return dict(value)
