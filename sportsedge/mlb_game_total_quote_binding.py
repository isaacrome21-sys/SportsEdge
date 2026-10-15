"""Canonical-path quote binding for the MLB Total Runs 3-Way market.

DraftKings hangs a full-game "Total Runs (3-Way)" market alongside the
two-way total: three selections -- OVER, EXACTLY and UNDER -- at one
integer line (Oct 13 2026 DraftKings catalog capture, CATALOG_MLB.md
full-game list; inspected menu census key GAME_TOTAL_3_WAY, group
"game", period FULL_GAME, form BAND). The canonical card intake
(artifacts/run_it_full.py) had no binding for it, so every such row
died as an unknown market. This module is that binding layer, mirroring
sportsedge.mlb_period_quote_binding gate for gate, with the pairing
rule generalized from a pair to the market's three-selection group.

It admits a canonical-intake 3-way quote only when ALL of the
following validate, in this order, failing closed with a specific
GAME_TOTAL_3WAY_* reason code:

1. source/sportsbook named (GAME_TOTAL_3WAY_SOURCE_MISSING);
2. the book's event ID present (GAME_TOTAL_3WAY_EVENT_ID_MISSING);
3. an explicit period that is the market's own FULL_GAME, or the
   book's unambiguous full-game market identity itself (a
   present-but-different period refuses:
   GAME_TOTAL_3WAY_PERIOD_UNVERIFIED -- an F3/F5/segment quote must
   never bind as the full-game 3-way);
4. selection identity: OVER, EXACTLY or UNDER
   (GAME_TOTAL_3WAY_SELECTION_UNVERIFIED);
5. line shape: a non-negative INTEGER line
   (GAME_TOTAL_3WAY_LINE_UNVERIFIED -- the EXACTLY settlement cell
   exists only when the final total can land exactly on the line, so
   a half-line "3-way" row is a different contract and refuses);
6. a valid American price (GAME_TOTAL_3WAY_PRICE_UNVERIFIED);
7. a capture timestamp that parses and is fresh at pricing time
   through the one centralized check (sportsedge.quote_freshness,
   180s bound: GAME_TOTAL_3WAY_QUOTE_STALE);
8. fixture binding to a VERIFIED gamePk on the official StatsAPI
   schedule, with team-name and first-pitch (<=120s) cross-checks and
   a pregame capture (GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING /
   GAME_TOTAL_3WAY_FIXTURE_BINDING_MISMATCH /
   GAME_TOTAL_3WAY_QUOTE_NOT_PREGAME);
9. a complete three-selection group: same book, same event, same
   fixture, same integer rung, exactly one quote per selection
   (OVER / EXACTLY / UNDER), captured <=120s apart across the group
   (GAME_TOTAL_3WAY_QUOTE_UNPAIRED /
   GAME_TOTAL_3WAY_PAIR_SKEW_EXCEEDED). The rung is part of the
   grouping identity (owner ruling 2026-10-13), so each integer line
   is its own group and rungs never cross-bind;
10. a verified settlement basis (see SETTLEMENT_BASIS below):
    GAME_TOTAL_3WAY_SETTLEMENT_BASIS_UNVERIFIED.

Settlement basis, verified from the settlement code (not assumed):
the canonical full-game totals settlement
(mlb_catalog_prediction_settlement._game_outcome, TOTALS branch)
partitions the verified final score's total into above / exactly-on /
below the line, returning PUSH at exact equality for the two-way
contract. The DraftKings 3-way contract sells that same partition as
three selections: OVER wins strictly above the line, EXACTLY wins on
the line (the two-way push cell), UNDER wins strictly below, and no
selection pushes. The outcome is a pure function of the verified
final score, so the basis is VERIFIED on that code plus the census /
catalog record of the offering.

Feature honesty: features assemble from strictly-prior StatsAPI final
scores for both clubs plus the strictly-prior league full-game prior
(MLBGameTotalHistorySource in sportsedge.mlb_game_total_features --
actual final scores only, never a scaled period rate). No pitcher
inputs, no snapshot-contract state. Insufficient strictly-prior
history fails closed with GAME_TOTAL_3WAY_FEATURES_UNAVAILABLE.

Even a fully bound, fully featured group does not price on the card:
GAME_TOTAL_3_WAY is absent from config/deployments.json, so the
deployment registry lookup fails closed (stage UNKNOWN, "market
absent from registry", eligible=false). The card stage therefore
blocks at the deployment gate with
GAME_TOTAL_3WAY_DEPLOYMENT_NOT_ELIGIBLE (taxonomy NO_VALIDATION) and
attaches the bound group, feature lineage and pricer-reachability
hashes as evidence -- the same registry discipline the F5 and period
markets sit behind. Eligibility is a governance decision; this layer
never flips it.

Research only. No betting authority, no staking, no order placement.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .game_total_distribution import GAME_TOTAL_3WAY_MARKET, GAME_TOTAL_3WAY_MARKETS
from .mlb_f5_quote_binding import (
    make_statsapi_fixture_resolver,
    opener_from_getter,
)
from .quote_freshness import QUOTE_FRESH, QUOTE_STALE, check_quote_freshness

GAME_TOTAL_BINDING_VERSION = "MLB_GAME_TOTAL_QUOTE_BINDING_V1"
CHICAGO_TZ = ZoneInfo("America/Chicago")

# Canonical intake spellings -> canonical 3-way market. Every alias is
# itself an unambiguous full-game 3-way market identity.
GAME_TOTAL_MARKET_ALIASES = {
    "GAME_TOTAL_3_WAY": GAME_TOTAL_3WAY_MARKET,
    "GAME_TOTAL_THREE_WAY": GAME_TOTAL_3WAY_MARKET,
    "GAME_TOTAL_3WAY": GAME_TOTAL_3WAY_MARKET,
    "TOTAL_RUNS_3_WAY": GAME_TOTAL_3WAY_MARKET,
    "TOTAL_RUNS_THREE_WAY": GAME_TOTAL_3WAY_MARKET,
    "TOTAL_RUNS_3WAY": GAME_TOTAL_3WAY_MARKET,
    "FULL_GAME_TOTAL_3_WAY": GAME_TOTAL_3WAY_MARKET,
}

_FULL_GAME_PERIOD_TOKENS = frozenset({"FULL_GAME", "FG", "FULL", "GAME"})
_SIDE_CANONICAL = {"OVER": "OVER", "UNDER": "UNDER",
                   "EXACTLY": "EXACTLY", "EXACT": "EXACTLY"}
_SIDE_ORDER = {"OVER": 0, "EXACTLY": 1, "UNDER": 2}

# Same-book grouped captures must be this close (the strict paired
# evaluator's 120-second synchronization bound, applied across the
# whole three-selection group).
MAX_PAIR_SKEW_SECONDS = 120
# Fixture first pitch vs intake kickoff tolerance.
FIRST_PITCH_TOLERANCE_SECONDS = 120

# --- specific fail-closed reason codes --------------------------------
GAME_TOTAL_3WAY_MARKET_UNSUPPORTED = "GAME_TOTAL_3WAY_MARKET_UNSUPPORTED"
GAME_TOTAL_3WAY_SOURCE_MISSING = "GAME_TOTAL_3WAY_SOURCE_MISSING"
GAME_TOTAL_3WAY_EVENT_ID_MISSING = "GAME_TOTAL_3WAY_EVENT_ID_MISSING"
GAME_TOTAL_3WAY_PERIOD_UNVERIFIED = "GAME_TOTAL_3WAY_PERIOD_UNVERIFIED"
GAME_TOTAL_3WAY_SELECTION_UNVERIFIED = "GAME_TOTAL_3WAY_SELECTION_UNVERIFIED"
GAME_TOTAL_3WAY_LINE_UNVERIFIED = "GAME_TOTAL_3WAY_LINE_UNVERIFIED"
GAME_TOTAL_3WAY_PRICE_UNVERIFIED = "GAME_TOTAL_3WAY_PRICE_UNVERIFIED"
GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_MISSING = "GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_MISSING"
GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_INVALID = "GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_INVALID"
GAME_TOTAL_3WAY_QUOTE_STALE = "GAME_TOTAL_3WAY_QUOTE_STALE"
GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING = "GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING"
GAME_TOTAL_3WAY_FIXTURE_BINDING_MISMATCH = "GAME_TOTAL_3WAY_FIXTURE_BINDING_MISMATCH"
GAME_TOTAL_3WAY_QUOTE_NOT_PREGAME = "GAME_TOTAL_3WAY_QUOTE_NOT_PREGAME"
GAME_TOTAL_3WAY_QUOTE_UNPAIRED = "GAME_TOTAL_3WAY_QUOTE_UNPAIRED"
GAME_TOTAL_3WAY_PAIR_SKEW_EXCEEDED = "GAME_TOTAL_3WAY_PAIR_SKEW_EXCEEDED"
GAME_TOTAL_3WAY_CANONICAL_QUOTE_REJECTED = "GAME_TOTAL_3WAY_CANONICAL_QUOTE_REJECTED"
GAME_TOTAL_3WAY_SETTLEMENT_BASIS_UNVERIFIED = "GAME_TOTAL_3WAY_SETTLEMENT_BASIS_UNVERIFIED"
GAME_TOTAL_3WAY_FEATURES_UNAVAILABLE = "GAME_TOTAL_3WAY_FEATURES_UNAVAILABLE"
GAME_TOTAL_3WAY_PRICER_READOUT_FAILED = "GAME_TOTAL_3WAY_PRICER_READOUT_FAILED"
GAME_TOTAL_3WAY_DEPLOYMENT_NOT_ELIGIBLE = "GAME_TOTAL_3WAY_DEPLOYMENT_NOT_ELIGIBLE"
GAME_TOTAL_3WAY_CANONICAL_CARD_INTEGRATION_PENDING = "GAME_TOTAL_3WAY_CANONICAL_CARD_INTEGRATION_PENDING"
GAME_TOTAL_3WAY_BINDING_RUNTIME_UNAVAILABLE = "GAME_TOTAL_3WAY_BINDING_RUNTIME_UNAVAILABLE"

# Reason code -> canonical coverage taxonomy blocker.
BLOCKER_BY_REASON = {
    GAME_TOTAL_3WAY_MARKET_UNSUPPORTED: "NO_QUOTE",
    GAME_TOTAL_3WAY_SOURCE_MISSING: "NO_QUOTE",
    GAME_TOTAL_3WAY_EVENT_ID_MISSING: "NO_QUOTE",
    GAME_TOTAL_3WAY_PERIOD_UNVERIFIED: "NO_QUOTE",
    GAME_TOTAL_3WAY_SELECTION_UNVERIFIED: "NO_QUOTE",
    GAME_TOTAL_3WAY_LINE_UNVERIFIED: "NO_QUOTE",
    GAME_TOTAL_3WAY_PRICE_UNVERIFIED: "NO_QUOTE",
    GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_MISSING: "NO_QUOTE",
    GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_INVALID: "NO_QUOTE",
    GAME_TOTAL_3WAY_QUOTE_STALE: "NO_QUOTE",
    GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING: "NO_QUOTE",
    GAME_TOTAL_3WAY_FIXTURE_BINDING_MISMATCH: "NO_QUOTE",
    GAME_TOTAL_3WAY_QUOTE_NOT_PREGAME: "NO_QUOTE",
    GAME_TOTAL_3WAY_QUOTE_UNPAIRED: "NO_QUOTE",
    GAME_TOTAL_3WAY_PAIR_SKEW_EXCEEDED: "NO_QUOTE",
    GAME_TOTAL_3WAY_CANONICAL_QUOTE_REJECTED: "NO_QUOTE",
    GAME_TOTAL_3WAY_SETTLEMENT_BASIS_UNVERIFIED: "NO_SETTLEMENT",
    GAME_TOTAL_3WAY_FEATURES_UNAVAILABLE: "NO_DATA",
    GAME_TOTAL_3WAY_PRICER_READOUT_FAILED: "NO_ENGINE",
    GAME_TOTAL_3WAY_DEPLOYMENT_NOT_ELIGIBLE: "NO_VALIDATION",
    GAME_TOTAL_3WAY_CANONICAL_CARD_INTEGRATION_PENDING: "NO_ENGINE",
    GAME_TOTAL_3WAY_BINDING_RUNTIME_UNAVAILABLE: "NO_ENGINE",
}

_DK_GUIDE = ("https://sportsbook.draftkings.com/help/how-to-bet/"
             "baseball-betting-guide")
_DK_RULES = ("https://sportsbook.draftkings.com/help/"
             "general-betting-rules/market-rules")

SETTLEMENT_BASIS = {
    GAME_TOTAL_3WAY_MARKET: {
        "status": "VERIFIED",
        "settlement_type": "THREE_WAY",
        "basis": "VERIFIED_THREE_WAY -- combined full-game runs vs the "
                 "integer line partition into exactly three cells: OVER "
                 "wins strictly above the line, EXACTLY wins when the "
                 "final total lands exactly on the line, UNDER wins "
                 "strictly below; no selection pushes. The canonical "
                 "full-game totals settlement computes this same "
                 "partition from the verified final score (returning "
                 "PUSH at exact equality for the two-way TOTALS "
                 "contract); the DraftKings 3-way offering sells the "
                 "equality cell as the EXACTLY selection instead of "
                 "refunding it, as recorded in the Oct 13 2026 catalog "
                 "capture (\"Total Runs (3-Way) Over/Exactly/Under\") "
                 "and the inspected menu census (GAME_TOTAL_3_WAY, "
                 "FULL_GAME, BAND).",
        "verified_in": (
            "sportsedge/mlb_catalog_prediction_settlement.py:"
            "_game_outcome TOTALS branch (total = away_runs + "
            "home_runs over the verified final score; equality cell "
            "identified at abs(total - line) <= 1e-12); "
            "config/dk_inspected_menu_census_v1.json: GAME_TOTAL_3_WAY"),
        "rules_sources": (_DK_GUIDE, _DK_RULES),
    },
}


class GameTotalBindingError(ValueError):
    """One quote's admissibility failure: a specific code + detail."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class GameTotalFeatureAssemblyError(ValueError):
    pass


