"""Prospective shared NFL/CFB forward-capture primitives for Promotion Evidence V2.

This module does not create Model_P or select candidates. It accepts decisions that
already satisfy the frozen WS0 evidence-unit decision contract, enforces the
prospective decision/close windows, requires two-sided prices, and builds one
append-only same-threshold close record per decision. Legacy
NFL_FORWARD_SHADOW_EV_V1 rows are deliberately not adapted or reinterpreted here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isclose
from typing import Any, Iterable, Mapping

from sports.common.ev_math import american_to_decimal, devig_power
from sports.common.evidence_unit import (
    EvidenceContractError,
    canonical_sha256,
    validate_close_observation,
    validate_decision_record,
)

SUPPORTED_SPORTS = frozenset({"NFL", "CFB"})
SPORT_KEYS = {
    "NFL": "americanfootball_nfl",
    "CFB": "americanfootball_ncaaf",
}
BOOK = "draftkings"
MAIN_MARKETS = frozenset({"h2h", "spreads", "totals"})
DECISION_MIN_LEAD = 45
DECISION_MAX_LEAD = 120
CLOSE_MIN_LEAD = 2
CLOSE_MAX_LEAD = 20
CLOSE_DEFINITION_ID = "DK_SAME_THRESHOLD_T20_T2_POWER_V1"
CLOSE_SCHEMA_VERSION = "FOOTBALL_FORWARD_CLOSE_V2"


class FootballForwardV2Error(ValueError):
    pass


def _dt(value: Any, code: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise FootballForwardV2Error(code)
    try:
        out = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise FootballForwardV2Error(code) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise FootballForwardV2Error(code)
    return out.astimezone(timezone.utc)


def _num(value: Any, code: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise FootballForwardV2Error(code) from exc
    return out


def _shared_error(exc: EvidenceContractError) -> FootballForwardV2Error:
    return FootballForwardV2Error(str(exc))


def power_fair_pair(selected_american: float, opposite_american: float) -> tuple[float, float]:
    implied = [1.0 / american_to_decimal(selected_american), 1.0 / american_to_decimal(opposite_american)]
    fair = devig_power(implied)
    return float(fair[0]), float(fair[1])


def _validate_decision_line(row: Mapping[str, Any], market: str) -> float | None:
    if "line_at_decision" not in row:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_DECISION_LINE_FIELD_MISSING")
    raw = row.get("line_at_decision")
    if market == "h2h":
        if raw not in (None, ""):
            raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_H2H_LINE_MUST_BE_EMPTY")
        return None
    if raw in (None, ""):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_DECISION_LINE_REQUIRED")
    return _num(raw, "FOOTBALL_FORWARD_V2_DECISION_LINE_INVALID")


def validate_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        out = validate_decision_record(row)
    except EvidenceContractError as exc:
        raise _shared_error(exc) from exc

    for key in ("market", "side"):
        if not str(out.get(key) or "").strip():
            raise FootballForwardV2Error(f"FOOTBALL_FORWARD_V2_CANDIDATE_FIELD_MISSING:{key}")

    sport = str(out["sport"]).upper()
    if sport not in SUPPORTED_SPORTS:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_SPORT_UNSUPPORTED")
    market = str(out["market"]).lower()
    if market not in MAIN_MARKETS:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_MARKET_UNSUPPORTED")
    if str(out["book"]).lower() != BOOK:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_BOOK_MISMATCH")
    if out["qualifies_for_evidence"] is not True:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_NOT_EVIDENCE_QUALIFIED")

    # A V2 close lane never accepts the WS0 one-sided candidate exception.
    try:
        selected_price = float(out["selected_price"])
        opposite_price = float(out["opposite_price"])
        power_fair_pair(selected_price, opposite_price)
    except (TypeError, ValueError, EvidenceContractError) as exc:
        if isinstance(exc, FootballForwardV2Error):
            raise
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_TWO_SIDED_PRICE_REQUIRED") from exc

    start = _dt(out["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID")
    model_at = _dt(out["model_p_computed_at"], "FOOTBALL_FORWARD_V2_MODEL_P_TS_INVALID")
    price_at = _dt(out["price_observed_at"], "FOOTBALL_FORWARD_V2_PRICE_TS_INVALID")
    decision_at = max(model_at, price_at)
    lead = (start - decision_at).total_seconds() / 60.0
    if not (DECISION_MIN_LEAD <= lead <= DECISION_MAX_LEAD):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_DECISION_OUTSIDE_WINDOW")

    out["sport"] = sport
    out["market"] = market
    out["side"] = str(out["side"]).strip()
    out["book"] = BOOK
    out["selected_price"] = selected_price
    out["opposite_price"] = opposite_price
    out["line_at_decision"] = _validate_decision_line(out, market)
    return out


def _validate_same_threshold(
    candidate: Mapping[str, Any],
    *,
    selected_line: float | None,
    opposite_line: float | None,
) -> tuple[float | None, float | None]:
    market = str(candidate["market"])
    decision_line = candidate.get("line_at_decision")
    if market == "h2h":
        if selected_line is not None or opposite_line is not None:
            raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_H2H_CLOSE_LINE_MUST_BE_EMPTY")
        return None, None

    if selected_line is None or opposite_line is None:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_THRESHOLD_PAIR_REQUIRED")
    selected = _num(selected_line, "FOOTBALL_FORWARD_V2_CLOSE_LINE_INVALID")
    opposite = _num(opposite_line, "FOOTBALL_FORWARD_V2_CLOSE_LINE_INVALID")
    if decision_line is None or not isclose(selected, float(decision_line), abs_tol=1e-9):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_ORIGINAL_THRESHOLD_MISMATCH")
    expected_opposite = -selected if market == "spreads" else selected
    if not isclose(opposite, expected_opposite, abs_tol=1e-9):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_PAIR_LINE_MISMATCH")
    return selected, opposite


def _close_identity(
    *,
    decision_id: str,
    observed_at: str,
    selected_price: float,
    opposite_price: float,
    selected_line: float | None,
    opposite_line: float | None,
    snapshot_sha256: str,
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "observed_at": observed_at,
        "book": BOOK,
        "selected_price": float(selected_price),
        "opposite_price": float(opposite_price),
        "selected_line": selected_line,
        "opposite_line": opposite_line,
        "snapshot_sha256": str(snapshot_sha256).strip().lower(),
        "close_definition_id": CLOSE_DEFINITION_ID,
    }


def build_close_record(
    *,
    candidate: Mapping[str, Any],
    observed_at: str,
    selected_price: float,
    opposite_price: float,
    snapshot_sha256: str,
    selected_line: float | None = None,
    opposite_line: float | None = None,
) -> dict[str, Any]:
    row = validate_candidate(candidate)
    start = _dt(row["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID")
    observed = _dt(observed_at, "FOOTBALL_FORWARD_V2_CLOSE_TS_INVALID")
    lead = (start - observed).total_seconds() / 60.0
    if not (CLOSE_MIN_LEAD <= lead <= CLOSE_MAX_LEAD):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_OUTSIDE_WINDOW")
    decision_at = max(
        _dt(row["model_p_computed_at"], "FOOTBALL_FORWARD_V2_MODEL_P_TS_INVALID"),
        _dt(row["price_observed_at"], "FOOTBALL_FORWARD_V2_PRICE_TS_INVALID"),
    )
    if observed <= decision_at:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_NOT_AFTER_DECISION")

    close_selected_line, close_opposite_line = _validate_same_threshold(
        row, selected_line=selected_line, opposite_line=opposite_line
    )
    try:
        fair_selected, fair_opposite = power_fair_pair(selected_price, opposite_price)
    except (TypeError, ValueError) as exc:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_PRICE_PAIR_INVALID") from exc

    observed_iso = observed.isoformat()
    identity = _close_identity(
        decision_id=str(row["decision_id"]),
        observed_at=observed_iso,
        selected_price=float(selected_price),
        opposite_price=float(opposite_price),
        selected_line=close_selected_line,
        opposite_line=close_opposite_line,
        snapshot_sha256=snapshot_sha256,
    )
    base = {
        "close_id": canonical_sha256(identity),
        **identity,
    }
    try:
        checked = validate_close_observation(base, decision=row)
    except EvidenceContractError as exc:
        raise _shared_error(exc) from exc

    return {
        **checked,
        "schema_version": CLOSE_SCHEMA_VERSION,
        "evidence_unit_id": row["evidence_unit_id"],
        "sport": row["sport"],
        "game_id": row["game_id"],
        "game_start_ts": start.isoformat(),
        "market": row["market"],
        "side": row["side"],
        "fair_selected_p": fair_selected,
        "fair_opposite_p": fair_opposite,
        "devig_method": "POWER_V1",
        "promotion_authority": False,
    }


def _validated_candidate_map(candidates: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        row = validate_candidate(raw)
        decision_id = str(row["decision_id"])
        if decision_id in out:
            raise FootballForwardV2Error(f"FOOTBALL_FORWARD_V2_DUPLICATE_DECISION:{decision_id}")
        out[decision_id] = row
    return out


def _validate_close_record(raw: Mapping[str, Any], *, candidate: Mapping[str, Any]) -> dict[str, Any]:
    if str(raw.get("schema_version") or "") != CLOSE_SCHEMA_VERSION:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_SCHEMA_MISMATCH")
    if str(raw.get("close_definition_id") or "") != CLOSE_DEFINITION_ID:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_DEFINITION_MISMATCH")
    if str(raw.get("devig_method") or "") != "POWER_V1":
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_DEVIG_METHOD_MISMATCH")
    for key in ("evidence_unit_id", "sport", "game_id", "market", "side"):
        if str(raw.get(key)) != str(candidate.get(key)):
            raise FootballForwardV2Error(f"FOOTBALL_FORWARD_V2_CLOSE_IDENTITY_MISMATCH:{key}")
    try:
        checked = validate_close_observation(raw, decision=candidate)
    except EvidenceContractError as exc:
        raise _shared_error(exc) from exc

    observed = _dt(checked["observed_at"], "FOOTBALL_FORWARD_V2_CLOSE_TS_INVALID")
    start = _dt(candidate["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID")
    lead = (start - observed).total_seconds() / 60.0
    if not (CLOSE_MIN_LEAD <= lead <= CLOSE_MAX_LEAD):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_OUTSIDE_WINDOW")
    decision_at = max(
        _dt(candidate["model_p_computed_at"], "FOOTBALL_FORWARD_V2_MODEL_P_TS_INVALID"),
        _dt(candidate["price_observed_at"], "FOOTBALL_FORWARD_V2_PRICE_TS_INVALID"),
    )
    if observed <= decision_at:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_NOT_AFTER_DECISION")

    selected_line, opposite_line = _validate_same_threshold(
        candidate,
        selected_line=raw.get("selected_line"),
        opposite_line=raw.get("opposite_line"),
    )
    fair_selected, fair_opposite = power_fair_pair(float(raw["selected_price"]), float(raw["opposite_price"]))
    if not isclose(float(raw.get("fair_selected_p", -1.0)), fair_selected, abs_tol=1e-12):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_FAIR_PRICE_MISMATCH")
    if not isclose(float(raw.get("fair_opposite_p", -1.0)), fair_opposite, abs_tol=1e-12):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_FAIR_PRICE_MISMATCH")

    identity = _close_identity(
        decision_id=str(candidate["decision_id"]),
        observed_at=observed.isoformat(),
        selected_price=float(raw["selected_price"]),
        opposite_price=float(raw["opposite_price"]),
        selected_line=selected_line,
        opposite_line=opposite_line,
        snapshot_sha256=str(raw["snapshot_sha256"]),
    )
    if str(raw.get("close_id") or "") != canonical_sha256(identity):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_ID_MISMATCH")
    return dict(raw)


def _validated_close_map(
    closes: Iterable[Mapping[str, Any]],
    *,
    candidates: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw in closes:
        decision_id = str(raw.get("decision_id") or "")
        candidate = candidates.get(decision_id)
        if candidate is None:
            raise FootballForwardV2Error(f"FOOTBALL_FORWARD_V2_ORPHAN_CLOSE:{decision_id}")
        if decision_id in out:
            raise FootballForwardV2Error(f"FOOTBALL_FORWARD_V2_DUPLICATE_CLOSE:{decision_id}")
        out[decision_id] = _validate_close_record(raw, candidate=candidate)
    return out


def plan_due_bulk_sports(
    candidates: Iterable[Mapping[str, Any]],
    closes: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    current = now.astimezone(timezone.utc) if now.tzinfo and now.utcoffset() is not None else None
    if current is None:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_NOW_TIMEZONE_REQUIRED")
    candidate_map = _validated_candidate_map(candidates)
    close_map = _validated_close_map(closes, candidates=candidate_map)
    due: dict[str, list[str]] = {"NFL": [], "CFB": []}
    expired: list[str] = []
    pending = 0
    for decision_id, row in candidate_map.items():
        if decision_id in close_map:
            continue
        pending += 1
        lead = (_dt(row["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID") - current).total_seconds() / 60.0
        if lead <= 0:
            expired.append(decision_id)
        elif CLOSE_MIN_LEAD <= lead <= CLOSE_MAX_LEAD:
            due[row["sport"]].append(decision_id)
    return {
        "now": current.isoformat(),
        "due_sports": sorted(sport for sport, ids in due.items() if ids),
        "due_decision_ids": {sport: sorted(ids) for sport, ids in due.items() if ids},
        "pending_unclosed": pending,
        "expired_unclosed": sorted(expired),
        "provider_request_count": sum(1 for ids in due.values() if ids),
        "request_shape": "SPORT_BULK_V1",
    }


def coverage(candidates: Iterable[Mapping[str, Any]], closes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    candidate_map = _validated_candidate_map(candidates)
    close_map = _validated_close_map(closes, candidates=candidate_map)
    total = len(candidate_map)
    closed = len(close_map)
    return {
        "eligible_candidates": total,
        "captured_closes": closed,
        "missed_closes": total - closed,
        "coverage": None if total == 0 else closed / total,
    }


__all__ = [
    "BOOK", "CLOSE_DEFINITION_ID", "CLOSE_MAX_LEAD", "CLOSE_MIN_LEAD",
    "CLOSE_SCHEMA_VERSION", "DECISION_MAX_LEAD", "DECISION_MIN_LEAD",
    "FootballForwardV2Error", "MAIN_MARKETS", "SPORT_KEYS", "SUPPORTED_SPORTS",
    "build_close_record", "coverage", "plan_due_bulk_sports", "power_fair_pair",
    "validate_candidate",
]
