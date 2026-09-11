"""Prospective shared NFL/CFB forward-capture primitives for Promotion Evidence V2.

This module does not create Model_P or select candidates. It accepts already-qualified
immutable decisions, plans the frozen decision/close windows, devigs paired prices with
POWER_V1, and computes coverage. Legacy NFL_FORWARD_SHADOW_EV_V1 rows are not adapted
or reinterpreted here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from sports.common.ev_math import american_to_decimal, devig_power

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
CLOSE_DEFINITION_ID = "DK_MAINLINE_LAST_PRESTART_T20_T2_POWER_V1"


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


def validate_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "decision_id", "evidence_unit_id", "sport", "game_id", "game_start_ts",
        "market", "side", "book", "selected_price", "opposite_price",
        "price_observed_at", "qualifies_for_evidence",
    )
    missing = [k for k in required if k not in row or row.get(k) in (None, "")]
    if missing:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CANDIDATE_FIELDS_MISSING:" + ",".join(missing))
    out = dict(row)
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
    start = _dt(out["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID")
    observed = _dt(out["price_observed_at"], "FOOTBALL_FORWARD_V2_PRICE_TS_INVALID")
    if observed >= start:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_DECISION_PRICE_NOT_PREGAME")
    # V2 requires an actual pair; do not accept the one-sided candidate exception.
    try:
        float(out["selected_price"]); float(out["opposite_price"])
    except (TypeError, ValueError) as exc:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_TWO_SIDED_PRICE_REQUIRED") from exc
    out["sport"] = sport; out["market"] = market; out["book"] = BOOK
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
    closed = {str(row.get("decision_id") or "") for row in closes}
    due: dict[str, list[str]] = {"NFL": [], "CFB": []}
    expired: list[str] = []
    pending = 0
    for raw in candidates:
        row = validate_candidate(raw)
        did = str(row["decision_id"])
        if did in closed:
            continue
        pending += 1
        lead = (_dt(row["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID") - current).total_seconds() / 60.0
        if lead <= 0:
            expired.append(did)
        elif CLOSE_MIN_LEAD <= lead <= CLOSE_MAX_LEAD:
            due[row["sport"]].append(did)
    return {
        "now": current.isoformat(),
        "due_sports": sorted(sport for sport, ids in due.items() if ids),
        "due_decision_ids": {sport: sorted(ids) for sport, ids in due.items() if ids},
        "pending_unclosed": pending,
        "expired_unclosed": sorted(expired),
        "provider_request_count": sum(1 for ids in due.values() if ids),
        "request_shape": "SPORT_BULK_V1",
    }


def power_fair_pair(selected_american: float, opposite_american: float) -> tuple[float, float]:
    implied = [1.0 / american_to_decimal(selected_american), 1.0 / american_to_decimal(opposite_american)]
    fair = devig_power(implied)
    return float(fair[0]), float(fair[1])


def build_close_record(
    *,
    candidate: Mapping[str, Any],
    observed_at: str,
    selected_price: float,
    opposite_price: float,
    snapshot_sha256: str,
) -> dict[str, Any]:
    row = validate_candidate(candidate)
    start = _dt(row["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID")
    observed = _dt(observed_at, "FOOTBALL_FORWARD_V2_CLOSE_TS_INVALID")
    lead = (start - observed).total_seconds() / 60.0
    if not (CLOSE_MIN_LEAD <= lead <= CLOSE_MAX_LEAD):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_OUTSIDE_WINDOW")
    fair_selected, fair_opposite = power_fair_pair(selected_price, opposite_price)
    return {
        "schema_version": "FOOTBALL_FORWARD_CLOSE_V2",
        "decision_id": row["decision_id"],
        "evidence_unit_id": row["evidence_unit_id"],
        "sport": row["sport"],
        "game_id": row["game_id"],
        "game_start_ts": start.isoformat(),
        "market": row["market"],
        "side": row["side"],
        "book": BOOK,
        "observed_at": observed.isoformat(),
        "selected_price": float(selected_price),
        "opposite_price": float(opposite_price),
        "fair_selected_p": fair_selected,
        "fair_opposite_p": fair_opposite,
        "devig_method": "POWER_V1",
        "close_definition_id": CLOSE_DEFINITION_ID,
        "snapshot_sha256": str(snapshot_sha256),
        "promotion_authority": False,
    }


def coverage(candidates: Iterable[Mapping[str, Any]], closes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [validate_candidate(row) for row in candidates]
    close_ids = {str(row.get("decision_id") or "") for row in closes}
    closed = sum(1 for row in eligible if str(row["decision_id"]) in close_ids)
    total = len(eligible)
    return {
        "eligible_candidates": total,
        "captured_closes": closed,
        "missed_closes": total - closed,
        "coverage": None if total == 0 else closed / total,
    }


__all__ = [
    "BOOK", "CLOSE_DEFINITION_ID", "CLOSE_MAX_LEAD", "CLOSE_MIN_LEAD",
    "DECISION_MAX_LEAD", "DECISION_MIN_LEAD", "FootballForwardV2Error",
    "MAIN_MARKETS", "SPORT_KEYS", "SUPPORTED_SPORTS", "build_close_record",
    "coverage", "plan_due_bulk_sports", "power_fair_pair", "validate_candidate",
]
