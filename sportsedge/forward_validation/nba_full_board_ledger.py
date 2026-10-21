"""Build durable NBA-props prospective entry records from a full board.

This is an intake adapter, not a scorer.  It joins the one-output-per-input
contract of :func:`sportsedge.nba_phone_prop_pricing.phone_nba_prop_rows`
back to the raw DraftKings quote rows, requires a complete same-capture
OVER/UNDER pair, and emits the record shape consumed by ``nba_props``.

The adapter deliberately records both runner dispositions.  One ledger row
represents one event/player/market/line pair; the evaluator, not this module,
chooses the higher-EV side from the paired prices.  Rows that are blocked,
stale, duplicated, post-tip, single-sided, or outside the four frozen families
are retained in accounting but cannot enter the prospective ledger.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sportsedge.nba_phone_prop_pricing import (
    ENGINE_ID,
    nba_prop_family_for_market,
)

FIRST_COUNTABLE_SLATE = date(2026, 10, 21)
PRICED_STATUSES = {"PRICED_RESEARCH", "RESEARCH_CANDIDATE_NOT_VALIDATED"}


class NbaFullBoardLedgerError(ValueError):
    """Fail-closed board-level error with a stable reason code."""

    def __init__(self, reason: str, detail: object | None = None) -> None:
        self.reason = reason
        self.detail = detail
        suffix = "" if detail is None else f":{json.dumps(detail, sort_keys=True, default=str)}"
        super().__init__(reason + suffix)


def _instant(value: object, reason: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise NbaFullBoardLedgerError(reason, value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NbaFullBoardLedgerError(reason, value)
    return dt.astimezone(timezone.utc)


def _declared_date(value: object, reason: str) -> date:
    """Event's CT slate date, matching the independently repaired pricer.

    The DK capture/slate pipeline is America/Chicago anchored. A UTC/Z
    instant represents the same physical tipoff but its UTC calendar date
    may be one day later; without conversion, a valid 19:30 CT Oct 21 tip
    (2026-10-22T00:30:00Z) is rejected as EVENT_OUTSIDE_SLATE. Preserve
    an explicitly declared non-UTC offset's local calendar date, exactly
    as phone_nba_prop_pricing._target_date does. Never infer an absent
    timezone, change a stored timestamp or relax pre-event chronology.
    """
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise NbaFullBoardLedgerError(reason, value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NbaFullBoardLedgerError(reason, value)
    if dt.utcoffset() == timedelta(0):
        return dt.astimezone(ZoneInfo("America/Chicago")).date()
    return dt.date()


def _finite(value: object, reason: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        raise NbaFullBoardLedgerError(reason, value)
    if not math.isfinite(out):
        raise NbaFullBoardLedgerError(reason, value)
    return out


def _norm_side(row: dict) -> str:
    return str(row.get("side") or row.get("selection") or "").upper()


def _event_start(row: dict) -> object:
    for key in ("event_start", "commence_time", "tipoff", "game_start", "start_time"):
        if row.get(key) is not None:
            return row[key]
    return None


def _captured_at(row: dict) -> object:
    return row.get("quote_captured_at") or row.get("captured_at")


def _canonical_key(raw: dict, priced: dict) -> tuple:
    return (
        str(raw.get("capture_id") or ""),
        str(raw.get("event_id") or ""),
        str(priced.get("player_id") or ""),
        str(priced.get("coverage_market") or ""),
        _finite(raw.get("line"), "LINE_INVALID"),
    )


def _side_key(raw: dict, priced: dict) -> tuple:
    return _canonical_key(raw, priced) + (_norm_side(raw),)


def _stable_id(parts: tuple) -> str:
    payload = json.dumps(parts, separators=(",", ":"), ensure_ascii=True)
    return "nba-entry-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _reject(index: int, raw: dict, priced: dict, reason: str) -> dict:
    return {
        "input_index": index,
        "reason": reason,
        "event_id": raw.get("event_id"),
        "player_name": raw.get("player_name") or raw.get("label"),
        "market": raw.get("market"),
        "side": _norm_side(raw),
        "line": raw.get("line"),
        "pricing_status": priced.get("status"),
        "pricing_blocker": priced.get("blocker"),
    }


def build_nba_props_entry_ledger(
    raw_rows: list[dict],
    priced_rows: list[dict],
    *,
    run_id: str,
    source_ref: str,
    recorded_at: str,
    slate_date: str,
) -> dict:
    """Return ledger + complete raw-to-priced accounting.

    ``priced_rows`` must be the direct one-for-one result of pricing
    ``raw_rows``.  The function never matches by player name alone and never
    invents an event id, capture id, timestamp, line, side, or opposing price.
    """
    if len(raw_rows) != len(priced_rows):
        raise NbaFullBoardLedgerError(
            "RAW_PRICED_LENGTH_MISMATCH",
            {"raw": len(raw_rows), "priced": len(priced_rows)},
        )
    if not str(run_id).strip() or not str(source_ref).strip():
        raise NbaFullBoardLedgerError("RUN_PROVENANCE_REQUIRED")
    try:
        slate = date.fromisoformat(str(slate_date))
    except ValueError:
        raise NbaFullBoardLedgerError("SLATE_DATE_INVALID", slate_date)
    if slate < FIRST_COUNTABLE_SLATE:
        raise NbaFullBoardLedgerError(
            "SLATE_BEFORE_PROSPECTIVE_BOUNDARY", str(slate)
        )
    recorded = _instant(recorded_at, "RECORDED_AT_INVALID")

    groups: dict[tuple, list[tuple[int, dict, dict]]] = defaultdict(list)
    rejected: list[dict] = []
    raw_side_keys: set[tuple] = set()
    counts = Counter(raw_rows=len(raw_rows))

    for index, (raw, priced) in enumerate(zip(raw_rows, priced_rows)):
        family = nba_prop_family_for_market(raw.get("market"))
        if family is None:
            counts["out_of_scope_rows"] += 1
            rejected.append(_reject(index, raw, priced, "MARKET_OUT_OF_SCOPE"))
            continue
        counts["in_scope_rows"] += 1
        if priced.get("coverage_market") != family:
            raise NbaFullBoardLedgerError(
                "RAW_PRICED_MARKET_MISMATCH", {"input_index": index}
            )
        side = _norm_side(raw)
        if side not in {"OVER", "UNDER"} or priced.get("side") != side:
            raise NbaFullBoardLedgerError(
                "RAW_PRICED_SIDE_MISMATCH", {"input_index": index}
            )
        if _finite(raw.get("line"), "LINE_INVALID") != _finite(
            priced.get("line"), "RAW_PRICED_LINE_MISMATCH"
        ):
            raise NbaFullBoardLedgerError(
                "RAW_PRICED_LINE_MISMATCH", {"input_index": index}
            )
        raw_price = raw.get("odds", raw.get("price"))
        priced_price = priced.get("odds", priced.get("price"))
        if _finite(raw_price, "PRICE_INVALID") != _finite(
            priced_price, "RAW_PRICED_PRICE_MISMATCH"
        ):
            raise NbaFullBoardLedgerError(
                "RAW_PRICED_PRICE_MISMATCH", {"input_index": index}
            )
        if not raw.get("capture_id") or not raw.get("event_id"):
            rejected.append(_reject(index, raw, priced, "CAPTURE_OR_EVENT_ID_MISSING"))
            counts["identity_rejected_rows"] += 1
            continue
        if str(raw.get("book") or "").strip().lower() not in {
            "draftkings", "dk"
        }:
            rejected.append(_reject(index, raw, priced, "BOOK_NOT_DRAFTKINGS"))
            counts["book_rejected_rows"] += 1
            continue
        start_value = _event_start(raw)
        capture_value = _captured_at(raw)
        start = _instant(start_value, "EVENT_START_INVALID")
        captured = _instant(capture_value, "ENTRY_CAPTURED_AT_INVALID")
        # NBA slates are named by the event timestamp's declared local date;
        # converting a 19:30 CT tip to UTC would incorrectly move it to the
        # next calendar day.
        if _declared_date(start_value, "EVENT_START_INVALID") != slate:
            rejected.append(_reject(index, raw, priced, "EVENT_OUTSIDE_SLATE"))
            counts["wrong_slate_rows"] += 1
            continue
        # A quote at/after tip is categorically late even when the
        # operator recording timestamp is earlier than the quote.
        # Preserve that classification before testing causal chronology.
        if captured >= start or recorded >= start:
            rejected.append(_reject(index, raw, priced, "ENTRY_NOT_PRE_EVENT"))
            counts["late_rows"] += 1
            continue
        if recorded < captured:
            rejected.append(_reject(index, raw, priced, "RECORDED_BEFORE_CAPTURE"))
            counts["noncausal_rows"] += 1
            continue
        if priced.get("status") not in PRICED_STATUSES:
            reason = (
                "WATCH_NOT_COUNTABLE"
                if str(priced.get("status") or "").startswith("WATCH_")
                else "UNPRICED_NOT_COUNTABLE"
            )
            rejected.append(_reject(index, raw, priced, reason))
            counts["watch_rows" if reason.startswith("WATCH") else "blocked_rows"] += 1
            continue
        stamp = priced.get("nba_prop_engine")
        if not isinstance(stamp, dict) or stamp.get("engine_id") != ENGINE_ID:
            raise NbaFullBoardLedgerError(
                "ENGINE_STAMP_MISSING_OR_MISMATCH", {"input_index": index}
            )
        skey = _side_key(raw, priced)
        if skey in raw_side_keys:
            raise NbaFullBoardLedgerError("DUPLICATE_RAW_SIDE", skey)
        raw_side_keys.add(skey)
        groups[_canonical_key(raw, priced)].append((index, raw, priced))
        counts["priced_side_rows"] += 1

    ledger: list[dict] = []
    for key in sorted(groups, key=lambda x: tuple(str(v) for v in x)):
        members = groups[key]
        by_side = {_norm_side(raw): (index, raw, priced)
                   for index, raw, priced in members}
        if set(by_side) != {"OVER", "UNDER"} or len(members) != 2:
            counts["unpaired_priced_rows"] += len(members)
            for index, raw, priced in members:
                rejected.append(_reject(index, raw, priced, "ENTRY_PAIR_INCOMPLETE"))
            continue
        oi, over_raw, over = by_side["OVER"]
        ui, under_raw, under = by_side["UNDER"]
        if _captured_at(over_raw) != _captured_at(under_raw):
            raise NbaFullBoardLedgerError("PAIR_CAPTURE_TIMESTAMP_MISMATCH", key)
        if str(over.get("player_id")) != str(under.get("player_id")):
            raise NbaFullBoardLedgerError("PAIR_PLAYER_ID_MISMATCH", key)
        for field in ("p_over", "p_under", "p_push"):
            if abs(_finite(over.get(field), "MODEL_PROBABILITY_INVALID")
                   - _finite(under.get(field), "MODEL_PROBABILITY_INVALID")) > 1e-12:
                raise NbaFullBoardLedgerError("PAIR_MODEL_DISTRIBUTION_MISMATCH", key)
        if over.get("nba_prop_engine") != under.get("nba_prop_engine"):
            raise NbaFullBoardLedgerError("PAIR_ENGINE_STAMP_MISMATCH", key)
        nonpush = float(over["p_over"]) + float(over["p_under"])
        if nonpush <= 0:
            raise NbaFullBoardLedgerError("MODEL_NONPUSH_MASS_INVALID", key)
        prices = {
            "OVER": over_raw.get("odds", over_raw.get("price")),
            "UNDER": under_raw.get("odds", under_raw.get("price")),
        }
        disposition = (
            "PICKED"
            if any(p.get("status") == "RESEARCH_CANDIDATE_NOT_VALIDATED"
                   for _, _, p in members)
            else "PASSED"
        )
        start_value = _event_start(over_raw)
        captured_value = _captured_at(over_raw)
        row_id = _stable_id(key + (str(captured_value), ENGINE_ID))
        ledger.append({
            "row_id": row_id,
            "sport": "NBA",
            "family": over["coverage_market"],
            "market": over["coverage_market"],
            "event_id": str(over_raw["event_id"]),
            "event_start": start_value,
            "home_team": over_raw.get("home") or over_raw.get("home_team"),
            "away_team": over_raw.get("away") or over_raw.get("away_team"),
            "subject_id": str(over["player_id"]),
            "subject_name": over.get("player_name"),
            "line": float(over["line"]),
            "model_version": ENGINE_ID,
            "model_p": {
                "OVER": float(over["p_over"]) / nonpush,
                "UNDER": float(over["p_under"]) / nonpush,
            },
            "model_push_probability": float(over["p_push"]),
            "entry_prices": prices,
            "entry_captured_at": captured_value,
            "recorded_at": recorded_at,
            "label": "PROSPECTIVE",
            "disposition": disposition,
            "engine_stamp": dict(over["nba_prop_engine"]),
            "capture_id": str(over_raw["capture_id"]),
            "run_id": str(run_id),
            "source_ref": str(source_ref),
            "research_only": True,
            "eligible": False,
            "promotable": False,
            "play_authority": False,
        })
        counts["paired_quote_sets"] += 1
        counts["ledger_rows"] += 1
        counts["picked_rows" if disposition == "PICKED" else "passed_rows"] += 1

    ledger.sort(key=lambda row: row["row_id"])
    encoded = json.dumps(ledger, sort_keys=True, separators=(",", ":"))
    accounting = {key: int(counts.get(key, 0)) for key in (
        "raw_rows", "in_scope_rows", "out_of_scope_rows",
        "identity_rejected_rows", "book_rejected_rows", "wrong_slate_rows",
        "late_rows", "noncausal_rows", "blocked_rows", "watch_rows", "priced_side_rows",
        "unpaired_priced_rows", "paired_quote_sets", "ledger_rows",
        "picked_rows", "passed_rows",
    )}
    accounting["conservation_ok"] = (
        accounting["ledger_rows"] == accounting["paired_quote_sets"]
        and accounting["picked_rows"] + accounting["passed_rows"]
        == accounting["ledger_rows"]
    )
    return {
        "schema": "SPORTSEDGE_NBA_PROPS_FORWARD_ENTRY_LEDGER_V1",
        "status": "PROSPECTIVE_ENTRIES_BUILT_RESEARCH_ONLY",
        "slate_date": str(slate),
        "run_id": str(run_id),
        "source_ref": str(source_ref),
        "recorded_at": recorded_at,
        "engine_id": ENGINE_ID,
        "ledger_sha256": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        "accounting": accounting,
        "ledger": ledger,
        "rejected": sorted(rejected, key=lambda row: row["input_index"]),
    }
