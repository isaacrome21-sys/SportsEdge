"""Post-decision outcome and governed close binding for NFL attempt-9 Model_P.

This module can only enrich an already immutable prospective decision. It never
rewrites that decision and grants no promotion, Truth Gate, OFFICIAL, or staking
authority.
"""
from __future__ import annotations

from datetime import timedelta
from math import isfinite
from pathlib import Path
from typing import Any, Mapping
import json

from .attempt9_prospective import (
    NFLAttempt9ProspectiveError,
    canonical_sha256,
    validate_decision,
)

SCHEMA = "SPORTSEDGE_NFL_ATTEMPT9_PROSPECTIVE_EVIDENCE_V1"
STATUS = "PROSPECTIVE_OUTCOME_AND_CLV_BOUND_NOT_PROMOTED"


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise NFLAttempt9ProspectiveError(code)


def _finite(value: Any, code: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NFLAttempt9ProspectiveError(code) from exc
    _require(isfinite(out), code)
    return out


def _hex(value: Any, n: int, code: str) -> str:
    text = str(value or "").strip().lower()
    _require(len(text) == n and all(c in "0123456789abcdef" for c in text), code)
    return text


def _dt(value: Any, code: str):
    from datetime import datetime, timezone
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise NFLAttempt9ProspectiveError(code) from exc
    _require(out.tzinfo is not None and out.utcoffset() is not None, code)
    return out.astimezone(timezone.utc)


def implied_probability(price: Any) -> float:
    p = _finite(price, "NFL_A9_EVIDENCE_PRICE_INVALID")
    _require(p != 0.0, "NFL_A9_EVIDENCE_PRICE_INVALID")
    return 100.0 / (100.0 + p) if p > 0 else (-p) / ((-p) + 100.0)


def novig_probability(price: Any, opposite_price: Any) -> float:
    a, b = implied_probability(price), implied_probability(opposite_price)
    return a / (a + b)


def _settle(decision: Mapping[str, Any], *, home_score: int, away_score: int) -> str:
    line = _finite(decision.get("line"), "NFL_A9_EVIDENCE_LINE_INVALID")
    selection = str(decision.get("selection") or "").lower()
    if decision.get("market") == "spread":
        value = float(home_score - away_score) + line
        if selection == "away":
            value = -value
    elif decision.get("market") == "total":
        value = float(home_score + away_score) - line
        if selection == "under":
            value = -value
    else:
        raise NFLAttempt9ProspectiveError("NFL_A9_EVIDENCE_MARKET_UNSUPPORTED")
    _require(abs(value) > 1e-12, "NFL_A9_EVIDENCE_UNEXPECTED_PUSH")
    return "WIN" if value > 0 else "LOSS"


def build_evidence(
    decision: Mapping[str, Any],
    *,
    artifact: Mapping[str, Any],
    closing_quote_at_utc: str,
    closing_book: str,
    closing_line: float,
    closing_price_american: float,
    closing_opposite_price_american: float,
    closing_quote_sha256: str,
    settled_at_utc: str,
    home_score: int,
    away_score: int,
    settlement_source_sha256: str,
) -> dict[str, Any]:
    decision_sha = validate_decision(decision, artifact=artifact)
    kickoff = _dt(decision.get("kickoff_utc"), "NFL_A9_EVIDENCE_KICKOFF_INVALID")
    close_at = _dt(closing_quote_at_utc, "NFL_A9_EVIDENCE_CLOSE_TIME_INVALID")
    settled_at = _dt(settled_at_utc, "NFL_A9_EVIDENCE_SETTLEMENT_TIME_INVALID")
    _require(kickoff - timedelta(minutes=30) <= close_at <= kickoff - timedelta(minutes=15),
             "NFL_A9_EVIDENCE_CLOSE_OUTSIDE_GOVERNED_WINDOW")
    _require(settled_at > kickoff, "NFL_A9_EVIDENCE_SETTLEMENT_NOT_POSTGAME")
    _require(str(closing_book or "").strip().lower() == decision.get("book"),
             "NFL_A9_EVIDENCE_BOOK_MISMATCH")
    close_line = _finite(closing_line, "NFL_A9_EVIDENCE_LINE_INVALID")
    _require(abs(close_line - float(decision["line"])) <= 1e-12,
             "NFL_A9_EVIDENCE_ORIGINAL_THRESHOLD_MISSING")
    _require(isinstance(home_score, int) and not isinstance(home_score, bool) and home_score >= 0,
             "NFL_A9_EVIDENCE_HOME_SCORE_INVALID")
    _require(isinstance(away_score, int) and not isinstance(away_score, bool) and away_score >= 0,
             "NFL_A9_EVIDENCE_AWAY_SCORE_INVALID")
    close_qsha = _hex(closing_quote_sha256, 64, "NFL_A9_EVIDENCE_CLOSE_QUOTE_SHA_INVALID")
    settlement_sha = _hex(settlement_source_sha256, 64, "NFL_A9_EVIDENCE_SETTLEMENT_SHA_INVALID")
    decision_novig = novig_probability(decision["price_american"], decision.get("opposite_price_american")) if decision.get("opposite_price_american") is not None else None
    _require(decision_novig is not None, "NFL_A9_EVIDENCE_DECISION_TWO_SIDED_PRICE_REQUIRED")
    closing_novig = novig_probability(closing_price_american, closing_opposite_price_american)
    row = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "decision_sha256": decision_sha,
        "game_id": decision["game_id"],
        "market": decision["market"],
        "selection": decision["selection"],
        "decision_line": float(decision["line"]),
        "decision_price_american": float(decision["price_american"]),
        "decision_novig_probability": float(decision_novig),
        "closing_quote_at_utc": close_at.isoformat(),
        "closing_book": str(closing_book).strip().lower(),
        "closing_line": close_line,
        "closing_price_american": _finite(closing_price_american, "NFL_A9_EVIDENCE_PRICE_INVALID"),
        "closing_opposite_price_american": _finite(closing_opposite_price_american, "NFL_A9_EVIDENCE_PRICE_INVALID"),
        "closing_novig_probability": float(closing_novig),
        "clv": float(closing_novig - decision_novig),
        "closing_quote_sha256": close_qsha,
        "settled_at_utc": settled_at.isoformat(),
        "home_score": home_score,
        "away_score": away_score,
        "outcome": _settle(decision, home_score=home_score, away_score=away_score),
        "settlement_source_sha256": settlement_sha,
        "model_p_id": decision["model_p_id"],
        "model_p_artifact_sha256": decision["model_p_artifact_sha256"],
        "capture_code_git_sha": decision["capture_code_git_sha"],
        "training_source_sha256": decision["training_source_sha256"],
        "backfilled": False,
        "promotion_authority": False,
        "truth_gate_pass": False,
        "official_authority": False,
        "staking_authority": False,
    }
    row["evidence_sha256"] = canonical_sha256(row)
    return row


