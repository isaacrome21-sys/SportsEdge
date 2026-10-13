"""Canonical-path quote binding for MLB first-five-innings (F5) markets.

Until now the four F5 markets (F5_MONEYLINE, F5_RUN_LINE, F5_TOTALS,
F5_TEAM_TOTALS) were reachable only behind the manual-snapshot intake
contract (sportsedge.canonical_manual_mlb: ManualQuote rows with
source=MANUAL, both paired sides embedded in one row, and a deployment
card). The canonical card intake (artifacts/run_it_full.py) had no F5
quote binding at all, so every F5 row resolved BLOCKED / NO_QUOTE.

This module is that binding layer. It admits a canonical-intake F5 quote
only when ALL of the following validate, in this order, failing closed
with a specific F5_* reason code:

1. source/sportsbook named (F5_SOURCE_MISSING);
2. the book's event ID present (F5_EVENT_ID_MISSING);
3. an explicit period that is FIRST_5, or the book's unambiguous F5
   market identity itself (a present-but-different period, e.g. "FG",
   refuses: F5_PERIOD_UNVERIFIED -- quote_bridge tolerates "FG" for
   three F5 markets; this layer is deliberately stricter because a
   full-game quote must never bind as F5);
4. selection identity per market (team side for ML/run line, OVER/UNDER
   for totals, team + OVER/UNDER for team totals:
   F5_SELECTION_UNVERIFIED);
5. line shape per market (F5_LINE_UNVERIFIED);
6. a valid American price (F5_PRICE_UNVERIFIED);
7. a capture timestamp that parses (F5_QUOTE_TIMESTAMP_MISSING /
   F5_QUOTE_TIMESTAMP_INVALID) and is fresh at pricing time through the
   one centralized check (sportsedge.quote_freshness, 180s bound:
   F5_QUOTE_STALE);
8. fixture binding to a VERIFIED gamePk on the official StatsAPI
   schedule, with team-name and first-pitch (<=120s) cross-checks and a
   pregame capture (F5_FIXTURE_BINDING_MISSING /
   F5_FIXTURE_BINDING_MISMATCH / F5_QUOTE_NOT_PREGAME);
9. a paired counterpart: same book, same event, same fixture, opposite
   selection, line-compatible (negated for the run line), captured
   <=120s apart (F5_QUOTE_UNPAIRED / F5_PAIR_SKEW_EXCEEDED);
10. a verified settlement basis (see SETTLEMENT_BASIS below):
    F5_SETTLEMENT_BASIS_UNVERIFIED.

Settlement basis, verified from the settlement code (not assumed):
F5_RUN_LINE, F5_TOTALS and F5_TEAM_TOTALS settle from the score through
5 completed innings with explicit push handling
(mlb_additional_pit_joiner._f5_run_line_outcome / _f5_total_outcome and
mlb_catalog_prediction_settlement._team_total_outcome over facts["f5"]).
F5_MONEYLINE verifies as TWO_WAY (owner settlement ruling 2026-10-12):
DraftKings' published market rules define 2-Way Moneyline Markets as
offering no Draw/Tie selection with ties settled as Push, and its
baseball guide's first-five section offers only the two teams and
states a tied team bet pushes with the stake refunded. The settlement
type is declared explicitly in sportsedge.moneyline_settlement
(TWO_WAY for F5_MONEYLINE @ DraftKings) and the settlement code now
settles a tied score after five as PUSH through that typed model
(mlb_additional_pit_joiner._f5_moneyline_outcome via settle_moneyline);
the pricing readout's tie mass (push_p) and the settlement outcome now
agree. Undeclared books still fail closed at gate 10's code-level
equivalent (F5_MONEYLINE_TIE_POLICY_NOT_NORMALIZED in the joiner /
router hardening), because no type may be inherited by assumption.
F5_MONEYLINE therefore clears gate 10 and, like the other three F5
markets, stops only at the deployment gate below.

Feature honesty: the snapshot pricer's F5 feature assembly
(MLBAllMarketHistorySource.feature_row) depends only on a StatsAPI
opener, a retrieval instant, the resolved fixture's team IDs and its
official date -- strictly-prior inning-level linescores plus the league
prior. It consumes NO pitcher inputs and NO snapshot-contract state, so
this module assembles the identical feature rows on the canonical path
(assemble_f5_feature_rows). Nothing is fabricated: insufficient
strictly-prior history fails closed with F5_FEATURES_UNAVAILABLE.

Even a fully bound, fully featured pair does not price on the card:
config/deployments.json holds every F5 market at stage
F5_STATE_CANDIDATE with eligible=false (PIT holdout, calibration,
tie-rule/settlement validation, forward evidence and parity still
outstanding). The card stage therefore blocks at the deployment gate
with F5_DEPLOYMENT_NOT_ELIGIBLE (taxonomy NO_VALIDATION) and attaches
the bound pair, feature lineage and pricer-reachability hashes as
evidence. Eligibility is a governance decision; this layer never flips
it and never bypasses the truth gate with a raw engine readout.

Research only. No betting authority, no staking, no order placement.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .quote_freshness import (
    QUOTE_FRESH, QUOTE_FUTURE, QUOTE_INVALID, QUOTE_STALE, QUOTE_UNVERIFIED,
    check_quote_freshness,
)

F5_BINDING_VERSION = "MLB_F5_QUOTE_BINDING_V1"
CHICAGO_TZ = ZoneInfo("America/Chicago")

F5_MARKETS = frozenset({
    "F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"})

# Canonical intake spellings -> canonical F5 market. Every alias is
# itself an unambiguous first-five market identity.
F5_MARKET_ALIASES = {
    "F5_MONEYLINE": "F5_MONEYLINE", "F5_ML": "F5_MONEYLINE",
    "FIRST_FIVE_MONEYLINE": "F5_MONEYLINE",
    "F5_RUN_LINE": "F5_RUN_LINE", "F5_SPREAD": "F5_RUN_LINE",
    "FIRST_FIVE_RUN_LINE": "F5_RUN_LINE",
    "F5_TOTALS": "F5_TOTALS", "F5_TOTAL": "F5_TOTALS",
    "FIRST_FIVE_TOTAL": "F5_TOTALS", "FIRST_FIVE_TOTALS": "F5_TOTALS",
    "F5_TEAM_TOTALS": "F5_TEAM_TOTALS", "F5_TEAM_TOTAL": "F5_TEAM_TOTALS",
    "FIRST_FIVE_TEAM_TOTAL": "F5_TEAM_TOTALS",
    "FIRST_FIVE_TEAM_TOTALS": "F5_TEAM_TOTALS",
}

PERIOD_FIRST_5 = "FIRST_5"
_F5_PERIOD_TOKENS = frozenset({
    "F5", "5", "FIRST_5", "FIRST_FIVE", "FIRST_5_INNINGS",
    "FIRST_FIVE_INNINGS"})

# Same-book paired captures must be this close (the strict paired
# evaluator's 120-second synchronization bound).
MAX_PAIR_SKEW_SECONDS = 120
# Fixture first pitch vs intake kickoff tolerance (mirrors the snapshot
# lane's MANUAL_FIRST_PITCH_MISMATCH bound).
FIRST_PITCH_TOLERANCE_SECONDS = 120

# --- specific fail-closed reason codes --------------------------------
F5_MARKET_UNSUPPORTED = "F5_MARKET_UNSUPPORTED"
F5_SOURCE_MISSING = "F5_SOURCE_MISSING"
F5_EVENT_ID_MISSING = "F5_EVENT_ID_MISSING"
F5_PERIOD_UNVERIFIED = "F5_PERIOD_UNVERIFIED"
F5_SELECTION_UNVERIFIED = "F5_SELECTION_UNVERIFIED"
F5_LINE_UNVERIFIED = "F5_LINE_UNVERIFIED"
F5_PRICE_UNVERIFIED = "F5_PRICE_UNVERIFIED"
F5_QUOTE_TIMESTAMP_MISSING = "F5_QUOTE_TIMESTAMP_MISSING"
F5_QUOTE_TIMESTAMP_INVALID = "F5_QUOTE_TIMESTAMP_INVALID"
F5_QUOTE_STALE = "F5_QUOTE_STALE"
F5_FIXTURE_BINDING_MISSING = "F5_FIXTURE_BINDING_MISSING"
F5_FIXTURE_BINDING_MISMATCH = "F5_FIXTURE_BINDING_MISMATCH"
F5_QUOTE_NOT_PREGAME = "F5_QUOTE_NOT_PREGAME"
F5_QUOTE_UNPAIRED = "F5_QUOTE_UNPAIRED"
F5_PAIR_SKEW_EXCEEDED = "F5_PAIR_SKEW_EXCEEDED"
F5_CANONICAL_QUOTE_REJECTED = "F5_CANONICAL_QUOTE_REJECTED"
F5_SETTLEMENT_BASIS_UNVERIFIED = "F5_SETTLEMENT_BASIS_UNVERIFIED"
F5_FEATURES_UNAVAILABLE = "F5_FEATURES_UNAVAILABLE"
F5_PRICER_READOUT_FAILED = "F5_PRICER_READOUT_FAILED"
F5_DEPLOYMENT_NOT_ELIGIBLE = "F5_DEPLOYMENT_NOT_ELIGIBLE"
F5_CANONICAL_CARD_INTEGRATION_PENDING = "F5_CANONICAL_CARD_INTEGRATION_PENDING"
F5_BINDING_RUNTIME_UNAVAILABLE = "F5_BINDING_RUNTIME_UNAVAILABLE"

# Reason code -> canonical coverage taxonomy blocker.
BLOCKER_BY_REASON = {
    F5_MARKET_UNSUPPORTED: "NO_QUOTE",
    F5_SOURCE_MISSING: "NO_QUOTE",
    F5_EVENT_ID_MISSING: "NO_QUOTE",
    F5_PERIOD_UNVERIFIED: "NO_QUOTE",
    F5_SELECTION_UNVERIFIED: "NO_QUOTE",
    F5_LINE_UNVERIFIED: "NO_QUOTE",
    F5_PRICE_UNVERIFIED: "NO_QUOTE",
    F5_QUOTE_TIMESTAMP_MISSING: "NO_QUOTE",
    F5_QUOTE_TIMESTAMP_INVALID: "NO_QUOTE",
    F5_QUOTE_STALE: "NO_QUOTE",
    F5_FIXTURE_BINDING_MISSING: "NO_QUOTE",
    F5_FIXTURE_BINDING_MISMATCH: "NO_QUOTE",
    F5_QUOTE_NOT_PREGAME: "NO_QUOTE",
    F5_QUOTE_UNPAIRED: "NO_QUOTE",
    F5_PAIR_SKEW_EXCEEDED: "NO_QUOTE",
    F5_CANONICAL_QUOTE_REJECTED: "NO_QUOTE",
    F5_SETTLEMENT_BASIS_UNVERIFIED: "NO_SETTLEMENT",
    F5_FEATURES_UNAVAILABLE: "NO_DATA",
    F5_PRICER_READOUT_FAILED: "NO_ENGINE",
    F5_DEPLOYMENT_NOT_ELIGIBLE: "NO_VALIDATION",
    F5_CANONICAL_CARD_INTEGRATION_PENDING: "NO_ENGINE",
    F5_BINDING_RUNTIME_UNAVAILABLE: "NO_ENGINE",
}

# Settlement basis per market, verified from the settlement code paths
# named in each entry -- not from documentation or market convention.
SETTLEMENT_BASIS = {
    "F5_MONEYLINE": {
        "status": "VERIFIED",
        "settlement_type": "TWO_WAY",
        "basis": "VERIFIED_TWO_WAY -- leader after 5 completed innings "
                 "wins; a tied score after five is a PUSH (stake "
                 "returned), never a loss and never a draw outcome. "
                 "DraftKings offers only the two teams for the F5 "
                 "moneyline (no Draw selection) and publishes that a "
                 "tied team bet pushes with the stake refunded; its "
                 "market-rules taxonomy classifies that as a 2-Way "
                 "Moneyline Market. The settlement code settles ties "
                 "through the explicitly declared TWO_WAY type "
                 "(sportsedge.moneyline_settlement), consistent with "
                 "the pricing readout's separate push_p tie mass.",
        "verified_in": (
            "sportsedge/moneyline_settlement.py:"
            "declared_moneyline_settlement_type(F5_MONEYLINE, "
            "DraftKings)=TWO_WAY; "
            "sportsedge/mlb_additional_pit_joiner.py:"
            "_f5_moneyline_outcome via settle_moneyline"),
        "rules_sources": (
            "https://sportsbook.draftkings.com/help/how-to-bet/"
            "baseball-betting-guide",
            "https://sportsbook.draftkings.com/help/"
            "general-betting-rules/market-rules"),
    },
    "F5_RUN_LINE": {
        "status": "VERIFIED",
        "basis": "Score through 5 completed innings; selected team's "
                 "runs plus the line vs the opponent's runs; exact "
                 "equality is a PUSH.",
        "verified_in": (
            "sportsedge/mlb_additional_pit_joiner.py:"
            "_f5_run_line_outcome"),
    },
    "F5_TOTALS": {
        "status": "VERIFIED",
        "basis": "Combined runs through 5 completed innings vs the "
                 "line; OVER wins above, UNDER below, exact equality "
                 "is a PUSH.",
        "verified_in": (
            "sportsedge/mlb_additional_pit_joiner.py:_f5_total_outcome"),
    },
    "F5_TEAM_TOTALS": {
        "status": "VERIFIED",
        "basis": "Selected team's runs through 5 completed innings "
                 "(facts['f5']) vs the line; OVER wins above, UNDER "
                 "below, exact equality is a PUSH.",
        "verified_in": (
            "sportsedge/mlb_catalog_prediction_settlement.py:"
            "_team_total_outcome over facts['f5']"),
    },
}


class F5BindingError(ValueError):
    """One quote's admissibility failure: a specific code + detail."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class F5FeatureAssemblyError(ValueError):
    pass


