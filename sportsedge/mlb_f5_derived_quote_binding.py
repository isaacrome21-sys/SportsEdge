"""Canonical-path quote binding for the derived F5 markets.

The verified DraftKings first-five set (Oct 13 2026 catalog capture,
CATALOG_MLB.md) includes three families the canonical F5 binding does
not carry: the Both-Teams-to-Score X+ ladder (1+..7+), Winning
Margin, and Correct Score. Their read-outs derive from the same
shared F5 joint score state as the four canonical F5 markets
(sportsedge.f5_derived_readouts); this module is their binding
layer, mirroring sportsedge.mlb_f5_quote_binding /
mlb_period_quote_binding gate for gate, with grouping rules matched
to each market's form:

* F5_BOTH_TEAMS_TO_SCORE (M14): a two-sided YES/NO market per ladder
  rung -- binds as a pair at one integer rung (the rung is part of
  the pairing identity, owner ruling 2026-10-13);
* F5_WINNING_MARGIN (M15): a single-sided multi-outcome market --
  binds only as a complete selection group whose quoted bands
  partition the signed-margin space (verified mechanically by the
  shared grammar, never assumed);
* F5_CORRECT_SCORE (M15): a single-sided multi-outcome market --
  binds only as a complete selection group carrying the book's
  ANY_OTHER catch-all alongside distinct exact-score cells (without
  the catch-all the quoted cells cannot partition the score space,
  and the group refuses by name).

A quote is admitted only when ALL of the following validate, in
this order, failing closed with a specific F5_DERIVED_* reason code:
source/sportsbook named; the book's event ID present; an explicit
period that is FIRST_5 or the book's unambiguous F5 market identity
(a full-game or segment quote refuses:
F5_DERIVED_PERIOD_UNVERIFIED); selection identity per market via
the shared grammars (F5_DERIVED_SELECTION_UNVERIFIED); line shape
per market (BTTS rung an integer in the catalog ladder 1..7;
margin/correct-score rows carry no line:
F5_DERIVED_LINE_UNVERIFIED); a valid American price; a fresh capture
timestamp through the centralized check (180s bound); fixture
binding to a VERIFIED gamePk with team-name / first-pitch (<=120s)
cross-checks and a pregame capture; the market's grouping rule
above, with the whole group's captures spanning <=120s
(F5_DERIVED_QUOTE_UNPAIRED / F5_DERIVED_SELECTION_SET_INCOMPLETE /
F5_DERIVED_PAIR_SKEW_EXCEEDED); and a verified settlement basis
(SETTLEMENT_BASIS below): F5_DERIVED_SETTLEMENT_BASIS_UNVERIFIED.

Settlement basis, verified from the settlement code (not assumed):
all three families settle from facts["f5"] in
mlb_additional_pit_joiner._derive_outcome via _f5_btts_outcome /
_f5_winning_margin_outcome / _f5_correct_score_outcome, using the
same selection grammars as the read-out layer. The ANY_OTHER
catch-all itself settles fail-closed in the joiner
(F5_CORRECT_SCORE_ANY_OTHER_REQUIRES_SELECTION_SET -- a single
settlement row cannot carry the set it is the complement of); its
binding basis is the partition semantics themselves: the catch-all
is the complement of the group's quoted cells over the verified
final F5 score.

Feature honesty: features assemble from strictly-prior StatsAPI
inning linescores through MLBF5HistorySource.matchup_features --
the identical assembly the canonical F5 path consumes -- plus the
strictly-prior league F5 prior. No pitcher inputs, no
snapshot-contract state. Insufficient history fails closed with
F5_DERIVED_FEATURES_UNAVAILABLE.

Even a fully bound, fully featured group does not price on the
card: none of the three markets is in config/deployments.json, so
the deployment registry lookup fails closed (stage UNKNOWN,
"market absent from registry", eligible=false) and the card stage
blocks at the deployment gate with
F5_DERIVED_DEPLOYMENT_NOT_ELIGIBLE (taxonomy NO_VALIDATION),
attaching the bound group, feature lineage and pricer-reachability
hashes as evidence -- the same registry discipline the canonical F5
markets sit behind. Eligibility is a governance decision; this
layer never flips it.

Research only. No betting authority, no staking, no order placement.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .f5_derived_readouts import (
    ANY_OTHER,
    F5_BTTS_MARKET,
    F5_CORRECT_SCORE_MARKET,
    F5_DERIVED_MARKETS,
    F5_WINNING_MARGIN_MARKET,
    F5DerivedReadoutError,
    correct_score_selection,
    margin_band_selection,
    margin_bands_partition,
    parse_btts_rung,
    parse_correct_score_selection,
    parse_margin_band,
)
from .mlb_f5_quote_binding import (
    make_statsapi_fixture_resolver,
    opener_from_getter,
)
from .quote_freshness import QUOTE_FRESH, QUOTE_STALE, check_quote_freshness

F5_DERIVED_BINDING_VERSION = "MLB_F5_DERIVED_QUOTE_BINDING_V1"
CHICAGO_TZ = ZoneInfo("America/Chicago")

# Canonical intake spellings -> canonical derived F5 market. Every
# alias is itself an unambiguous first-five market identity.
F5_DERIVED_MARKET_ALIASES = {
    "F5_BOTH_TEAMS_TO_SCORE": F5_BTTS_MARKET,
    "F5_BTTS": F5_BTTS_MARKET,
    "F5_BOTH_TEAMS_TO_SCORE_RUNS": F5_BTTS_MARKET,
    "FIRST_FIVE_BOTH_TEAMS_TO_SCORE": F5_BTTS_MARKET,
    "F5_WINNING_MARGIN": F5_WINNING_MARGIN_MARKET,
    "FIRST_FIVE_WINNING_MARGIN": F5_WINNING_MARGIN_MARKET,
    "F5_CORRECT_SCORE": F5_CORRECT_SCORE_MARKET,
    "FIRST_FIVE_CORRECT_SCORE": F5_CORRECT_SCORE_MARKET,
}

_F5_PERIOD_TOKENS = frozenset({
    "F5", "5", "FIRST_5", "FIRST_FIVE", "FIRST_5_INNINGS",
    "FIRST_FIVE_INNINGS"})

# Same-book grouped captures must span no more than this (the strict
# paired evaluator's 120-second synchronization bound, applied
# across the whole group).
MAX_PAIR_SKEW_SECONDS = 120
# Fixture first pitch vs intake kickoff tolerance.
FIRST_PITCH_TOLERANCE_SECONDS = 120

# --- specific fail-closed reason codes --------------------------------
F5_DERIVED_MARKET_UNSUPPORTED = "F5_DERIVED_MARKET_UNSUPPORTED"
F5_DERIVED_SOURCE_MISSING = "F5_DERIVED_SOURCE_MISSING"
F5_DERIVED_EVENT_ID_MISSING = "F5_DERIVED_EVENT_ID_MISSING"
F5_DERIVED_PERIOD_UNVERIFIED = "F5_DERIVED_PERIOD_UNVERIFIED"
F5_DERIVED_SELECTION_UNVERIFIED = "F5_DERIVED_SELECTION_UNVERIFIED"
F5_DERIVED_LINE_UNVERIFIED = "F5_DERIVED_LINE_UNVERIFIED"
F5_DERIVED_PRICE_UNVERIFIED = "F5_DERIVED_PRICE_UNVERIFIED"
F5_DERIVED_QUOTE_TIMESTAMP_MISSING = "F5_DERIVED_QUOTE_TIMESTAMP_MISSING"
F5_DERIVED_QUOTE_TIMESTAMP_INVALID = "F5_DERIVED_QUOTE_TIMESTAMP_INVALID"
F5_DERIVED_QUOTE_STALE = "F5_DERIVED_QUOTE_STALE"
F5_DERIVED_FIXTURE_BINDING_MISSING = "F5_DERIVED_FIXTURE_BINDING_MISSING"
F5_DERIVED_FIXTURE_BINDING_MISMATCH = "F5_DERIVED_FIXTURE_BINDING_MISMATCH"
F5_DERIVED_QUOTE_NOT_PREGAME = "F5_DERIVED_QUOTE_NOT_PREGAME"
F5_DERIVED_QUOTE_UNPAIRED = "F5_DERIVED_QUOTE_UNPAIRED"
F5_DERIVED_SELECTION_SET_INCOMPLETE = "F5_DERIVED_SELECTION_SET_INCOMPLETE"
F5_DERIVED_PAIR_SKEW_EXCEEDED = "F5_DERIVED_PAIR_SKEW_EXCEEDED"
F5_DERIVED_CANONICAL_QUOTE_REJECTED = "F5_DERIVED_CANONICAL_QUOTE_REJECTED"
F5_DERIVED_SETTLEMENT_BASIS_UNVERIFIED = "F5_DERIVED_SETTLEMENT_BASIS_UNVERIFIED"
F5_DERIVED_FEATURES_UNAVAILABLE = "F5_DERIVED_FEATURES_UNAVAILABLE"
F5_DERIVED_PRICER_READOUT_FAILED = "F5_DERIVED_PRICER_READOUT_FAILED"
F5_DERIVED_DEPLOYMENT_NOT_ELIGIBLE = "F5_DERIVED_DEPLOYMENT_NOT_ELIGIBLE"
F5_DERIVED_CANONICAL_CARD_INTEGRATION_PENDING = "F5_DERIVED_CANONICAL_CARD_INTEGRATION_PENDING"
F5_DERIVED_BINDING_RUNTIME_UNAVAILABLE = "F5_DERIVED_BINDING_RUNTIME_UNAVAILABLE"

# Reason code -> canonical coverage taxonomy blocker.
BLOCKER_BY_REASON = {
    F5_DERIVED_MARKET_UNSUPPORTED: "NO_QUOTE",
    F5_DERIVED_SOURCE_MISSING: "NO_QUOTE",
    F5_DERIVED_EVENT_ID_MISSING: "NO_QUOTE",
    F5_DERIVED_PERIOD_UNVERIFIED: "NO_QUOTE",
    F5_DERIVED_SELECTION_UNVERIFIED: "NO_QUOTE",
    F5_DERIVED_LINE_UNVERIFIED: "NO_QUOTE",
    F5_DERIVED_PRICE_UNVERIFIED: "NO_QUOTE",
    F5_DERIVED_QUOTE_TIMESTAMP_MISSING: "NO_QUOTE",
    F5_DERIVED_QUOTE_TIMESTAMP_INVALID: "NO_QUOTE",
    F5_DERIVED_QUOTE_STALE: "NO_QUOTE",
    F5_DERIVED_FIXTURE_BINDING_MISSING: "NO_QUOTE",
    F5_DERIVED_FIXTURE_BINDING_MISMATCH: "NO_QUOTE",
    F5_DERIVED_QUOTE_NOT_PREGAME: "NO_QUOTE",
    F5_DERIVED_QUOTE_UNPAIRED: "NO_QUOTE",
    F5_DERIVED_SELECTION_SET_INCOMPLETE: "NO_QUOTE",
    F5_DERIVED_PAIR_SKEW_EXCEEDED: "NO_QUOTE",
    F5_DERIVED_CANONICAL_QUOTE_REJECTED: "NO_QUOTE",
    F5_DERIVED_SETTLEMENT_BASIS_UNVERIFIED: "NO_SETTLEMENT",
    F5_DERIVED_FEATURES_UNAVAILABLE: "NO_DATA",
    F5_DERIVED_PRICER_READOUT_FAILED: "NO_ENGINE",
    F5_DERIVED_DEPLOYMENT_NOT_ELIGIBLE: "NO_VALIDATION",
    F5_DERIVED_CANONICAL_CARD_INTEGRATION_PENDING: "NO_ENGINE",
    F5_DERIVED_BINDING_RUNTIME_UNAVAILABLE: "NO_ENGINE",
}

_DK_GUIDE = ("https://sportsbook.draftkings.com/help/how-to-bet/"
             "baseball-betting-guide")
_DK_RULES = ("https://sportsbook.draftkings.com/help/"
             "general-betting-rules/market-rules")

SETTLEMENT_BASIS = {
    F5_BTTS_MARKET: {
        "status": "VERIFIED",
        "settlement_type": "YES_NO_PER_RUNG",
        "basis": "VERIFIED -- both clubs' runs through 5 completed "
                 "innings vs the rung: YES wins when both score at "
                 "least the rung's runs, NO otherwise; no push is "
                 "possible. The settlement code derives the outcome "
                 "from facts['f5'] with the shared rung grammar.",
        "verified_in": (
            "sportsedge/mlb_additional_pit_joiner.py:"
            "_f5_btts_outcome via _derive_outcome over facts['f5']; "
            "catalog F5 set: Both Teams to Score X+ Runs ladder "
            "(1+..7+)"),
        "rules_sources": (_DK_GUIDE, _DK_RULES),
    },
    F5_WINNING_MARGIN_MARKET: {
        "status": "VERIFIED",
        "settlement_type": "MARGIN_BAND_PARTITION",
        "basis": "VERIFIED -- the signed F5 margin (home - away) "
                 "falls in exactly one band of the quoted partition; "
                 "that band's selection wins, all others lose; no "
                 "push is possible. The settlement code derives each "
                 "band's outcome from facts['f5'] with the shared "
                 "margin-band grammar.",
        "verified_in": (
            "sportsedge/mlb_additional_pit_joiner.py:"
            "_f5_winning_margin_outcome via _derive_outcome over "
            "facts['f5']; catalog F5 set: Winning Margin"),
        "rules_sources": (_DK_GUIDE, _DK_RULES),
    },
    F5_CORRECT_SCORE_MARKET: {
        "status": "VERIFIED",
        "settlement_type": "EXACT_SCORE_PARTITION",
        "basis": "VERIFIED -- the exact F5 score (away, home) is one "
                 "cell of the quoted partition (listed cells plus "
                 "the ANY_OTHER catch-all); that cell wins, all "
                 "others lose; no push is possible. Exact cells "
                 "settle from facts['f5'] in the settlement code; "
                 "ANY_OTHER is the partition complement of the "
                 "group's listed cells and settles fail-closed in "
                 "the joiner when presented without its set "
                 "(F5_CORRECT_SCORE_ANY_OTHER_REQUIRES_SELECTION_SET).",
        "verified_in": (
            "sportsedge/mlb_additional_pit_joiner.py:"
            "_f5_correct_score_outcome via _derive_outcome over "
            "facts['f5']; catalog F5 set: Correct Score"),
        "rules_sources": (_DK_GUIDE, _DK_RULES),
    },
}


class F5DerivedBindingError(ValueError):
    """One quote's admissibility failure: a specific code + detail."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class F5DerivedFeatureAssemblyError(ValueError):
    pass