def validate_evidence(row: Mapping[str, Any], decision: Mapping[str, Any], *, artifact: Mapping[str, Any]) -> str:
    rebuilt = build_evidence(
        decision, artifact=artifact,
        closing_quote_at_utc=str(row.get("closing_quote_at_utc") or ""),
        closing_book=str(row.get("closing_book") or ""),
        closing_line=row.get("closing_line"),
        closing_price_american=row.get("closing_price_american"),
        closing_opposite_price_american=row.get("closing_opposite_price_american"),
        closing_quote_sha256=str(row.get("closing_quote_sha256") or ""),
        settled_at_utc=str(row.get("settled_at_utc") or ""),
        home_score=row.get("home_score"),
        away_score=row.get("away_score"),
        settlement_source_sha256=str(row.get("settlement_source_sha256") or ""),
    )
    _require(dict(row) == rebuilt, "NFL_A9_EVIDENCE_REPLAY_MISMATCH")
    return str(rebuilt["evidence_sha256"])


def write_evidence_once(path: str | Path, row: Mapping[str, Any], decision: Mapping[str, Any], *, artifact: Mapping[str, Any]) -> bool:
    validate_evidence(row, decision, artifact=artifact)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(dict(row), sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    try:
        with target.open("x", encoding="utf-8") as handle:
            handle.write(payload)
        return True
    except FileExistsError:
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise NFLAttempt9ProspectiveError("NFL_A9_EVIDENCE_EXISTING_RECORD_INVALID") from exc
        validate_evidence(existing, decision, artifact=artifact)
        _require(existing.get("evidence_sha256") == row.get("evidence_sha256"),
                 "NFL_A9_EVIDENCE_IMMUTABLE_CONFLICT")
        return False