def normalize_game_total_market(value: Any) -> str | None:
    """Canonical 3-way market for an intake spelling, else None."""
    return GAME_TOTAL_MARKET_ALIASES.get(str(value or "").strip().upper())


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
            raise GameTotalBindingError(code, f"unparseable timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise GameTotalBindingError(code, "timestamp must be timezone-aware")
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


def _parse_quote(row: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """Validate one intake row's own admissibility (pre-fixture/grouping).

    Returns a normalized quote dict; raises GameTotalBindingError
    otherwise.
    """
    market = normalize_game_total_market(row.get("market"))
    if market is None:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_MARKET_UNSUPPORTED,
            f"not a full-game Total Runs 3-Way market: {row.get('market')!r}")
    book_raw = str(row.get("book") or row.get("sportsbook") or "").strip()
    if not book_raw:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_SOURCE_MISSING, "quote names no sportsbook/source")
    event_id = str(row.get("event_id") or row.get("source_event_id")
                   or "").strip()
    if not event_id:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_EVENT_ID_MISSING,
            "quote carries no sportsbook event ID to bind to the fixture")
    game_pk_raw = row.get("game_pk")
    if game_pk_raw in (None, ""):
        game_pk_raw = row.get("game_id")
    try:
        game_pk = int(str(game_pk_raw).strip())
    except (TypeError, ValueError):
        game_pk = None
    if game_pk is None or game_pk <= 0:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING,
            "quote carries no verified MLB gamePk identity")

    # Period: an explicit period must be the market's own FULL_GAME;
    # absent a period field, the book's full-game market identity
    # (the market spelling itself) binds.
    period_raw = row.get("period")
    if period_raw not in (None, ""):
        token = str(period_raw).strip().upper().replace(" ", "_").replace("-", "_")
        if token not in _FULL_GAME_PERIOD_TOKENS:
            raise GameTotalBindingError(
                GAME_TOTAL_3WAY_PERIOD_UNVERIFIED,
                f"period {period_raw!r} is not explicitly FULL_GAME; a "
                "segment or different-period quote must never bind as "
                "the full-game Total Runs 3-Way")
        period_basis = "EXPLICIT"
    else:
        period_basis = "MARKET_IDENTITY"

    side_raw = str(row.get("side") or row.get("selection") or "").strip().upper()
    side = _SIDE_CANONICAL.get(side_raw)
    if side is None:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_SELECTION_UNVERIFIED,
            f"{market} selection must be OVER, EXACTLY or UNDER, "
            f"got {side_raw!r}")

    line = _line(row.get("line"))
    if line is None:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_LINE_UNVERIFIED,
            f"{market} requires a numeric integer line, "
            f"got {row.get('line')!r}")
    if line < 0 or line != int(line):
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_LINE_UNVERIFIED,
            f"{market} line must be a non-negative integer, got {line}: "
            "the EXACTLY settlement cell exists only when the final "
            "total can land exactly on the line, so a non-integer "
            "\"3-way\" row is a different contract and refuses")

    price = _american(row.get("odds", row.get("price")))
    if price is None:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_PRICE_UNVERIFIED,
            "price must be integer American odds (<= -100 or >= 100)")

    captured_raw = row.get("quote_captured_at")
    if captured_raw in (None, ""):
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_MISSING,
            "quote carries no quote_captured_at timestamp")
    captured = _parse_time(captured_raw, GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_INVALID)
    freshness = check_quote_freshness(captured, now=now)
    if freshness["code"] == QUOTE_STALE:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_QUOTE_STALE,
            f"quote age {freshness['age_seconds']}s exceeds the 180s "
            "freshness bound at pricing time")
    if freshness["code"] != QUOTE_FRESH:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_QUOTE_TIMESTAMP_INVALID,
            f"quote freshness verdict {freshness['code']} is not "
            "admissible (future or invalid capture timestamp)")

    kickoff_raw = row.get("kickoff") or row.get("commence_time")
    if kickoff_raw in (None, ""):
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING,
            "quote carries no kickoff/commence_time to bind the "
            "fixture against the official schedule")
    kickoff = _parse_time(kickoff_raw, GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING)

    return {
        "market": market,
        "raw_market_name": str(row.get("market") or "").strip(),
        "book": book_raw,
        "book_key": book_raw.lower(),
        "event_id": event_id,
        "game_pk": game_pk,
        "period": "FULL_GAME",
        "period_basis": period_basis,
        "side": side,
        "line": line,
        "american_odds": price,
        "captured_at": captured,
        "kickoff": kickoff,
        "away": row.get("away"),
        "home": row.get("home"),
    }