def normalize_f5_market(value: Any) -> str | None:
    """Canonical F5 market for an intake spelling, else None."""
    return F5_MARKET_ALIASES.get(str(value or "").strip().upper())


def settlement_basis(market: str) -> dict[str, Any]:
    return dict(SETTLEMENT_BASIS[market])


def _norm_name(value: Any) -> str:
    return " ".join(
        str(value or "").strip().lower().replace(".", "").split())


def _parse_time(value: Any, code: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(
                str(value or "").strip().replace("Z", "+00:00"))
        except (ValueError, TypeError) as exc:
            raise F5BindingError(code, f"unparseable timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise F5BindingError(code, "timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _american(value: Any) -> int | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not isfinite(numeric) or numeric != int(numeric):
        return None
    price = int(numeric)
    if price == 0 or -100 < price < 100:
        return None
    return price


def _line(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


_TEAM_SIDE_TOKENS = {
    "HOME": "HOME", "HOME_ML": "HOME", "HOME_RL": "HOME",
    "AWAY": "AWAY", "AWAY_ML": "AWAY", "AWAY_RL": "AWAY",
}


def _parse_quote(row: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """Validate one intake row's own admissibility (pre-fixture/pairing).

    Returns a normalized quote dict; raises F5BindingError otherwise.
    """
    market = normalize_f5_market(row.get("market"))
    if market is None:
        raise F5BindingError(
            F5_MARKET_UNSUPPORTED,
            f"not an F5 market: {row.get('market')!r}")
    book_raw = str(row.get("book") or row.get("sportsbook") or "").strip()
    if not book_raw:
        raise F5BindingError(
            F5_SOURCE_MISSING, "quote names no sportsbook/source")
    event_id = str(row.get("event_id") or row.get("source_event_id")
                   or "").strip()
    if not event_id:
        raise F5BindingError(
            F5_EVENT_ID_MISSING,
            "quote carries no sportsbook event ID to bind to the fixture")
    game_pk_raw = row.get("game_pk")
    if game_pk_raw in (None, ""):
        game_pk_raw = row.get("game_id")
    try:
        game_pk = int(str(game_pk_raw).strip())
    except (TypeError, ValueError):
        game_pk = None
    if game_pk is None or game_pk <= 0:
        raise F5BindingError(
            F5_FIXTURE_BINDING_MISSING,
            "quote carries no verified MLB gamePk identity")

    # Period: an explicit period must be FIRST_5; absent a period field,
    # the book's F5 market identity (the market spelling itself) binds.
    period_raw = row.get("period")
    if period_raw not in (None, ""):
        token = str(period_raw).strip().upper().replace(" ", "_")
        if token not in _F5_PERIOD_TOKENS:
            raise F5BindingError(
                F5_PERIOD_UNVERIFIED,
                f"period {period_raw!r} is not explicitly FIRST_5; an "
                "ambiguous or full-game period refuses")
        period_basis = "EXPLICIT"
    else:
        period_basis = "MARKET_IDENTITY"

    side_raw = str(row.get("side") or row.get("selection") or "").strip().upper()
    line_raw = row.get("line")
    team_side = None
    if market in ("F5_MONEYLINE", "F5_RUN_LINE"):
        side = _TEAM_SIDE_TOKENS.get(side_raw)
        if side is None:
            raise F5BindingError(
                F5_SELECTION_UNVERIFIED,
                f"{market} selection must be a team side (HOME/AWAY), "
                f"got {side_raw!r}")
    else:
        if side_raw not in ("OVER", "UNDER"):
            raise F5BindingError(
                F5_SELECTION_UNVERIFIED,
                f"{market} selection must be OVER or UNDER, got {side_raw!r}")
        side = side_raw
    if market == "F5_MONEYLINE":
        line = _line(line_raw)
        if line is None:
            if line_raw not in (None, ""):
                raise F5BindingError(
                    F5_LINE_UNVERIFIED,
                    f"F5 moneyline line is not numeric: {line_raw!r}")
            line = 0.0
        elif line != 0.0:
            raise F5BindingError(
                F5_LINE_UNVERIFIED,
                "an F5 moneyline carrying a nonzero line is a different "
                "contract")
    else:
        line = _line(line_raw)
        if line is None:
            raise F5BindingError(
                F5_LINE_UNVERIFIED,
                f"{market} requires a numeric line, got {line_raw!r}")
        if market in ("F5_TOTALS", "F5_TEAM_TOTALS") and line < 0:
            raise F5BindingError(
                F5_LINE_UNVERIFIED, f"{market} line must be >= 0")
    if market == "F5_TEAM_TOTALS":
        raw_team_side = str(row.get("team_side") or "").strip().upper()
        if raw_team_side in ("HOME", "AWAY"):
            team_side = raw_team_side
        elif not (row.get("team") or row.get("team_id")):
            raise F5BindingError(
                F5_SELECTION_UNVERIFIED,
                "F5 team total names no team (team_side, team or "
                "team_id required)")

    price = _american(row.get("odds", row.get("price")))
    if price is None:
        raise F5BindingError(
            F5_PRICE_UNVERIFIED,
            "price must be integer American odds (<= -100 or >= 100)")

    captured_raw = row.get("quote_captured_at")
    if captured_raw in (None, ""):
        raise F5BindingError(
            F5_QUOTE_TIMESTAMP_MISSING,
            "quote carries no quote_captured_at timestamp")
    captured = _parse_time(captured_raw, F5_QUOTE_TIMESTAMP_INVALID)
    freshness = check_quote_freshness(captured, now=now)
    if freshness["code"] == QUOTE_STALE:
        raise F5BindingError(
            F5_QUOTE_STALE,
            f"quote age {freshness['age_seconds']}s exceeds the 180s "
            "freshness bound at pricing time")
    if freshness["code"] != QUOTE_FRESH:
        raise F5BindingError(
            F5_QUOTE_TIMESTAMP_INVALID,
            f"quote freshness verdict {freshness['code']} is not "
            "admissible (future or invalid capture timestamp)")

    kickoff_raw = row.get("kickoff") or row.get("commence_time")
    if kickoff_raw in (None, ""):
        raise F5BindingError(
            F5_FIXTURE_BINDING_MISSING,
            "quote carries no kickoff/commence_time to bind the "
            "fixture against the official schedule")
    kickoff = _parse_time(kickoff_raw, F5_FIXTURE_BINDING_MISSING)

    return {
        "market": market,
        "raw_market_name": str(row.get("market") or "").strip(),
        "book": book_raw,
        "book_key": book_raw.lower(),
        "event_id": event_id,
        "game_pk": game_pk,
        "period": PERIOD_FIRST_5,
        "period_basis": period_basis,
        "side": side,
        "team_side": team_side,
        "line": line,
        "american_odds": price,
        "captured_at": captured,
        "kickoff": kickoff,
        "away": row.get("away"),
        "home": row.get("home"),
        "team": row.get("team"),
        "team_id": row.get("team_id"),
    }


def _resolve_team_entity(parsed: Mapping[str, Any],
                         fixture: Mapping[str, Any]) -> str:
    """Resolve an F5_TEAM_TOTALS selection to the fixture's team ID."""
    away_id = int(fixture["away_team_id"])
    home_id = int(fixture["home_team_id"])
    if parsed.get("team_side") == "AWAY":
        return str(away_id)
    if parsed.get("team_side") == "HOME":
        return str(home_id)
    team_id_raw = parsed.get("team_id")
    if team_id_raw not in (None, ""):
        try:
            team_id = int(str(team_id_raw).strip())
        except (TypeError, ValueError):
            team_id = None
        if team_id in (away_id, home_id):
            return str(team_id)
        raise F5BindingError(
            F5_SELECTION_UNVERIFIED,
            f"team_id {team_id_raw!r} is not one of the fixture's teams")
    team_name = _norm_name(parsed.get("team"))
    if team_name:
        if team_name == _norm_name(fixture.get("away_name")):
            return str(away_id)
        if team_name == _norm_name(fixture.get("home_name")):
            return str(home_id)
    raise F5BindingError(
        F5_SELECTION_UNVERIFIED,
        "F5 team total's team identity does not resolve against the "
        "verified fixture")


def _resolve_fixture(parsed: Mapping[str, Any],
                     fixture_resolver: Callable | None,
                     cache: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Resolve (once per gamePk) the verified fixture for a quote."""
    game_pk = parsed["game_pk"]
    if game_pk in cache:
        return cache[game_pk]
    if fixture_resolver is None:
        raise F5BindingError(
            F5_FIXTURE_BINDING_MISSING,
            "no verified fixture source is available on this path, so "
            "the gamePk binding cannot be verified")
    slate_date = parsed["kickoff"].astimezone(
        CHICAGO_TZ).date().isoformat()
    try:
        fixture = fixture_resolver(game_pk=game_pk, slate_date=slate_date)
    except Exception as exc:
        raise F5BindingError(
            F5_FIXTURE_BINDING_MISSING,
            f"fixture resolution failed for gamePk "
            f"{game_pk}: {exc}") from exc
    if not isinstance(fixture, Mapping):
        raise F5BindingError(
            F5_FIXTURE_BINDING_MISSING,
            f"gamePk {game_pk} not found on the official "
            f"schedule for {slate_date}")
    if int(fixture["game_pk"]) != game_pk:
        raise F5BindingError(
            F5_FIXTURE_BINDING_MISMATCH,
            "resolved fixture gamePk differs from the quote's gamePk")
    first_pitch = fixture["first_pitch_at"]
    if not isinstance(first_pitch, datetime):
        first_pitch = _parse_time(first_pitch, F5_FIXTURE_BINDING_MISMATCH)
    resolved = {
        "game_pk": int(fixture["game_pk"]),
        "away_team_id": int(fixture["away_team_id"]),
        "home_team_id": int(fixture["home_team_id"]),
        "away_name": fixture.get("away_name"),
        "home_name": fixture.get("home_name"),
        "first_pitch_at": first_pitch,
        "official_date": str(fixture.get("official_date") or slate_date),
    }
    cache[game_pk] = resolved
    return resolved


def _cross_check_fixture(parsed: Mapping[str, Any],
                         fixture: Mapping[str, Any]) -> None:
    """Per-row checks of the quote against its verified fixture."""
    for field, fixture_field in (("away", "away_name"), ("home", "home_name")):
        supplied = _norm_name(parsed.get(field))
        if supplied and supplied != _norm_name(fixture.get(fixture_field)):
            raise F5BindingError(
                F5_FIXTURE_BINDING_MISMATCH,
                f"quote {field} team {parsed.get(field)!r} does not "
                f"match the verified fixture ({fixture.get(fixture_field)!r})")
    first_pitch = fixture["first_pitch_at"]
    if abs((first_pitch - parsed["kickoff"]).total_seconds()) \
            > FIRST_PITCH_TOLERANCE_SECONDS:
        raise F5BindingError(
            F5_FIXTURE_BINDING_MISMATCH,
            "intake kickoff differs from the verified fixture's first "
            f"pitch by more than {FIRST_PITCH_TOLERANCE_SECONDS}s")
    if parsed["captured_at"] >= first_pitch:
        raise F5BindingError(
            F5_QUOTE_NOT_PREGAME,
            "quote was captured at or after the verified first pitch")


def _canonical_quote(parsed: Mapping[str, Any], fixture: Mapping[str, Any],
                     entity_id: str) -> dict[str, Any]:
    """Bridge-shaped canonical quote (period F5), proven admissible by
    sportsedge.quote_bridge.validate_canonical_quote itself."""
    from .quote_bridge import QuoteBridgeError, validate_canonical_quote
    raw = {
        "game_id": str(fixture["game_pk"]),
        "period": "F5",
        "market": parsed["market"],
        "entity_id": entity_id,
        "side": parsed["side"],
        "line": parsed["line"],
        "book_key": parsed["book_key"],
        "sportsbook": parsed["book"],
        "raw_market_name": parsed["raw_market_name"],
        "is_alternate": False,
        "american_odds": parsed["american_odds"],
        "retrieved_at": parsed["captured_at"],
        "ttl_seconds": 3600,
        "source_url": "CANONICAL_CARD_INTAKE",
        "selection": parsed["side"],
        "source_event_id": parsed["event_id"],
    }
    try:
        quote = validate_canonical_quote(raw)
    except QuoteBridgeError as exc:
        raise F5BindingError(
            F5_CANONICAL_QUOTE_REJECTED,
            f"bound quote rejected by the canonical quote bridge: {exc}"
        ) from exc
    quote["f5_period_basis"] = parsed["period_basis"]
    quote["f5_event_id"] = parsed["event_id"]
    return quote


def _opposite(side: str) -> str:
    return {"HOME": "AWAY", "AWAY": "HOME",
            "OVER": "UNDER", "UNDER": "OVER"}[side]


def _lines_pair(market: str, own: float, other: float) -> bool:
    if market == "F5_RUN_LINE":
        return abs(own + other) < 1e-9
    return abs(own - other) < 1e-9


def bind_f5_quotes(rows: Sequence[Mapping[str, Any]], *, now: datetime,
                   fixture_resolver: Callable | None = None) -> dict[str, Any]:
    """Bind canonical-intake F5 quote rows into admissible pairs.

    ``fixture_resolver`` is a callable (game_pk=..., slate_date=...) ->
    verified fixture mapping {game_pk, away_team_id, home_team_id,
    away_name, home_name, first_pitch_at, official_date} or None. With
    no resolver, every otherwise-valid row fails closed with
    F5_FIXTURE_BINDING_MISSING: an unverifiable binding is no binding.

    Returns {"row_results": [...], "pairs": [...]}. Row results carry
    BOUND (with pair_id) or BLOCKED (with reason_code + taxonomy
    blocker). Pairs carry the two canonical quotes, the verified
    fixture, and the market's settlement-basis record; a pair whose
    settlement basis is UNVERIFIED is returned with status
    SETTLEMENT_UNVERIFIED and its member rows BLOCKED accordingly.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("F5_BINDING_NOW_TIMEZONE_REQUIRED")
    now = now.astimezone(timezone.utc)
    row_results: list[dict[str, Any] | None] = [None] * len(rows)
    parsed_by_index: dict[int, dict[str, Any]] = {}
    fixtures_by_pk: dict[int, dict[str, Any]] = {}

    for i, row in enumerate(rows):
        if normalize_f5_market(row.get("market")) is None:
            row_results[i] = {"status": "NOT_F5", "input_index": i}
            continue
        try:
            parsed = _parse_quote(row, now=now)
            fixture = _resolve_fixture(
                parsed, fixture_resolver, fixtures_by_pk)
            _cross_check_fixture(parsed, fixture)
            if parsed["market"] == "F5_TEAM_TOTALS":
                parsed["entity_id"] = _resolve_team_entity(parsed, fixture)
            else:
                parsed["entity_id"] = str(parsed["game_pk"])
            parsed["fixture"] = fixture
            parsed_by_index[i] = parsed
        except F5BindingError as exc:
            row_results[i] = {
                "status": "BLOCKED", "input_index": i,
                "market": row.get("market"),
                "reason_code": exc.code, "detail": exc.detail,
                "blocker": BLOCKER_BY_REASON[exc.code],
                "research_only": True,
            }

    # Pairing: group admissible quotes by book/event/fixture/market/
    # entity; a group prices only as exactly one opposite pair.
    groups: dict[tuple, list[int]] = {}
    for i, parsed in parsed_by_index.items():
        key = (parsed["book_key"], parsed["event_id"], parsed["game_pk"],
               parsed["market"], parsed["entity_id"])
        groups.setdefault(key, []).append(i)

    pairs: list[dict[str, Any]] = []
    for key, indices in sorted(groups.items(), key=lambda kv: min(kv[1])):
        def _block(indices_, code, detail):
            for j in indices_:
                row_results[j] = {
                    "status": "BLOCKED", "input_index": j,
                    "market": parsed_by_index[j]["market"],
                    "reason_code": code, "detail": detail,
                    "blocker": BLOCKER_BY_REASON[code],
                    "research_only": True,
                }
        if len(indices) != 2:
            _block(indices, F5_QUOTE_UNPAIRED,
                   "a two-sided F5 market requires exactly one quote "
                   f"per side in the binding group; found {len(indices)}")
            continue
        first, second = (parsed_by_index[indices[0]],
                         parsed_by_index[indices[1]])
        if _opposite(first["side"]) != second["side"]:
            _block(indices, F5_QUOTE_UNPAIRED,
                   "binding group holds no opposite-selection "
                   "counterpart for either quote")
            continue
        if not _lines_pair(first["market"], first["line"], second["line"]):
            _block(indices, F5_QUOTE_UNPAIRED,
                   "counterpart line is not the paired line for this "
                   "market (run line negates; totals match exactly)")
            continue
        skew = abs((first["captured_at"]
                    - second["captured_at"]).total_seconds())
        if skew > MAX_PAIR_SKEW_SECONDS:
            _block(indices, F5_PAIR_SKEW_EXCEEDED,
                   f"paired captures are {skew:.0f}s apart; the bound "
                   f"is {MAX_PAIR_SKEW_SECONDS}s")
            continue
        try:
            quotes = [
                _canonical_quote(p, p["fixture"], p["entity_id"])
                for p in (first, second)]
        except F5BindingError as exc:
            _block(indices, exc.code, exc.detail)
            continue
        pair_id = f"F5PAIR-{len(pairs) + 1:03d}-{first['game_pk']}"
        basis = settlement_basis(first["market"])
        pair = {
            "pair_id": pair_id,
            "market": first["market"],
            "book_key": first["book_key"],
            "event_id": first["event_id"],
            "fixture": {
                "game_pk": first["fixture"]["game_pk"],
                "away_team_id": first["fixture"]["away_team_id"],
                "home_team_id": first["fixture"]["home_team_id"],
                "away_name": first["fixture"]["away_name"],
                "home_name": first["fixture"]["home_name"],
                "first_pitch_at": first["fixture"]["first_pitch_at"]
                    .astimezone(timezone.utc).isoformat(),
                "official_date": first["fixture"]["official_date"],
            },
            "entity_id": first["entity_id"],
            "quotes": quotes,
            "member_indices": list(indices),
            "settlement_basis": basis,
            "status": "BOUND" if basis["status"] == "VERIFIED"
                      else "SETTLEMENT_UNVERIFIED",
            "binding_version": F5_BINDING_VERSION,
        }
        pairs.append(pair)
        for j in indices:
            if basis["status"] == "VERIFIED":
                row_results[j] = {
                    "status": "BOUND", "input_index": j,
                    "market": first["market"], "pair_id": pair_id,
                    "research_only": True,
                }
            else:
                row_results[j] = {
                    "status": "BLOCKED", "input_index": j,
                    "market": first["market"], "pair_id": pair_id,
                    "reason_code": F5_SETTLEMENT_BASIS_UNVERIFIED,
                    "detail": basis["basis"],
                    "blocker": BLOCKER_BY_REASON[
                        F5_SETTLEMENT_BASIS_UNVERIFIED],
                    "research_only": True,
                }
    return {"row_results": row_results, "pairs": pairs}


# ---------------------------------------------------------------------
# Verified fixture source (official StatsAPI schedule)
# ---------------------------------------------------------------------

def make_statsapi_fixture_resolver(*, opener: Callable) -> Callable:
    """Build a fixture_resolver over the official MLB schedule.

    Uses sportsedge.mlb_source.fetch_schedule -- the same schedule read
    the snapshot lane binds against -- through the supplied opener.
    Resolution failures return None (the binder fails closed); they are
    never repaired by guessing.
    """
    from .mlb_source import fetch_schedule, parse_game_start
    cache: dict[str, list] = {}

    def resolver(*, game_pk: int, slate_date: str):
        if slate_date not in cache:
            try:
                cache[slate_date] = fetch_schedule(
                    slate_date, opener=opener)
            except Exception:
                cache[slate_date] = []
        for game in cache[slate_date]:
            if int(game.game_pk) == int(game_pk):
                return {
                    "game_pk": int(game.game_pk),
                    "away_team_id": int(game.away_id),
                    "home_team_id": int(game.home_id),
                    "away_name": game.away_name,
                    "home_name": game.home_name,
                    "first_pitch_at": parse_game_start(game.game_date),
                    "official_date": game.official_date or slate_date,
                }
        return None

    return resolver


class _BytesResponse:
    """Minimal urlopen-style response over an in-memory JSON payload."""

    def __init__(self, body: bytes):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


def opener_from_getter(getter: Callable) -> Callable:
    """Adapt a payload-style getter (url -> mapping) to a urlopen-style
    opener, the seam the StatsAPI sources consume. A getter that returns
    no payload raises OSError, which the sources convert to their own
    fail-closed errors."""

    def opener(url_or_request, timeout=15):
        url = getattr(url_or_request, "full_url", None) or str(url_or_request)
        payload = getter(url)
        if not isinstance(payload, Mapping):
            raise OSError("F5_SOURCE_GETTER_NO_PAYLOAD")
        return _BytesResponse(json.dumps(payload).encode("utf-8"))

    return opener


# ---------------------------------------------------------------------
# Feature assembly + pricer reachability (verified pregame data only)
# ---------------------------------------------------------------------

def assemble_f5_feature_rows(pair: Mapping[str, Any], *, opener: Callable,
                             retrieved_at: datetime) -> list[dict[str, Any]]:
    """Assemble the snapshot pricer's F5 feature rows for a bound pair.

    Uses MLBAllMarketHistorySource.feature_row -- the identical assembly
    run_canonical_manual_mlb performs -- which for F5 markets consumes
    only strictly-prior StatsAPI inning linescores (team histories plus
    the league prior) keyed by the verified fixture's team IDs and
    official date. No pitcher inputs, no snapshot-contract state, no
    sportsbook prices. Raises F5FeatureAssemblyError on any failure.
    """
    from .mlb_all_market_features import MLBAllMarketHistorySource
    from .mlb_generic_features import MLBGenericFeatureError
    fixture = pair["fixture"]
    market = pair["market"]
    source = MLBAllMarketHistorySource(opener=opener,
                                       retrieved_at=retrieved_at)
    target_date = date.fromisoformat(str(fixture["official_date"]))
    entity_ids = sorted({str(q["entity_id"]) for q in pair["quotes"]})
    rows = []
    for entity_id in entity_ids:
        try:
            rows.append(source.feature_row(
                game_pk=int(fixture["game_pk"]),
                market=market,
                entity_id=entity_id,
                target_date=target_date,
                away_team_id=int(fixture["away_team_id"]),
                home_team_id=int(fixture["home_team_id"]),
                team_id=int(entity_id) if market == "F5_TEAM_TOTALS"
                        else None,
            ))
        except MLBGenericFeatureError as exc:
            raise F5FeatureAssemblyError(str(exc)) from exc
    return rows


def price_bound_pair_readouts(pair: Mapping[str, Any],
                              feature_rows: Sequence[Mapping[str, Any]]
                              ) -> list[dict[str, Any]]:
    """Run the shared F5 engine session over a bound pair's quotes.

    This is a reachability proof, not a card price: it shows the bound
    canonical quotes plus assembled features are exactly what the
    snapshot pricer's engine consumes. Only provenance hashes are
    returned -- no probability leaves this function.
    """
    from .shared_f5_engine import build_shared_f5_engine_session
    fixture = pair["fixture"]
    feature_by_entity = {}
    for row in feature_rows:
        feature_by_entity[str(row.get("entity_id"))] = row
    session = build_shared_f5_engine_session()
    readouts = []
    for quote in pair["quotes"]:
        feature = feature_by_entity.get(str(quote["entity_id"]))
        if feature is None:
            raise F5FeatureAssemblyError(
                f"no assembled feature row for entity {quote['entity_id']}")
        model_input = {
            "game_id": str(fixture["game_pk"]),
            "market": pair["market"],
            "entity_id": str(quote["entity_id"]),
            "line": quote["line"],
            "side": quote["side"],
            "features": dict(feature["features"]),
            "feature_source_hash": feature.get("feature_source_hash"),
        }
        if pair["market"] == "F5_TEAM_TOTALS":
            model_input["team_side"] = (
                "AWAY" if int(quote["entity_id"])
                == int(fixture["away_team_id"]) else "HOME")
        out = session(model_input)
        readouts.append({
            "side": quote["side"],
            "engine_version": out["engine_version"],
            "distribution_sha256": out["distribution_sha256"],
            "readout_sha256": out["readout_sha256"],
            "readout_version": out["readout_version"],
        })
    return readouts


# ---------------------------------------------------------------------
# Canonical card stage (artifacts/run_it_full.py)
# ---------------------------------------------------------------------

def _blocked_card_row(row: Mapping[str, Any], *, code: str, detail: str,
                      evidence: Mapping[str, Any] | None = None
                      ) -> dict[str, Any]:
    blocker = BLOCKER_BY_REASON[code]
    out = {
        "status": "NO_MODEL_OR_MARKET",
        "reason": f"{blocker}: {code} — {detail}"[:400],
        "blocker": blocker,
        "blocker_detail": detail,
        "f5_reason": code,
        "coverage_market": normalize_f5_market(row.get("market")),
        "sport": "MLB",
        "market": row.get("market"),
        "selection": row.get("side") or row.get("selection"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }
    if evidence:
        out.update(evidence)
    return out


def _pair_evidence(pair: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pair_id": pair["pair_id"],
        "fixture": pair["fixture"],
        "settlement_basis": pair["settlement_basis"],
        "quotes": [{
            "game_id": q["game_id"], "period": q["period"],
            "market": q["market"], "entity_id": q["entity_id"],
            "side": q["side"], "line": q["line"],
            "american_odds": q["american_odds"],
            "book_key": q["book_key"],
            "retrieved_at": q["retrieved_at"]
                .astimezone(timezone.utc).isoformat(),
            "f5_event_id": q["f5_event_id"],
            "f5_period_basis": q["f5_period_basis"],
        } for q in pair["quotes"]],
        "binding_version": pair["binding_version"],
    }


def phone_f5_binding_rows(rows: Sequence[Mapping[str, Any]], *,
                          now: datetime | None = None,
                          getter: Callable | None = None,
                          fixture_resolver: Callable | None = None,
                          opener: Callable | None = None,
                          fetch_enabled: bool = True
                          ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Canonical-card stage for F5 rows: bind, assemble, gate, block.

    Every input row returns exactly one card row. All outcomes are
    BLOCKED rows today -- the gates, in order, are quote admissibility
    (this module), settlement basis, feature assembly, and the F5
    deployment gate (config/deployments.json: stage F5_STATE_CANDIDATE,
    eligible=false). A bound pair that clears every upstream gate
    blocks with F5_DEPLOYMENT_NOT_ELIGIBLE and carries the bound pair,
    feature lineage, and pricer-reachability hashes as evidence.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("F5_STAGE_NOW_TIMEZONE_REQUIRED")
    rows = list(rows)
    if opener is None and getter is not None:
        opener = opener_from_getter(getter)
    if fixture_resolver is None and fetch_enabled:
        if opener is None:
            from urllib.request import urlopen
            opener = urlopen
        fixture_resolver = make_statsapi_fixture_resolver(opener=opener)
    bound = bind_f5_quotes(rows, now=now, fixture_resolver=fixture_resolver)
    results: list[dict[str, Any] | None] = [None] * len(rows)
    for i, result in enumerate(bound["row_results"]):
        if result["status"] == "BLOCKED":
            results[i] = _blocked_card_row(
                rows[i], code=result["reason_code"],
                detail=result["detail"])
    pairs_by_member = {}
    for pair in bound["pairs"]:
        for member in pair["member_indices"]:
            pairs_by_member[member] = pair
    for i, result in enumerate(bound["row_results"]):
        if result["status"] != "BOUND":
            continue
        pair = pairs_by_member[i]
        evidence = {"f5_binding": _pair_evidence(pair)}
        if opener is None:
            results[i] = _blocked_card_row(
                rows[i], code=F5_FEATURES_UNAVAILABLE,
                detail="no StatsAPI opener is available on this path, "
                       "so strictly-prior linescore history cannot be "
                       "assembled",
                evidence=evidence)
            continue
        try:
            feature_rows = assemble_f5_feature_rows(
                pair, opener=opener, retrieved_at=now)
        except F5FeatureAssemblyError as exc:
            results[i] = _blocked_card_row(
                rows[i], code=F5_FEATURES_UNAVAILABLE,
                detail=str(exc), evidence=evidence)
            continue
        feature = feature_rows[0]
        evidence["f5_feature_lineage"] = {
            "source": feature.get("source"),
            "feature_source_hash": feature.get("feature_source_hash"),
            "feature_version": feature.get("joint_feature_version"),
            "away_history_games": feature.get("away_history_games"),
            "home_history_games": feature.get("home_history_games"),
        }
        try:
            readouts = price_bound_pair_readouts(pair, feature_rows)
        except Exception as exc:
            results[i] = _blocked_card_row(
                rows[i], code=F5_PRICER_READOUT_FAILED,
                detail=f"{type(exc).__name__}: {exc}", evidence=evidence)
            continue
        evidence["f5_pricer_reachability"] = {
            "engine": "SHARED_F5_ENGINE",
            "readouts": readouts,
        }
        from .deployments import deployment_for
        deployment = deployment_for(pair["market"])
        evidence["f5_deployment"] = {
            "stage": deployment.get("stage"),
            "eligible": deployment.get("eligible"),
            "reason": deployment.get("reason"),
        }
        if deployment.get("eligible") is not True:
            results[i] = _blocked_card_row(
                rows[i], code=F5_DEPLOYMENT_NOT_ELIGIBLE,
                detail=(f"deployment stage "
                        f"{deployment.get('stage')} is not eligible: "
                        f"{deployment.get('reason')}"),
                evidence=evidence)
        else:
            results[i] = _blocked_card_row(
                rows[i], code=F5_CANONICAL_CARD_INTEGRATION_PENDING,
                detail="quote binding, settlement basis, features and "
                       "deployment all clear, but canonical-card "
                       "pricing integration for F5 is not built; "
                       "refusing to price through an unwired route",
                evidence=evidence)
    if any(r is None for r in results):
        raise ValueError("F5_STAGE_RESULT_COUNT_MISMATCH")
    counts: dict[str, int] = {}
    for result in results:
        code = result.get("f5_reason", "BOUND")
        counts[code] = counts.get(code, 0) + 1
    receipts = [{
        "source": F5_BINDING_VERSION,
        "status": "F5_BINDING_ACTIVE_DEPLOYMENT_GATED",
        "rows": len(results),
        "bound_pairs": len(bound["pairs"]),
        "outcome_counts": counts,
    }]
    return results, receipts
