"""Research-only NHL paired quote readout; no capture/source attestation or PLAY.

This intentionally sits OUTSIDE canonical RUN IT. It prices three existing
NHL frozen-rate distributions against operator-supplied, TWO-SIDED prices
without inventing an opposite side, recency, books, or fixture identities.
A source-reference or capture-ID string is not independent proof of a quote.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isclose, isfinite

from sportsedge.nhl_rate_v1_card import (
    final_score_distribution, no_vig, puck_line_probs, resolve_team, total_probs,
)

VERSION = "NHL_RATE_V1_PAIRED_RESEARCH_READOUT_V1"
MAX_QUOTE_AGE_SECONDS = 180
MAX_PAIR_SPAN_SECONDS = 150
MARKET_SIDES = {
    "MONEYLINE": {"AWAY", "HOME"},
    "TOTAL": {"OVER", "UNDER"},
    "PUCK_LINE": {"AWAY", "HOME"},
}


def _instant(value, name):
    try:
        d = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(name + "_INVALID") from exc
    if d.tzinfo is None or d.utcoffset() is None:
        raise ValueError(name + "_NAIVE")
    return d.astimezone(timezone.utc)


def _number(value, name):
    if isinstance(value, bool):
        raise ValueError(name + "_INVALID")
    try:
        x = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(name + "_INVALID") from exc
    if not isfinite(x):
        raise ValueError(name + "_NONFINITE")
    return x


def _american(value):
    number = _number(value, "NHL_ODDS")
    if not number.is_integer() or abs(number) < 100:
        raise ValueError("NHL_ODDS_INVALID")
    return int(number)


def _quote_line(value, market):
    if market == "MONEYLINE":
        if value is not None:
            raise ValueError("NHL_MONEYLINE_HAS_LINE")
        return None
    x = _number(value, "NHL_QUOTE_LINE")
    if market == "TOTAL" and x <= 0:
        raise ValueError("NHL_TOTAL_LINE_NOT_POSITIVE")
    return x


def nhl_paired_market_readout(*, away, home, event_id, event_start,
                              as_of, capture_id, market, quote_rows,
                              fixture_source_ref, quote_source_ref,
                              book="DraftKings"):
    """Price one full two-sided MARKET SET as an explicitly unverified view.

    Required row shape for each side: side, odds, line, captured_at,
    capture_id. The group also carries the asserted quote_source_ref.
    All timestamps must be genuinely recorded, timezone-aware and
    strictly before event start; the market is not read after tip.
    """
    m = str(market or "").strip().upper()
    if m not in MARKET_SIDES:
        raise ValueError("NHL_MARKET_UNSUPPORTED")
    if str(book or "").strip().casefold() not in {"draftkings", "dk"}:
        raise ValueError("NHL_BOOK_NOT_DRAFTKINGS")
    eid = str(event_id or "").strip()
    cap = str(capture_id or "").strip()
    if not eid or not cap or not str(fixture_source_ref or "").strip() or not str(quote_source_ref or "").strip():
        raise ValueError("NHL_CAPTURE_AND_SOURCE_PROVENANCE_REQUIRED")
    if not str(home or "").strip() or not str(away or "").strip() or str(home).casefold() == str(away).casefold():
        raise ValueError("NHL_FIXTURE_TEAMS_INVALID")
    start, now = _instant(event_start, "NHL_EVENT_START"), _instant(as_of, "NHL_AS_OF")
    if now >= start:
        raise ValueError("NHL_MARKET_EVENT_STARTED")
    if not isinstance(quote_rows, list) or len(quote_rows) != 2:
        raise ValueError("NHL_MARKET_TWO_SIDED_REQUIRED")
    sides, stamps = {}, []
    for row in quote_rows:
        if not isinstance(row, dict):
            raise ValueError("NHL_QUOTE_ROW_INVALID")
        side = str(row.get("side") or "").strip().upper()
        if side not in MARKET_SIDES[m] or side in sides:
            raise ValueError("NHL_MARKET_PAIR_SIDES_INVALID")
        if str(row.get("capture_id") or "").strip() != cap:
            raise ValueError("NHL_PAIR_CAPTURE_ID_MISMATCH")
        qtime = _instant(row.get("captured_at"), "NHL_QUOTE_CAPTURE_TIME")
        if qtime >= start or qtime > now:
            raise ValueError("NHL_QUOTE_NOT_PRETIP_OR_IN_FUTURE")
        if (now - qtime).total_seconds() > MAX_QUOTE_AGE_SECONDS:
            raise ValueError("NHL_QUOTE_STALE")
        sides[side] = {"odds": _american(row.get("odds")),
                       "line": _quote_line(row.get("line"), m),
                       "captured_at": qtime.isoformat()}
        stamps.append(qtime)
    if set(sides) != MARKET_SIDES[m]:
        raise ValueError("NHL_MARKET_PAIR_SIDES_INVALID")
    span = abs((stamps[0] - stamps[1]).total_seconds())
    if span > MAX_PAIR_SPAN_SECONDS:
        raise ValueError("NHL_MARKET_PAIR_CAPTURE_SPAN_EXCEEDED")
    # The caller's different-looking display names can alias the same team.
    # Validate the canonical matchup BEFORE generating any market readout.
    away_id, home_id = resolve_team(away), resolve_team(home)
    if away_id is None or home_id is None:
        raise ValueError("NHL_RATE_MODEL_TEAM_UNMAPPED")
    if away_id == home_id:
        raise ValueError("NHL_FIXTURE_SAME_CANONICAL_TEAM")
    fsd = final_score_distribution(away_id, home_id)
    if m == "MONEYLINE":
        first, second = "AWAY", "HOME"
        if any(v["line"] is not None for v in sides.values()):
            raise ValueError("NHL_MONEYLINE_HAS_LINE")
        p2 = sum(p for (hg, ag), p in fsd["dist"].items() if hg > ag)
        model_a, push, model_b = 1.0 - p2, 0.0, p2
        common_line = None
    elif m == "TOTAL":
        first, second = "OVER", "UNDER"
        common_line = sides[first]["line"]
        if not isclose(common_line, sides[second]["line"], abs_tol=1e-9):
            raise ValueError("NHL_TOTAL_PAIR_LINE_MISMATCH")
        model_a, push, model_b = total_probs(fsd, common_line)
    else:
        first, second = "AWAY", "HOME"
        common_line = sides[first]["line"]
        if not isclose(common_line, -sides[second]["line"], abs_tol=1e-9):
            raise ValueError("NHL_PUCK_LINE_PAIR_MISMATCH")
        model_a, push, model_b = puck_line_probs(fsd, common_line)
    if not isclose(model_a + model_b + push, 1.0, abs_tol=1e-8):
        raise ValueError("NHL_PROBABILITY_MASS_NONCONSERVATION")
    # Book prices on two-sided markets with possible pushes are quoted
    # on RESOLVED bets. Comparing no-vig P(side | not push) directly against
    # unconditional P(side) makes both sides look falsely overpriced when
    # push mass is present. Preserve both model distributions explicitly.
    resolved_mass = model_a + model_b
    if resolved_mass <= 0:
        raise ValueError("NHL_MODEL_NO_RESOLVED_OUTCOME_MASS")
    conditional_a, conditional_b = model_a / resolved_mass, model_b / resolved_mass
    nv_a, nv_b = no_vig(sides[first]["odds"], sides[second]["odds"])
    return {
        "schema": VERSION, "sport": "NHL", "status": "UNVALIDATED_MARKET_DIAGNOSTIC",
        "event_id": eid, "away": away, "home": home, "market": m, "book": "DraftKings",
        "line": common_line, "capture_id": cap,
        "fixture_source_ref": str(fixture_source_ref),
        "quote_source_ref": str(quote_source_ref),
        "observed_at_utc": now.isoformat(), "event_start_utc": start.isoformat(),
        "capture_span_seconds": span, "max_age_seconds": MAX_QUOTE_AGE_SECONDS,
        "first_side": first, "second_side": second,
        "quoted": {first: sides[first], second: sides[second]},
        "rate_v1_model": {first: model_a, "PUSH": push, second: model_b},
        "rate_v1_conditional_on_no_push": {first: conditional_a,
                                           second: conditional_b},
        "same_book_no_vig": {first: nv_a, second: nv_b},
        "model_minus_no_vig": {first: conditional_a - nv_a,
                               second: conditional_b - nv_b},
        "comparison_basis": "RESOLVED_WAGER_CONDITIONAL_NOT_RAW_MASS",
        "distribution_ref": "NHL_RATE_V1_STATIC_PRIORS_UNVALIDATED",
        "quote_authentication": "OPERATOR_DECLARATION_NOT_INDEPENDENTLY_VERIFIED",
        "gap_is_not_edge": True, "official_authority": False,
        "play_authority": False, "research_only": True,
    }
