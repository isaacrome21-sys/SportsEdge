"""Immutable prospective decision records for the frozen NFL attempt-9 Model_P owner.

This module creates evidence rows, not promotion. A record is valid only when
the frozen Model_P artifact verifies, the probability was created strictly
pregame, and the row is bound to exact model/code/source and quote identity.
Outcomes and closing prices are deliberately absent at decision-write time.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Mapping

from .attempt9_model_p import MODEL_P_ID, model_probability, verify_model_p_artifact

SCHEMA = "SPORTSEDGE_NFL_ATTEMPT9_PROSPECTIVE_MODEL_P_DECISION_V1"
STATUS = "PROSPECTIVE_MODEL_P_DECISION_CAPTURED_NOT_PROMOTED"
ALLOWED_MARKETS = frozenset({"spread", "total"})


class NFLAttempt9ProspectiveError(ValueError):
    pass


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise NFLAttempt9ProspectiveError(code)


def _dt(value: Any, code: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise NFLAttempt9ProspectiveError(code) from exc
    _require(out.tzinfo is not None and out.utcoffset() is not None, code)
    return out.astimezone(timezone.utc)


def _hex(value: Any, n: int, code: str) -> str:
    text = str(value or "").strip().lower()
    _require(len(text) == n and all(c in "0123456789abcdef" for c in text), code)
    return text


def _finite(value: Any, code: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLAttempt9ProspectiveError(code) from exc
    _require(isfinite(out), code)
    return out


def canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return sha256(raw).hexdigest()


def build_decision(
    *,
    artifact: Mapping[str, Any],
    game_id: str,
    kickoff_utc: str,
    decision_at_utc: str,
    feature_asof_utc: str,
    quote_observed_at_utc: str,
    capture_code_git_sha: str,
    book: str,
    quote_sha256: str,
    market: str,
    selection: str,
    line: float,
    price_american: float,
    raw_prediction: float,
) -> dict[str, Any]:
    artifact_sha = verify_model_p_artifact(artifact)
    _require(str(artifact.get("model_p_id") or "") == MODEL_P_ID, "NFL_A9_LEDGER_MODEL_ID_MISMATCH")
    market_key = str(market or "").strip().lower()
    _require(market_key in ALLOWED_MARKETS, "NFL_A9_LEDGER_MARKET_UNSUPPORTED")
    kickoff = _dt(kickoff_utc, "NFL_A9_LEDGER_KICKOFF_INVALID")
    decision_at = _dt(decision_at_utc, "NFL_A9_LEDGER_DECISION_TIME_INVALID")
    feature_asof = _dt(feature_asof_utc, "NFL_A9_LEDGER_FEATURE_ASOF_INVALID")
    quote_at = _dt(quote_observed_at_utc, "NFL_A9_LEDGER_QUOTE_TIME_INVALID")
    _require(feature_asof <= decision_at < kickoff, "NFL_A9_LEDGER_PIT_VIOLATION")
    _require(quote_at <= decision_at < kickoff, "NFL_A9_LEDGER_QUOTE_PIT_VIOLATION")
    _require(bool(str(game_id).strip()), "NFL_A9_LEDGER_GAME_ID_REQUIRED")
    _require(bool(str(book).strip()), "NFL_A9_LEDGER_BOOK_REQUIRED")
    code_sha = _hex(capture_code_git_sha, 40, "NFL_A9_LEDGER_CODE_SHA_INVALID")
    qsha = _hex(quote_sha256, 64, "NFL_A9_LEDGER_QUOTE_SHA_INVALID")
    price = _finite(price_american, "NFL_A9_LEDGER_PRICE_INVALID")
    _require(price != 0.0, "NFL_A9_LEDGER_PRICE_INVALID")
    p = model_probability(
        artifact,
        market=market_key,
        raw_prediction=_finite(raw_prediction, "NFL_A9_LEDGER_PREDICTION_INVALID"),
        line=_finite(line, "NFL_A9_LEDGER_LINE_INVALID"),
        selection=selection,
    )
    row = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "game_id": str(game_id).strip(),
        "kickoff_utc": kickoff.isoformat(),
        "decision_at_utc": decision_at.isoformat(),
        "feature_asof_utc": feature_asof.isoformat(),
        "quote_observed_at_utc": quote_at.isoformat(),
        "capture_code_git_sha": code_sha,
        "model_p_id": MODEL_P_ID,
        "model_p_artifact_sha256": artifact_sha,
        "runtime_artifact_sha256": str(artifact["runtime_artifact_sha256"]).lower(),
        "training_source_sha256": str(artifact["source_sha256"]).lower(),
        "book": str(book).strip().lower(),
        "quote_sha256": qsha,
        "market": market_key,
        "selection": str(selection).strip().lower(),
        "line": float(line),
        "price_american": price,
        "raw_prediction": float(raw_prediction),
        "model_p": float(p["model_p"]),
        "push_probability": float(p["push_probability"]),
        "outcome": None,
        "closing_market": None,
        "backfilled": False,
        "promotion_authority": False,
        "truth_gate_pass": False,
        "official_authority": False,
        "staking_authority": False,
    }
    row["decision_sha256"] = canonical_sha256(row)
    return row


def validate_decision(row: Mapping[str, Any]) -> str:
    _require(row.get("schema_version") == SCHEMA, "NFL_A9_LEDGER_SCHEMA_INVALID")
    _require(row.get("status") == STATUS, "NFL_A9_LEDGER_STATUS_INVALID")
    _require(row.get("model_p_id") == MODEL_P_ID, "NFL_A9_LEDGER_MODEL_ID_MISMATCH")
    _require(row.get("market") in ALLOWED_MARKETS, "NFL_A9_LEDGER_MARKET_UNSUPPORTED")
    _require(row.get("outcome") is None and row.get("closing_market") is None, "NFL_A9_LEDGER_FUTURE_DATA_FORBIDDEN")
    _require(row.get("backfilled") is False, "NFL_A9_LEDGER_BACKFILL_FORBIDDEN")
    for key in ("promotion_authority", "truth_gate_pass", "official_authority", "staking_authority"):
        _require(row.get(key) is False, f"NFL_A9_LEDGER_AUTHORITY_INVALID:{key}")
    kickoff = _dt(row.get("kickoff_utc"), "NFL_A9_LEDGER_KICKOFF_INVALID")
    decision = _dt(row.get("decision_at_utc"), "NFL_A9_LEDGER_DECISION_TIME_INVALID")
    feature = _dt(row.get("feature_asof_utc"), "NFL_A9_LEDGER_FEATURE_ASOF_INVALID")
    quote = _dt(row.get("quote_observed_at_utc"), "NFL_A9_LEDGER_QUOTE_TIME_INVALID")
    _require(feature <= decision < kickoff and quote <= decision < kickoff, "NFL_A9_LEDGER_PIT_VIOLATION")
    _hex(row.get("capture_code_git_sha"), 40, "NFL_A9_LEDGER_CODE_SHA_INVALID")
    _hex(row.get("model_p_artifact_sha256"), 64, "NFL_A9_LEDGER_ARTIFACT_SHA_INVALID")
    _hex(row.get("runtime_artifact_sha256"), 64, "NFL_A9_LEDGER_RUNTIME_SHA_INVALID")
    _hex(row.get("training_source_sha256"), 64, "NFL_A9_LEDGER_SOURCE_SHA_INVALID")
    _hex(row.get("quote_sha256"), 64, "NFL_A9_LEDGER_QUOTE_SHA_INVALID")
    price = _finite(row.get("price_american"), "NFL_A9_LEDGER_PRICE_INVALID")
    _require(price != 0.0, "NFL_A9_LEDGER_PRICE_INVALID")
    p = _finite(row.get("model_p"), "NFL_A9_LEDGER_MODEL_P_INVALID")
    _require(0.0 < p < 1.0, "NFL_A9_LEDGER_MODEL_P_INVALID")
    _require(_finite(row.get("push_probability"), "NFL_A9_LEDGER_PUSH_INVALID") == 0.0, "NFL_A9_LEDGER_PUSH_NOT_SUPPORTED")
    expected = canonical_sha256({k: v for k, v in row.items() if k != "decision_sha256"})
    _require(str(row.get("decision_sha256") or "").lower() == expected, "NFL_A9_LEDGER_DECISION_SHA_MISMATCH")
    return expected