def _resolve_fixture(parsed: Mapping[str, Any],
                     fixture_resolver: Callable | None,
                     cache: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Resolve (once per gamePk) the verified fixture for a quote."""
    game_pk = parsed["game_pk"]
    if game_pk in cache:
        return cache[game_pk]
    if fixture_resolver is None:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING,
            "no verified fixture source is available on this path, so "
            "the gamePk binding cannot be verified")
    slate_date = parsed["kickoff"].astimezone(
        CHICAGO_TZ).date().isoformat()
    try:
        fixture = fixture_resolver(game_pk=game_pk, slate_date=slate_date)
    except Exception as exc:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING,
            f"fixture resolution failed for gamePk "
            f"{game_pk}: {exc}") from exc
    if not isinstance(fixture, Mapping):
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING,
            f"gamePk {game_pk} not found on the official "
            f"schedule for {slate_date}")
    if int(fixture["game_pk"]) != game_pk:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_FIXTURE_BINDING_MISMATCH,
            "resolved fixture gamePk differs from the quote's gamePk")
    first_pitch = fixture["first_pitch_at"]
    if not isinstance(first_pitch, datetime):
        first_pitch = _parse_time(first_pitch, GAME_TOTAL_3WAY_FIXTURE_BINDING_MISMATCH)
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
            raise GameTotalBindingError(
                GAME_TOTAL_3WAY_FIXTURE_BINDING_MISMATCH,
                f"quote {field} team {parsed.get(field)!r} does not "
                f"match the verified fixture ({fixture.get(fixture_field)!r})")
    first_pitch = fixture["first_pitch_at"]
    if abs((first_pitch - parsed["kickoff"]).total_seconds()) \
            > FIRST_PITCH_TOLERANCE_SECONDS:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_FIXTURE_BINDING_MISMATCH,
            "intake kickoff differs from the verified fixture's first "
            f"pitch by more than {FIRST_PITCH_TOLERANCE_SECONDS}s")
    if parsed["captured_at"] >= first_pitch:
        raise GameTotalBindingError(
            GAME_TOTAL_3WAY_QUOTE_NOT_PREGAME,
            "quote was captured at or after the verified first pitch")


# Canonical-quote validation for 3-way quotes. The shared quote
# bridge (sportsedge.quote_bridge) validates by market name, and its
# market tables are kept in exact parity with the governed acceptance
# matrix -- which does not carry GAME_TOTAL_3_WAY yet. Admitting it
# there is registry work (acceptance matrix + catalog + surface +
# provider capability, owned by the integration lane), so this
# binding performs the bridge's own checks locally, field for field,
# and fails closed with GAME_TOTAL_3WAY_CANONICAL_QUOTE_REJECTED
# exactly where the bridge would raise. The emitted quote carries the
# bridge's output shape.
def _validate_game_total_canonical_quote(raw: Mapping[str, Any]) -> dict[str, Any]:
    def reject(detail: str) -> GameTotalBindingError:
        return GameTotalBindingError(
            GAME_TOTAL_3WAY_CANONICAL_QUOTE_REJECTED,
            f"bound quote rejected by canonical-quote validation: {detail}")

    def required_text(key: str) -> str:
        value = raw.get(key)
        if value is None:
            raise reject("QUOTE_IDENTITY_INCOMPLETE")
        out = str(value).strip()
        if not out:
            raise reject("QUOTE_IDENTITY_INCOMPLETE")
        return out

    game_id = required_text("game_id")
    market = required_text("market").upper()
    entity_id = required_text("entity_id")
    side = required_text("side").upper()
    period = required_text("period").upper()
    book_key = required_text("book_key")
    raw_market_name = required_text("raw_market_name")
    if market != GAME_TOTAL_3WAY_MARKET:
        raise reject(f"unsupported market: {market}")
    if period != "FULL_GAME":
        raise reject("QUOTE_PERIOD_MODEL_MISMATCH")
    if side not in _SIDE_ORDER:
        raise reject(f"unsupported side for {market}: {side}")
    is_alternate = raw.get("is_alternate")
    if type(is_alternate) is not bool:
        raise reject("QUOTE_IDENTITY_INCOMPLETE")
    try:
        line = float(raw.get("line"))
    except (TypeError, ValueError) as exc:
        raise reject("line must be numeric") from exc
    if not isfinite(line) or line < 0 or line != int(line):
        raise reject("line must be a non-negative integer")
    odds_raw = raw.get("american_odds")
    try:
        odds = float(odds_raw)
    except (TypeError, ValueError) as exc:
        raise reject("american_odds must be numeric") from exc
    if not isfinite(odds) or odds == 0 or -100 < odds < 100 or odds != int(odds):
        raise reject("american_odds must be integer <= -100 or >= 100")
    retrieved = raw.get("retrieved_at")
    if not (isinstance(retrieved, datetime) and retrieved.tzinfo is not None
            and retrieved.utcoffset() is not None):
        raise reject("retrieved_at must be an aware datetime")
    ttl = raw.get("ttl_seconds", 300)
    if isinstance(ttl, bool):
        raise reject("ttl_seconds invalid")
    try:
        ttl = int(ttl)
    except (TypeError, ValueError) as exc:
        raise reject("ttl_seconds invalid") from exc
    if ttl <= 0:
        raise reject("ttl_seconds must be > 0")
    out = {
        "game_id": game_id, "period": period, "market": market,
        "entity_id": entity_id, "side": side, "line": line,
        "book_key": book_key, "retrieved_at": retrieved,
        "is_alternate": is_alternate, "raw_market_name": raw_market_name,
        "american_odds": int(odds), "ttl_seconds": ttl,
    }
    for key in ("sportsbook", "source_url", "selection"):
        if raw.get(key) not in (None, ""):
            out[key] = str(raw[key])
    if raw.get("source_event_id") not in (None, ""):
        out["source_event_id"] = str(raw["source_event_id"])
    return out


def _canonical_quote(parsed: Mapping[str, Any], fixture: Mapping[str, Any],
                     entity_id: str) -> dict[str, Any]:
    """Bridge-shaped canonical quote (full-game 3-way), proven
    admissible by the local canonical-quote validation above."""
    raw = {
        "game_id": str(fixture["game_pk"]),
        "period": "FULL_GAME",
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
    quote = _validate_game_total_canonical_quote(raw)
    quote["period_period_basis"] = parsed["period_basis"]
    quote["period_event_id"] = parsed["event_id"]
    return quote


def bind_game_total_quotes(rows: Sequence[Mapping[str, Any]], *, now: datetime,
                           fixture_resolver: Callable | None = None) -> dict[str, Any]:
    """Bind canonical-intake Total Runs 3-Way rows into admissible
    three-selection groups.

    ``fixture_resolver`` is a callable (game_pk=..., slate_date=...) ->
    verified fixture mapping or None (the same seam the F5/period
    bindings use). With no resolver, every otherwise-valid row fails
    closed with GAME_TOTAL_3WAY_FIXTURE_BINDING_MISSING.

    Returns {"row_results": [...], "groups": [...]}. Row results carry
    BOUND (with group_id) or BLOCKED (with reason_code + taxonomy
    blocker). Groups carry the three canonical quotes (ordered OVER,
    EXACTLY, UNDER), the verified fixture, and the market's
    settlement-basis record.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("GAME_TOTAL_BINDING_NOW_TIMEZONE_REQUIRED")
    now = now.astimezone(timezone.utc)
    row_results: list[dict[str, Any] | None] = [None] * len(rows)
    parsed_by_index: dict[int, dict[str, Any]] = {}
    fixtures_by_pk: dict[int, dict[str, Any]] = {}

    for i, row in enumerate(rows):
        if normalize_game_total_market(row.get("market")) is None:
            row_results[i] = {"status": "NOT_GAME_TOTAL_3WAY", "input_index": i}
            continue
        try:
            parsed = _parse_quote(row, now=now)
            fixture = _resolve_fixture(
                parsed, fixture_resolver, fixtures_by_pk)
            _cross_check_fixture(parsed, fixture)
            parsed["entity_id"] = str(parsed["game_pk"])
            parsed["fixture"] = fixture
            parsed_by_index[i] = parsed
        except GameTotalBindingError as exc:
            row_results[i] = {
                "status": "BLOCKED", "input_index": i,
                "market": row.get("market"),
                "reason_code": exc.code, "detail": exc.detail,
                "blocker": BLOCKER_BY_REASON[exc.code],
                "research_only": True,
            }

    # Grouping: admissible quotes group by book/event/fixture/market/
    # entity/rung -- the LINE is part of the grouping identity (owner
    # ruling 2026-10-13), so each integer rung is its own group; a
    # group binds only as exactly one quote per selection.
    groups_by_key: dict[tuple, list[int]] = {}
    for i, parsed in parsed_by_index.items():
        key = (parsed["book_key"], parsed["event_id"], parsed["game_pk"],
               parsed["market"], parsed["entity_id"],
               round(float(parsed["line"]), 6) + 0.0)
        groups_by_key.setdefault(key, []).append(i)

    groups: list[dict[str, Any]] = []
    for key, indices in sorted(groups_by_key.items(), key=lambda kv: min(kv[1])):
        def _block(indices_, code, detail):
            for j in indices_:
                row_results[j] = {
                    "status": "BLOCKED", "input_index": j,
                    "market": parsed_by_index[j]["market"],
                    "reason_code": code, "detail": detail,
                    "blocker": BLOCKER_BY_REASON[code],
                    "research_only": True,
                }
        members = [parsed_by_index[j] for j in indices]
        sides = sorted(p["side"] for p in members)
        if len(indices) != 3 or sides != ["EXACTLY", "OVER", "UNDER"]:
            _block(indices, GAME_TOTAL_3WAY_QUOTE_UNPAIRED,
                   "a three-way market binds only as exactly one quote "
                   "per selection (OVER / EXACTLY / UNDER) in the "
                   f"binding group; found {len(indices)} quote(s) with "
                   f"selections {sides}")
            continue
        captured = [p["captured_at"] for p in members]
        skew = (max(captured) - min(captured)).total_seconds()
        if skew > MAX_PAIR_SKEW_SECONDS:
            _block(indices, GAME_TOTAL_3WAY_PAIR_SKEW_EXCEEDED,
                   f"grouped captures span {skew:.0f}s; the bound is "
                   f"{MAX_PAIR_SKEW_SECONDS}s")
            continue
        ordered = sorted(
            ((j, parsed_by_index[j]) for j in indices),
            key=lambda jp: _SIDE_ORDER[jp[1]["side"]])
        indices = [j for j, _ in ordered]
        members = [p for _, p in ordered]
        try:
            quotes = [
                _canonical_quote(p, p["fixture"], p["entity_id"])
                for p in members]
        except GameTotalBindingError as exc:
            _block(indices, exc.code, exc.detail)
            continue
        group_id = f"GT3GROUP-{len(groups) + 1:03d}-{members[0]['game_pk']}"
        basis = settlement_basis(members[0]["market"])
        fixture = members[0]["fixture"]
        group = {
            "group_id": group_id,
            "market": members[0]["market"],
            "book_key": members[0]["book_key"],
            "event_id": members[0]["event_id"],
            "fixture": {
                "game_pk": fixture["game_pk"],
                "away_team_id": fixture["away_team_id"],
                "home_team_id": fixture["home_team_id"],
                "away_name": fixture["away_name"],
                "home_name": fixture["home_name"],
                "first_pitch_at": fixture["first_pitch_at"]
                    .astimezone(timezone.utc).isoformat(),
                "official_date": fixture["official_date"],
            },
            "entity_id": members[0]["entity_id"],
            "rung_line": float(members[0]["line"]),
            "quotes": quotes,
            "member_indices": list(indices),
            "settlement_basis": basis,
            "status": "BOUND" if basis["status"] == "VERIFIED"
                      else "SETTLEMENT_UNVERIFIED",
            "binding_version": GAME_TOTAL_BINDING_VERSION,
        }
        groups.append(group)
        for j in indices:
            if basis["status"] == "VERIFIED":
                row_results[j] = {
                    "status": "BOUND", "input_index": j,
                    "market": members[0]["market"], "group_id": group_id,
                    "research_only": True,
                }
            else:
                row_results[j] = {
                    "status": "BLOCKED", "input_index": j,
                    "market": members[0]["market"], "group_id": group_id,
                    "reason_code": GAME_TOTAL_3WAY_SETTLEMENT_BASIS_UNVERIFIED,
                    "detail": basis["basis"],
                    "blocker": BLOCKER_BY_REASON[
                        GAME_TOTAL_3WAY_SETTLEMENT_BASIS_UNVERIFIED],
                    "research_only": True,
                }
    return {"row_results": row_results, "groups": groups}


# ---------------------------------------------------------------------
# Feature assembly + pricer reachability (verified pregame data only)
# ---------------------------------------------------------------------

def assemble_game_total_feature_rows(group: Mapping[str, Any], *,
                                     opener: Callable,
                                     retrieved_at: datetime) -> list[dict[str, Any]]:
    """Assemble the full-game feature row for a bound group.

    Uses MLBGameTotalHistorySource.game_matchup_features --
    strictly-prior StatsAPI final scores for both clubs plus the
    strictly-prior league full-game prior, keyed by the verified
    fixture's team IDs and official date. The full-game score state is
    one joint (away, home) distribution for the matchup, so one
    feature row serves the whole group (all three quotes resolve from
    the same joint state). No pitcher inputs, no sportsbook prices.
    Raises GameTotalFeatureAssemblyError on any failure.
    """
    from .mlb_f5_features import MLBF5FeatureError
    from .mlb_game_total_features import MLBGameTotalHistorySource
    fixture = group["fixture"]
    source = MLBGameTotalHistorySource(opener=opener, retrieved_at=retrieved_at)
    target_date = date.fromisoformat(str(fixture["official_date"]))
    try:
        features = source.game_matchup_features(
            away_team_id=int(fixture["away_team_id"]),
            home_team_id=int(fixture["home_team_id"]),
            target_date=target_date,
        )
    except MLBF5FeatureError as exc:
        raise GameTotalFeatureAssemblyError(str(exc)) from exc
    features["source"] = "MLB_STATSAPI_STRICT_PRIOR_FINAL_SCORES"
    features["joint_feature_version"] = features["feature_version"]
    return [features]


def price_bound_group_readouts(group: Mapping[str, Any],
                               feature_rows: Sequence[Mapping[str, Any]]
                               ) -> list[dict[str, Any]]:
    """Run the shared game-total engine session over a bound group's
    quotes.

    This is a reachability proof, not a card price: it shows the bound
    canonical quotes plus assembled features are exactly what the
    game-total engine consumes. Only provenance hashes are returned --
    no probability leaves this function.
    """
    from .shared_game_total_engine import build_shared_game_total_engine_session
    fixture = group["fixture"]
    if len(feature_rows) != 1:
        raise GameTotalFeatureAssemblyError(
            "game total feature assembly must yield exactly one matchup row")
    feature = feature_rows[0]
    session = build_shared_game_total_engine_session()
    readouts = []
    for quote in group["quotes"]:
        model_input = {
            "game_id": str(fixture["game_pk"]),
            "market": group["market"],
            "entity_id": str(quote["entity_id"]),
            "line": quote["line"],
            "side": quote["side"],
            "features": dict(feature["features"]),
            "feature_source_hash": feature.get("feature_source_hash"),
        }
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
        "game_total_reason": code,
        "coverage_market": normalize_game_total_market(row.get("market")),
        "sport": "MLB",
        "market": row.get("market"),
        "selection": row.get("side") or row.get("selection"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
    }
    if evidence:
        out.update(evidence)
    return out


def _group_evidence(group: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "group_id": group["group_id"],
        "fixture": group["fixture"],
        "settlement_basis": group["settlement_basis"],
        "quotes": [{
            "game_id": q["game_id"], "period": q["period"],
            "market": q["market"], "entity_id": q["entity_id"],
            "side": q["side"], "line": q["line"],
            "american_odds": q["american_odds"],
            "book_key": q["book_key"],
            "retrieved_at": q["retrieved_at"]
                .astimezone(timezone.utc).isoformat(),
            "period_event_id": q["period_event_id"],
            "period_period_basis": q["period_period_basis"],
        } for q in group["quotes"]],
        "binding_version": group["binding_version"],
    }


def phone_game_total_binding_rows(rows: Sequence[Mapping[str, Any]], *,
                                  now: datetime | None = None,
                                  getter: Callable | None = None,
                                  fixture_resolver: Callable | None = None,
                                  opener: Callable | None = None,
                                  fetch_enabled: bool = True
                                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Canonical-card stage for Total Runs 3-Way rows: bind, assemble,
    gate, block.

    Every input row returns exactly one card row. All outcomes are
    BLOCKED rows today -- the gates, in order, are quote admissibility
    (this module), settlement basis, feature assembly, and the
    deployment gate (GAME_TOTAL_3_WAY is absent from
    config/deployments.json, so the registry lookup fails closed with
    stage UNKNOWN / "market absent from registry"). A bound group that
    clears every upstream gate blocks with
    GAME_TOTAL_3WAY_DEPLOYMENT_NOT_ELIGIBLE and carries the bound
    group, feature lineage, and pricer-reachability hashes as
    evidence.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("GAME_TOTAL_STAGE_NOW_TIMEZONE_REQUIRED")
    rows = list(rows)
    if opener is None and getter is not None:
        opener = opener_from_getter(getter)
    if fixture_resolver is None and fetch_enabled:
        if opener is None:
            from urllib.request import urlopen
            opener = urlopen
        fixture_resolver = make_statsapi_fixture_resolver(opener=opener)
    bound = bind_game_total_quotes(rows, now=now, fixture_resolver=fixture_resolver)
    results: list[dict[str, Any] | None] = [None] * len(rows)
    for i, result in enumerate(bound["row_results"]):
        if result["status"] == "BLOCKED":
            results[i] = _blocked_card_row(
                rows[i], code=result["reason_code"],
                detail=result["detail"])
    groups_by_member = {}
    for group in bound["groups"]:
        for member in group["member_indices"]:
            groups_by_member[member] = group
    for i, result in enumerate(bound["row_results"]):
        if result["status"] != "BOUND":
            continue
        group = groups_by_member[i]
        evidence = {"game_total_binding": _group_evidence(group)}
        if opener is None:
            results[i] = _blocked_card_row(
                rows[i], code=GAME_TOTAL_3WAY_FEATURES_UNAVAILABLE,
                detail="no StatsAPI opener is available on this path, "
                       "so strictly-prior final-score history cannot "
                       "be assembled",
                evidence=evidence)
            continue
        try:
            feature_rows = assemble_game_total_feature_rows(
                group, opener=opener, retrieved_at=now)
        except GameTotalFeatureAssemblyError as exc:
            results[i] = _blocked_card_row(
                rows[i], code=GAME_TOTAL_3WAY_FEATURES_UNAVAILABLE,
                detail=str(exc), evidence=evidence)
            continue
        feature = feature_rows[0]
        evidence["game_total_feature_lineage"] = {
            "source": feature.get("source"),
            "feature_source_hash": feature.get("feature_source_hash"),
            "feature_version": feature.get("joint_feature_version"),
            "away_history_games": feature.get("away_history_games"),
            "home_history_games": feature.get("home_history_games"),
        }
        try:
            readouts = price_bound_group_readouts(group, feature_rows)
        except Exception as exc:
            results[i] = _blocked_card_row(
                rows[i], code=GAME_TOTAL_3WAY_PRICER_READOUT_FAILED,
                detail=f"{type(exc).__name__}: {exc}", evidence=evidence)
            continue
        evidence["game_total_pricer_reachability"] = {
            "engine": "SHARED_GAME_TOTAL_ENGINE",
            "readouts": readouts,
        }
        from .deployments import deployment_for
        deployment = deployment_for(group["market"])
        evidence["game_total_deployment"] = {
            "stage": deployment.get("stage"),
            "eligible": deployment.get("eligible"),
            "reason": deployment.get("reason"),
        }
        if deployment.get("eligible") is not True:
            results[i] = _blocked_card_row(
                rows[i], code=GAME_TOTAL_3WAY_DEPLOYMENT_NOT_ELIGIBLE,
                detail=(f"deployment stage "
                        f"{deployment.get('stage')} is not eligible: "
                        f"{deployment.get('reason')}"),
                evidence=evidence)
        else:
            results[i] = _blocked_card_row(
                rows[i], code=GAME_TOTAL_3WAY_CANONICAL_CARD_INTEGRATION_PENDING,
                detail="quote binding, settlement basis, features and "
                       "deployment all clear, but canonical-card "
                       "pricing integration for the Total Runs 3-Way "
                       "market is not built; refusing to price through "
                       "an unwired route",
                evidence=evidence)
    if any(r is None for r in results):
        raise ValueError("GAME_TOTAL_STAGE_RESULT_COUNT_MISMATCH")
    counts: dict[str, int] = {}
    for result in results:
        code = result.get("game_total_reason", "BOUND")
        counts[code] = counts.get(code, 0) + 1
    receipts = [{
        "source": GAME_TOTAL_BINDING_VERSION,
        "status": "GAME_TOTAL_BINDING_ACTIVE_DEPLOYMENT_GATED",
        "rows": len(results),
        "bound_groups": len(bound["groups"]),
        "outcome_counts": counts,
    }]
    return results, receipts