def normalize_f5_derived_market(value: Any) -> str | None:
    """Canonical derived F5 market for an intake spelling, else None."""
    return F5_DERIVED_MARKET_ALIASES.get(str(value or "").strip().upper())


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
            raise F5DerivedBindingError(code, f"unparseable timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise F5DerivedBindingError(code, "timestamp must be timezone-aware")
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


def _parse_quote(row: Mapping[str, Any], *, now: datetime) -> dict[str, Any]:
    """Validate one intake row's own admissibility (pre-fixture/grouping).

    Returns a normalized quote dict; raises F5DerivedBindingError
    otherwise. The normalized "side" is the market's selection in
    canonical form (YES/NO for BTTS; the band / score selection
    string for the partition markets).
    """
    market = normalize_f5_derived_market(row.get("market"))
    if market is None:
        raise F5DerivedBindingError(
            F5_DERIVED_MARKET_UNSUPPORTED,
            f"not a derived F5 market: {row.get('market')!r}")
    book_raw = str(row.get("book") or row.get("sportsbook") or "").strip()
    if not book_raw:
        raise F5DerivedBindingError(
            F5_DERIVED_SOURCE_MISSING, "quote names no sportsbook/source")
    event_id = str(row.get("event_id") or row.get("source_event_id")
                   or "").strip()
    if not event_id:
        raise F5DerivedBindingError(
            F5_DERIVED_EVENT_ID_MISSING,
            "quote carries no sportsbook event ID to bind to the fixture")
    game_pk_raw = row.get("game_pk")
    if game_pk_raw in (None, ""):
        game_pk_raw = row.get("game_id")
    try:
        game_pk = int(str(game_pk_raw).strip())
    except (TypeError, ValueError):
        game_pk = None
    if game_pk is None or game_pk <= 0:
        raise F5DerivedBindingError(
            F5_DERIVED_FIXTURE_BINDING_MISSING,
            "quote carries no verified MLB gamePk identity")

    # Period: an explicit period must be the market's own FIRST_5;
    # absent a period field, the book's F5 market identity binds. A
    # full-game period token refuses (deliberately stricter than the
    # quote bridge, exactly as in the canonical F5 binding).
    period_raw = row.get("period")
    if period_raw not in (None, ""):
        token = str(period_raw).strip().upper().replace(" ", "_").replace("-", "_")
        if token not in _F5_PERIOD_TOKENS:
            raise F5DerivedBindingError(
                F5_DERIVED_PERIOD_UNVERIFIED,
                f"period {period_raw!r} is not explicitly FIRST_5; a "
                "full-game or different-period quote must never bind "
                "as a derived F5 market")
        period_basis = "EXPLICIT"
    else:
        period_basis = "MARKET_IDENTITY"

    side_raw = str(row.get("side") or row.get("selection") or "").strip().upper()
    line_raw = row.get("line")
    if market == F5_BTTS_MARKET:
        if side_raw not in {"YES", "NO"}:
            raise F5DerivedBindingError(
                F5_DERIVED_SELECTION_UNVERIFIED,
                f"{market} selection must be YES or NO, got {side_raw!r}")
        side = side_raw
        try:
            rung = parse_btts_rung(line_raw)
        except F5DerivedReadoutError as exc:
            raise F5DerivedBindingError(
                F5_DERIVED_LINE_UNVERIFIED, str(exc)) from exc
        line: float | None = float(rung)
        selection_key = f"RUNG_{rung}_{side}"
    elif market == F5_WINNING_MARGIN_MARKET:
        try:
            band = parse_margin_band(side_raw)
        except F5DerivedReadoutError as exc:
            raise F5DerivedBindingError(
                F5_DERIVED_SELECTION_UNVERIFIED, str(exc)) from exc
        side = margin_band_selection(band)
        if line_raw not in (None, ""):
            raise F5DerivedBindingError(
                F5_DERIVED_LINE_UNVERIFIED,
                f"{market} is a band market and carries no line, "
                f"got {line_raw!r}")
        line = None
        selection_key = side
    else:  # F5_CORRECT_SCORE_MARKET
        try:
            parsed = parse_correct_score_selection(side_raw)
        except F5DerivedReadoutError as exc:
            raise F5DerivedBindingError(
                F5_DERIVED_SELECTION_UNVERIFIED, str(exc)) from exc
        side = correct_score_selection(parsed)
        if line_raw not in (None, ""):
            raise F5DerivedBindingError(
                F5_DERIVED_LINE_UNVERIFIED,
                f"{market} is an exact-score market and carries no "
                f"line, got {line_raw!r}")
        line = None
        selection_key = side

    price = _american(row.get("odds", row.get("price")))
    if price is None:
        raise F5DerivedBindingError(
            F5_DERIVED_PRICE_UNVERIFIED,
            "price must be integer American odds (<= -100 or >= 100)")

    captured_raw = row.get("quote_captured_at")
    if captured_raw in (None, ""):
        raise F5DerivedBindingError(
            F5_DERIVED_QUOTE_TIMESTAMP_MISSING,
            "quote carries no quote_captured_at timestamp")
    captured = _parse_time(captured_raw, F5_DERIVED_QUOTE_TIMESTAMP_INVALID)
    freshness = check_quote_freshness(captured, now=now)
    if freshness["code"] == QUOTE_STALE:
        raise F5DerivedBindingError(
            F5_DERIVED_QUOTE_STALE,
            f"quote age {freshness['age_seconds']}s exceeds the 180s "
            "freshness bound at pricing time")
    if freshness["code"] != QUOTE_FRESH:
        raise F5DerivedBindingError(
            F5_DERIVED_QUOTE_TIMESTAMP_INVALID,
            f"quote freshness verdict {freshness['code']} is not "
            "admissible (future or invalid capture timestamp)")

    kickoff_raw = row.get("kickoff") or row.get("commence_time")
    if kickoff_raw in (None, ""):
        raise F5DerivedBindingError(
            F5_DERIVED_FIXTURE_BINDING_MISSING,
            "quote carries no kickoff/commence_time to bind the "
            "fixture against the official schedule")
    kickoff = _parse_time(kickoff_raw, F5_DERIVED_FIXTURE_BINDING_MISSING)

    return {
        "market": market,
        "raw_market_name": str(row.get("market") or "").strip(),
        "book": book_raw,
        "book_key": book_raw.lower(),
        "event_id": event_id,
        "game_pk": game_pk,
        "period": "FIRST_5",
        "period_basis": period_basis,
        "side": side,
        "selection_key": selection_key,
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
        raise F5DerivedBindingError(
            F5_DERIVED_FIXTURE_BINDING_MISSING,
            "no verified fixture source is available on this path, so "
            "the gamePk binding cannot be verified")
    slate_date = parsed["kickoff"].astimezone(
        CHICAGO_TZ).date().isoformat()
    try:
        fixture = fixture_resolver(game_pk=game_pk, slate_date=slate_date)
    except Exception as exc:
        raise F5DerivedBindingError(
            F5_DERIVED_FIXTURE_BINDING_MISSING,
            f"fixture resolution failed for gamePk "
            f"{game_pk}: {exc}") from exc
    if not isinstance(fixture, Mapping):
        raise F5DerivedBindingError(
            F5_DERIVED_FIXTURE_BINDING_MISSING,
            f"gamePk {game_pk} not found on the official "
            f"schedule for {slate_date}")
    if int(fixture["game_pk"]) != game_pk:
        raise F5DerivedBindingError(
            F5_DERIVED_FIXTURE_BINDING_MISMATCH,
            "resolved fixture gamePk differs from the quote's gamePk")
    first_pitch = fixture["first_pitch_at"]
    if not isinstance(first_pitch, datetime):
        first_pitch = _parse_time(first_pitch, F5_DERIVED_FIXTURE_BINDING_MISMATCH)
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
            raise F5DerivedBindingError(
                F5_DERIVED_FIXTURE_BINDING_MISMATCH,
                f"quote {field} team {parsed.get(field)!r} does not "
                f"match the verified fixture ({fixture.get(fixture_field)!r})")
    first_pitch = fixture["first_pitch_at"]
    if abs((first_pitch - parsed["kickoff"]).total_seconds()) \
            > FIRST_PITCH_TOLERANCE_SECONDS:
        raise F5DerivedBindingError(
            F5_DERIVED_FIXTURE_BINDING_MISMATCH,
            "intake kickoff differs from the verified fixture's first "
            f"pitch by more than {FIRST_PITCH_TOLERANCE_SECONDS}s")
    if parsed["captured_at"] >= first_pitch:
        raise F5DerivedBindingError(
            F5_DERIVED_QUOTE_NOT_PREGAME,
            "quote was captured at or after the verified first pitch")


# Canonical-quote validation for derived F5 quotes. The shared quote
# bridge (sportsedge.quote_bridge) validates by market name, and its
# market tables are kept in exact parity with the governed acceptance
# matrix -- which does not carry the derived F5 markets yet.
# Admitting them there is registry work (owned by the integration
# lane), so this binding performs the bridge's own checks locally,
# field for field, and fails closed with
# F5_DERIVED_CANONICAL_QUOTE_REJECTED exactly where the bridge would
# raise. The emitted quote carries the bridge's output shape; the
# partition markets carry line 0.0 as the no-line placeholder, with
# the selection string in the side field.
def _validate_f5_derived_canonical_quote(raw: Mapping[str, Any]) -> dict[str, Any]:
    def reject(detail: str) -> F5DerivedBindingError:
        return F5DerivedBindingError(
            F5_DERIVED_CANONICAL_QUOTE_REJECTED,
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
    if market not in F5_DERIVED_MARKETS:
        raise reject(f"unsupported market: {market}")
    if period != "FIRST_5":
        raise reject("QUOTE_PERIOD_MODEL_MISMATCH")
    is_alternate = raw.get("is_alternate")
    if type(is_alternate) is not bool:
        raise reject("QUOTE_IDENTITY_INCOMPLETE")
    try:
        line = float(raw.get("line"))
    except (TypeError, ValueError) as exc:
        raise reject("line must be numeric") from exc
    if not isfinite(line):
        raise reject("line must be finite")
    if market == F5_BTTS_MARKET:
        if side not in {"YES", "NO"}:
            raise reject(f"unsupported side for {market}: {side}")
        try:
            parse_btts_rung(line)
        except F5DerivedReadoutError as exc:
            raise reject(str(exc)) from exc
    elif market == F5_WINNING_MARGIN_MARKET:
        try:
            canonical = margin_band_selection(parse_margin_band(side))
        except F5DerivedReadoutError as exc:
            raise reject(str(exc)) from exc
        if canonical != side:
            raise reject(f"non-canonical margin selection: {side}")
    else:
        try:
            canonical = correct_score_selection(
                parse_correct_score_selection(side))
        except F5DerivedReadoutError as exc:
            raise reject(str(exc)) from exc
        if canonical != side:
            raise reject(f"non-canonical correct-score selection: {side}")
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
    """Bridge-shaped canonical quote (derived F5), proven admissible
    by the local canonical-quote validation above."""
    raw = {
        "game_id": str(fixture["game_pk"]),
        "period": "FIRST_5",
        "market": parsed["market"],
        "entity_id": entity_id,
        "side": parsed["side"],
        "line": parsed["line"] if parsed["line"] is not None else 0.0,
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
    quote = _validate_f5_derived_canonical_quote(raw)
    quote["period_period_basis"] = parsed["period_basis"]
    quote["period_event_id"] = parsed["event_id"]
    return quote


def _group_key(parsed: Mapping[str, Any]) -> tuple:
    """Grouping identity: book / event / fixture / market / entity,
    plus the rung for the BTTS ladder (the rung is part of the
    pairing identity, owner ruling 2026-10-13)."""
    key = (parsed["book_key"], parsed["event_id"], parsed["game_pk"],
           parsed["market"], parsed["entity_id"])
    if parsed["market"] == F5_BTTS_MARKET:
        key = key + (round(float(parsed["line"]), 6) + 0.0,)
    return key


def _group_completeness(market: str, members: list[dict[str, Any]]
                        ) -> tuple[str, str] | None:
    """None when the group binds, else (reason_code, detail).

    BTTS binds as exactly one YES + one NO at the rung. The partition
    markets bind only when their quoted selections form the market's
    full partition (mechanically verified); a duplicate selection is
    a pairing failure, an incomplete partition is named as such.
    """
    if market == F5_BTTS_MARKET:
        sides = sorted(p["side"] for p in members)
        if len(members) != 2 or sides != ["NO", "YES"]:
            return (F5_DERIVED_QUOTE_UNPAIRED,
                    "a two-sided BTTS rung requires exactly one YES "
                    f"and one NO quote in the binding group; found "
                    f"{len(members)} quote(s) with selections {sides}")
        return None
    selections = [p["side"] for p in members]
    if len(set(selections)) != len(selections):
        return (F5_DERIVED_QUOTE_UNPAIRED,
                "binding group carries a duplicate selection; a "
                f"partition market binds one quote per selection, "
                f"found {sorted(selections)}")
    if market == F5_WINNING_MARGIN_MARKET:
        bands = [parse_margin_band(s) for s in selections]
        if not margin_bands_partition(bands):
            return (F5_DERIVED_SELECTION_SET_INCOMPLETE,
                    "the quoted winning-margin bands do not partition "
                    f"the signed-margin space: {sorted(selections)}; a "
                    "single-sided partition market binds only as its "
                    "complete selection set")
        return None
    # F5_CORRECT_SCORE
    if ANY_OTHER not in selections:
        return (F5_DERIVED_SELECTION_SET_INCOMPLETE,
                "the quoted correct-score cells carry no ANY_OTHER "
                "catch-all, so they cannot partition the score "
                f"space: {sorted(selections)}; a single-sided "
                "partition market binds only as its complete "
                "selection set")
    return None


def bind_f5_derived_quotes(rows: Sequence[Mapping[str, Any]], *, now: datetime,
                           fixture_resolver: Callable | None = None) -> dict[str, Any]:
    """Bind canonical-intake derived-F5 rows into admissible groups.

    ``fixture_resolver`` is a callable (game_pk=..., slate_date=...)
    -> verified fixture mapping or None (the same seam the F5/period
    bindings use). With no resolver, every otherwise-valid row fails
    closed with F5_DERIVED_FIXTURE_BINDING_MISSING.

    Returns {"row_results": [...], "groups": [...]}. Row results
    carry BOUND (with group_id) or BLOCKED (with reason_code +
    taxonomy blocker). Groups carry the canonical quotes, the
    verified fixture, the group's partition (for the partition
    markets), and the market's settlement-basis record.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("F5_DERIVED_BINDING_NOW_TIMEZONE_REQUIRED")
    now = now.astimezone(timezone.utc)
    row_results: list[dict[str, Any] | None] = [None] * len(rows)
    parsed_by_index: dict[int, dict[str, Any]] = {}
    fixtures_by_pk: dict[int, dict[str, Any]] = {}

    for i, row in enumerate(rows):
        if normalize_f5_derived_market(row.get("market")) is None:
            row_results[i] = {"status": "NOT_F5_DERIVED", "input_index": i}
            continue
        try:
            parsed = _parse_quote(row, now=now)
            fixture = _resolve_fixture(
                parsed, fixture_resolver, fixtures_by_pk)
            _cross_check_fixture(parsed, fixture)
            parsed["entity_id"] = str(parsed["game_pk"])
            parsed["fixture"] = fixture
            parsed_by_index[i] = parsed
        except F5DerivedBindingError as exc:
            row_results[i] = {
                "status": "BLOCKED", "input_index": i,
                "market": row.get("market"),
                "reason_code": exc.code, "detail": exc.detail,
                "blocker": BLOCKER_BY_REASON[exc.code],
                "research_only": True,
            }

    groups_by_key: dict[tuple, list[int]] = {}
    for i, parsed in parsed_by_index.items():
        groups_by_key.setdefault(_group_key(parsed), []).append(i)

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
        market = members[0]["market"]
        failure = _group_completeness(market, members)
        if failure is not None:
            _block(indices, failure[0], failure[1])
            continue
        captured = [p["captured_at"] for p in members]
        skew = (max(captured) - min(captured)).total_seconds()
        if skew > MAX_PAIR_SKEW_SECONDS:
            _block(indices, F5_DERIVED_PAIR_SKEW_EXCEEDED,
                   f"grouped captures span {skew:.0f}s; the bound is "
                   f"{MAX_PAIR_SKEW_SECONDS}s")
            continue
        members.sort(key=lambda p: p["selection_key"])
        indices = [j for j, _ in sorted(
            ((j, parsed_by_index[j]) for j in indices),
            key=lambda jp: jp[1]["selection_key"])]
        try:
            quotes = [
                _canonical_quote(p, p["fixture"], p["entity_id"])
                for p in members]
        except F5DerivedBindingError as exc:
            _block(indices, exc.code, exc.detail)
            continue
        group_id = f"F5DGROUP-{len(groups) + 1:03d}-{members[0]['game_pk']}"
        basis = settlement_basis(market)
        fixture = members[0]["fixture"]
        group = {
            "group_id": group_id,
            "market": market,
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
            "rung_line": (float(members[0]["line"])
                          if market == F5_BTTS_MARKET else None),
            "partition": ([p["side"] for p in members]
                          if market != F5_BTTS_MARKET else None),
            "quotes": quotes,
            "member_indices": list(indices),
            "settlement_basis": basis,
            "status": "BOUND" if basis["status"] == "VERIFIED"
                      else "SETTLEMENT_UNVERIFIED",
            "binding_version": F5_DERIVED_BINDING_VERSION,
        }
        groups.append(group)
        for j in indices:
            if basis["status"] == "VERIFIED":
                row_results[j] = {
                    "status": "BOUND", "input_index": j,
                    "market": market, "group_id": group_id,
                    "research_only": True,
                }
            else:
                row_results[j] = {
                    "status": "BLOCKED", "input_index": j,
                    "market": market, "group_id": group_id,
                    "reason_code": F5_DERIVED_SETTLEMENT_BASIS_UNVERIFIED,
                    "detail": basis["basis"],
                    "blocker": BLOCKER_BY_REASON[
                        F5_DERIVED_SETTLEMENT_BASIS_UNVERIFIED],
                    "research_only": True,
                }
    return {"row_results": row_results, "groups": groups}


# ---------------------------------------------------------------------
# Feature assembly + pricer reachability (verified pregame data only)
# ---------------------------------------------------------------------

def assemble_f5_derived_feature_rows(group: Mapping[str, Any], *,
                                     opener: Callable,
                                     retrieved_at: datetime) -> list[dict[str, Any]]:
    """Assemble the F5 feature row for a bound group.

    Uses MLBF5HistorySource.matchup_features -- the identical
    strictly-prior StatsAPI inning-linescore assembly the canonical
    F5 path consumes -- keyed by the verified fixture's team IDs and
    official date. The F5 score state is one joint (away, home)
    distribution for the matchup, so one feature row serves the
    whole group. No pitcher inputs, no sportsbook prices. Raises
    F5DerivedFeatureAssemblyError on any failure.
    """
    from .mlb_f5_features import MLBF5FeatureError, MLBF5HistorySource
    fixture = group["fixture"]
    source = MLBF5HistorySource(opener=opener, retrieved_at=retrieved_at)
    target_date = date.fromisoformat(str(fixture["official_date"]))
    try:
        features = source.matchup_features(
            away_team_id=int(fixture["away_team_id"]),
            home_team_id=int(fixture["home_team_id"]),
            target_date=target_date,
        )
    except MLBF5FeatureError as exc:
        raise F5DerivedFeatureAssemblyError(str(exc)) from exc
    features["source"] = "MLB_STATSAPI_STRICT_PRIOR_F5_AND_INNING1_LINESCORE"
    features["joint_feature_version"] = features["feature_version"]
    return [features]


def price_bound_group_readouts(group: Mapping[str, Any],
                               feature_rows: Sequence[Mapping[str, Any]]
                               ) -> list[dict[str, Any]]:
    """Run the shared derived-F5 engine session over a bound group's
    quotes.

    This is a reachability proof, not a card price: it shows the
    bound canonical quotes plus assembled features are exactly what
    the derived read-out layer consumes (the partition markets pass
    the group's quoted partition as readout context). Only provenance
    hashes are returned -- no probability leaves this function.
    """
    from .shared_f5_derived_engine import build_shared_f5_derived_engine_session
    fixture = group["fixture"]
    if len(feature_rows) != 1:
        raise F5DerivedFeatureAssemblyError(
            "derived F5 feature assembly must yield exactly one matchup row")
    feature = feature_rows[0]
    session = build_shared_f5_derived_engine_session()
    readouts = []
    for quote in group["quotes"]:
        model_input = {
            "game_id": str(fixture["game_pk"]),
            "market": group["market"],
            "entity_id": str(quote["entity_id"]),
            "line": group["rung_line"] if group["market"] == F5_BTTS_MARKET
                    else None,
            "side": quote["side"],
            "features": dict(feature["features"]),
            "feature_source_hash": feature.get("feature_source_hash"),
        }
        if group["partition"] is not None:
            model_input["partition"] = list(group["partition"])
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
        "f5_derived_reason": code,
        "coverage_market": normalize_f5_derived_market(row.get("market")),
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
        "rung_line": group["rung_line"],
        "partition": group["partition"],
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


def phone_f5_derived_binding_rows(rows: Sequence[Mapping[str, Any]], *,
                                  now: datetime | None = None,
                                  getter: Callable | None = None,
                                  fixture_resolver: Callable | None = None,
                                  opener: Callable | None = None,
                                  fetch_enabled: bool = True
                                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Canonical-card stage for derived F5 rows: bind, assemble,
    gate, block.

    Every input row returns exactly one card row. All outcomes are
    BLOCKED rows today -- the gates, in order, are quote
    admissibility (this module), settlement basis, feature assembly,
    and the deployment gate (none of the three markets is in
    config/deployments.json, so the registry lookup fails closed
    with stage UNKNOWN / "market absent from registry"). A bound
    group that clears every upstream gate blocks with
    F5_DERIVED_DEPLOYMENT_NOT_ELIGIBLE and carries the bound group,
    feature lineage, and pricer-reachability hashes as evidence.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("F5_DERIVED_STAGE_NOW_TIMEZONE_REQUIRED")
    rows = list(rows)
    if opener is None and getter is not None:
        opener = opener_from_getter(getter)
    if fixture_resolver is None and fetch_enabled:
        if opener is None:
            from urllib.request import urlopen
            opener = urlopen
        fixture_resolver = make_statsapi_fixture_resolver(opener=opener)
    bound = bind_f5_derived_quotes(rows, now=now, fixture_resolver=fixture_resolver)
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
        evidence = {"f5_derived_binding": _group_evidence(group)}
        if opener is None:
            results[i] = _blocked_card_row(
                rows[i], code=F5_DERIVED_FEATURES_UNAVAILABLE,
                detail="no StatsAPI opener is available on this path, "
                       "so strictly-prior linescore history cannot be "
                       "assembled",
                evidence=evidence)
            continue
        try:
            feature_rows = assemble_f5_derived_feature_rows(
                group, opener=opener, retrieved_at=now)
        except F5DerivedFeatureAssemblyError as exc:
            results[i] = _blocked_card_row(
                rows[i], code=F5_DERIVED_FEATURES_UNAVAILABLE,
                detail=str(exc), evidence=evidence)
            continue
        feature = feature_rows[0]
        evidence["f5_derived_feature_lineage"] = {
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
                rows[i], code=F5_DERIVED_PRICER_READOUT_FAILED,
                detail=f"{type(exc).__name__}: {exc}", evidence=evidence)
            continue
        evidence["f5_derived_pricer_reachability"] = {
            "engine": "SHARED_F5_DERIVED_ENGINE",
            "readouts": readouts,
        }
        from .deployments import deployment_for
        deployment = deployment_for(group["market"])
        evidence["f5_derived_deployment"] = {
            "stage": deployment.get("stage"),
            "eligible": deployment.get("eligible"),
            "reason": deployment.get("reason"),
        }
        if deployment.get("eligible") is not True:
            results[i] = _blocked_card_row(
                rows[i], code=F5_DERIVED_DEPLOYMENT_NOT_ELIGIBLE,
                detail=(f"deployment stage "
                        f"{deployment.get('stage')} is not eligible: "
                        f"{deployment.get('reason')}"),
                evidence=evidence)
        else:
            results[i] = _blocked_card_row(
                rows[i], code=F5_DERIVED_CANONICAL_CARD_INTEGRATION_PENDING,
                detail="quote binding, settlement basis, features and "
                       "deployment all clear, but canonical-card "
                       "pricing integration for the derived F5 "
                       "markets is not built; refusing to price "
                       "through an unwired route",
                evidence=evidence)
    if any(r is None for r in results):
        raise ValueError("F5_DERIVED_STAGE_RESULT_COUNT_MISMATCH")
    counts: dict[str, int] = {}
    for result in results:
        code = result.get("f5_derived_reason", "BOUND")
        counts[code] = counts.get(code, 0) + 1
    receipts = [{
        "source": F5_DERIVED_BINDING_VERSION,
        "status": "F5_DERIVED_BINDING_ACTIVE_DEPLOYMENT_GATED",
        "rows": len(results),
        "bound_groups": len(bound["groups"]),
        "outcome_counts": counts,
    }]
    return results, receipts
