"""Canonical-path quote binding for MLB first-3 / first-7 innings markets.

DraftKings hangs full market sets for the 1st 3 innings and the 1st 7
innings alongside the full game and the first five (Oct 13 2026
DraftKings catalog capture, CATALOG_MLB.md: "Same structure exists for
1st 3 innings and 1st 7 innings (ML, team totals, run line, BTTS
ladder, winning margin; 1st-3 team totals at 0.5; 1st-7 at 2.5)").
The canonical card intake (artifacts/run_it_full.py) had no binding
for the eight period markets (F3_MONEYLINE / F3_RUN_LINE / F3_TOTALS /
F3_TEAM_TOTALS and the F7 equivalents), so every such row died as an
unknown market. This module is that binding layer, mirroring
sportsedge.mlb_f5_quote_binding gate for gate.

It admits a canonical-intake period quote only when ALL of the
following validate, in this order, failing closed with a specific
PERIOD_* reason code:

1. source/sportsbook named (PERIOD_SOURCE_MISSING);
2. the book's event ID present (PERIOD_EVENT_ID_MISSING);
3. an explicit period that is the market's own FIRST_3 / FIRST_7, or
   the book's unambiguous period market identity itself (a
   present-but-different period refuses: PERIOD_PERIOD_UNVERIFIED --
   a full-game or F5 quote must never bind as F3/F7);
4. selection identity per market (PERIOD_SELECTION_UNVERIFIED);
5. line shape per market (PERIOD_LINE_UNVERIFIED);
6. a valid American price (PERIOD_PRICE_UNVERIFIED);
7. a capture timestamp that parses and is fresh at pricing time
   through the one centralized check (sportsedge.quote_freshness,
   180s bound: PERIOD_QUOTE_STALE);
8. fixture binding to a VERIFIED gamePk on the official StatsAPI
   schedule, with team-name and first-pitch (<=120s) cross-checks and
   a pregame capture (PERIOD_FIXTURE_BINDING_MISSING /
   PERIOD_FIXTURE_BINDING_MISMATCH / PERIOD_QUOTE_NOT_PREGAME);
9. a paired counterpart: same book, same event, same fixture, same
   rung, opposite selection, line-compatible (negated for the run
   line), captured <=120s apart (PERIOD_QUOTE_UNPAIRED /
   PERIOD_PAIR_SKEW_EXCEEDED). The rung is part of the pairing
   identity (owner ruling 2026-10-13), with run-line rungs normalized
   to the AWAY side's signed line -- the #2287 pairing discipline;
10. a verified settlement basis (see SETTLEMENT_BASIS below):
    PERIOD_SETTLEMENT_BASIS_UNVERIFIED.

Settlement basis, verified from the settlement code (not assumed):
the period run line, totals and team totals settle from the score
through the period's completed innings with explicit push handling
(mlb_additional_pit_joiner._period_run_line_outcome /
_period_total_outcome / _period_team_total_outcome over
facts["f3"] / facts["f7"]). The period
moneylines verify as TWO_WAY on the same published-rules basis as
F5_MONEYLINE: DraftKings offers only the two teams for the 1st-3 and
1st-7 moneylines (no Draw selection) and publishes that a tied team
bet pushes with the stake refunded; the settlement type is declared
explicitly in sportsedge.moneyline_settlement (TWO_WAY for
F3_MONEYLINE and F7_MONEYLINE @ DraftKings) and the settlement code
settles a tied period score as PUSH through that typed model
(mlb_additional_pit_joiner._period_moneyline_outcome via
settle_moneyline). Undeclared books still fail closed.

Feature honesty: features assemble from strictly-prior StatsAPI
inning-level linescores through the period (MLBPeriodHistorySource in
sportsedge.mlb_period_features, cumulative runs through inning 3 or 7 --
never a scaled full-game rate), plus the strictly-prior league period
prior. No pitcher inputs, no snapshot-contract state. Insufficient
strictly-prior history fails closed with PERIOD_FEATURES_UNAVAILABLE.

Even a fully bound, fully featured pair does not price on the card:
the period markets are absent from config/deployments.json, so the
deployment registry lookup fails closed (stage UNKNOWN, "market
absent from registry", eligible=false). The card stage therefore
blocks at the deployment gate with PERIOD_DEPLOYMENT_NOT_ELIGIBLE
(taxonomy NO_VALIDATION) and attaches the bound pair, feature lineage
and pricer-reachability hashes as evidence -- the same registry
discipline the F5 markets sit behind. Eligibility is a governance
decision; this layer never flips it.

Research only. No betting authority, no staking, no order placement.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from math import isfinite
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .mlb_f5_quote_binding import (
    make_statsapi_fixture_resolver,
    opener_from_getter,
)
from .period_distribution import F3_MARKETS, F7_MARKETS
from .quote_freshness import QUOTE_FRESH, QUOTE_STALE, check_quote_freshness

PERIOD_BINDING_VERSION = "MLB_PERIOD_QUOTE_BINDING_V1"
CHICAGO_TZ = ZoneInfo("America/Chicago")

# Canonical intake spellings -> canonical period market. Every alias
# is itself an unambiguous period market identity.
PERIOD_MARKET_ALIASES = {
    "F3_MONEYLINE": "F3_MONEYLINE", "F3_ML": "F3_MONEYLINE",
    "FIRST_THREE_MONEYLINE": "F3_MONEYLINE",
    "FIRST_3_MONEYLINE": "F3_MONEYLINE",
    "F3_RUN_LINE": "F3_RUN_LINE", "F3_SPREAD": "F3_RUN_LINE",
    "FIRST_THREE_RUN_LINE": "F3_RUN_LINE",
    "F3_TOTALS": "F3_TOTALS", "F3_TOTAL": "F3_TOTALS",
    "FIRST_THREE_TOTAL": "F3_TOTALS", "FIRST_THREE_TOTALS": "F3_TOTALS",
    "F3_TEAM_TOTALS": "F3_TEAM_TOTALS", "F3_TEAM_TOTAL": "F3_TEAM_TOTALS",
    "FIRST_THREE_TEAM_TOTAL": "F3_TEAM_TOTALS",
    "FIRST_THREE_TEAM_TOTALS": "F3_TEAM_TOTALS",
    "F7_MONEYLINE": "F7_MONEYLINE", "F7_ML": "F7_MONEYLINE",
    "FIRST_SEVEN_MONEYLINE": "F7_MONEYLINE",
    "FIRST_7_MONEYLINE": "F7_MONEYLINE",
    "F7_RUN_LINE": "F7_RUN_LINE", "F7_SPREAD": "F7_RUN_LINE",
    "FIRST_SEVEN_RUN_LINE": "F7_RUN_LINE",
    "F7_TOTALS": "F7_TOTALS", "F7_TOTAL": "F7_TOTALS",
    "FIRST_SEVEN_TOTAL": "F7_TOTALS", "FIRST_SEVEN_TOTALS": "F7_TOTALS",
    "F7_TEAM_TOTALS": "F7_TEAM_TOTALS", "F7_TEAM_TOTAL": "F7_TEAM_TOTALS",
    "FIRST_SEVEN_TEAM_TOTAL": "F7_TEAM_TOTALS",
    "FIRST_SEVEN_TEAM_TOTALS": "F7_TEAM_TOTALS",
}

PERIOD_LABEL_BY_INNINGS = {3: "FIRST_3", 7: "FIRST_7"}
_PERIOD_TOKENS_BY_INNINGS = {
    3: frozenset({"F3", "3", "FIRST_3", "FIRST_THREE",
                  "FIRST_3_INNINGS", "FIRST_THREE_INNINGS"}),
    7: frozenset({"F7", "7", "FIRST_7", "FIRST_SEVEN",
                  "FIRST_7_INNINGS", "FIRST_SEVEN_INNINGS"}),
}

# Same-book paired captures must be this close (the strict paired
# evaluator's 120-second synchronization bound).
MAX_PAIR_SKEW_SECONDS = 120
# Fixture first pitch vs intake kickoff tolerance.
FIRST_PITCH_TOLERANCE_SECONDS = 120

# --- specific fail-closed reason codes --------------------------------
PERIOD_MARKET_UNSUPPORTED = "PERIOD_MARKET_UNSUPPORTED"
PERIOD_SOURCE_MISSING = "PERIOD_SOURCE_MISSING"
PERIOD_EVENT_ID_MISSING = "PERIOD_EVENT_ID_MISSING"
PERIOD_PERIOD_UNVERIFIED = "PERIOD_PERIOD_UNVERIFIED"
PERIOD_SELECTION_UNVERIFIED = "PERIOD_SELECTION_UNVERIFIED"
PERIOD_LINE_UNVERIFIED = "PERIOD_LINE_UNVERIFIED"
PERIOD_PRICE_UNVERIFIED = "PERIOD_PRICE_UNVERIFIED"
PERIOD_QUOTE_TIMESTAMP_MISSING = "PERIOD_QUOTE_TIMESTAMP_MISSING"
PERIOD_QUOTE_TIMESTAMP_INVALID = "PERIOD_QUOTE_TIMESTAMP_INVALID"
PERIOD_QUOTE_STALE = "PERIOD_QUOTE_STALE"
PERIOD_FIXTURE_BINDING_MISSING = "PERIOD_FIXTURE_BINDING_MISSING"
PERIOD_FIXTURE_BINDING_MISMATCH = "PERIOD_FIXTURE_BINDING_MISMATCH"
PERIOD_QUOTE_NOT_PREGAME = "PERIOD_QUOTE_NOT_PREGAME"
PERIOD_QUOTE_UNPAIRED = "PERIOD_QUOTE_UNPAIRED"
PERIOD_PAIR_SKEW_EXCEEDED = "PERIOD_PAIR_SKEW_EXCEEDED"
PERIOD_CANONICAL_QUOTE_REJECTED = "PERIOD_CANONICAL_QUOTE_REJECTED"
PERIOD_SETTLEMENT_BASIS_UNVERIFIED = "PERIOD_SETTLEMENT_BASIS_UNVERIFIED"
PERIOD_FEATURES_UNAVAILABLE = "PERIOD_FEATURES_UNAVAILABLE"
PERIOD_PRICER_READOUT_FAILED = "PERIOD_PRICER_READOUT_FAILED"
PERIOD_DEPLOYMENT_NOT_ELIGIBLE = "PERIOD_DEPLOYMENT_NOT_ELIGIBLE"
PERIOD_CANONICAL_CARD_INTEGRATION_PENDING = "PERIOD_CANONICAL_CARD_INTEGRATION_PENDING"
PERIOD_BINDING_RUNTIME_UNAVAILABLE = "PERIOD_BINDING_RUNTIME_UNAVAILABLE"

# Reason code -> canonical coverage taxonomy blocker.
BLOCKER_BY_REASON = {
    PERIOD_MARKET_UNSUPPORTED: "NO_QUOTE",
    PERIOD_SOURCE_MISSING: "NO_QUOTE",
    PERIOD_EVENT_ID_MISSING: "NO_QUOTE",
    PERIOD_PERIOD_UNVERIFIED: "NO_QUOTE",
    PERIOD_SELECTION_UNVERIFIED: "NO_QUOTE",
    PERIOD_LINE_UNVERIFIED: "NO_QUOTE",
    PERIOD_PRICE_UNVERIFIED: "NO_QUOTE",
    PERIOD_QUOTE_TIMESTAMP_MISSING: "NO_QUOTE",
    PERIOD_QUOTE_TIMESTAMP_INVALID: "NO_QUOTE",
    PERIOD_QUOTE_STALE: "NO_QUOTE",
    PERIOD_FIXTURE_BINDING_MISSING: "NO_QUOTE",
    PERIOD_FIXTURE_BINDING_MISMATCH: "NO_QUOTE",
    PERIOD_QUOTE_NOT_PREGAME: "NO_QUOTE",
    PERIOD_QUOTE_UNPAIRED: "NO_QUOTE",
    PERIOD_PAIR_SKEW_EXCEEDED: "NO_QUOTE",
    PERIOD_CANONICAL_QUOTE_REJECTED: "NO_QUOTE",
    PERIOD_SETTLEMENT_BASIS_UNVERIFIED: "NO_SETTLEMENT",
    PERIOD_FEATURES_UNAVAILABLE: "NO_DATA",
    PERIOD_PRICER_READOUT_FAILED: "NO_ENGINE",
    PERIOD_DEPLOYMENT_NOT_ELIGIBLE: "NO_VALIDATION",
    PERIOD_CANONICAL_CARD_INTEGRATION_PENDING: "NO_ENGINE",
    PERIOD_BINDING_RUNTIME_UNAVAILABLE: "NO_ENGINE",
}

_DK_GUIDE = ("https://sportsbook.draftkings.com/help/how-to-bet/"
             "baseball-betting-guide")
_DK_RULES = ("https://sportsbook.draftkings.com/help/"
             "general-betting-rules/market-rules")


def _settlement_basis() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for innings, fact_key in ((3, "f3"), (7, "f7")):
        prefix = f"F{innings}"
        out[f"{prefix}_MONEYLINE"] = {
            "status": "VERIFIED",
            "settlement_type": "TWO_WAY",
            "basis": f"VERIFIED_TWO_WAY -- leader after {innings} "
                     "completed innings wins; a tied score after the "
                     "period is a PUSH (stake returned), never a loss "
                     "and never a draw outcome. DraftKings offers only "
                     "the two teams for the period moneyline (no Draw "
                     "selection) and publishes that a tied team bet "
                     "pushes with the stake refunded; its market-rules "
                     "taxonomy classifies that as a 2-Way Moneyline "
                     "Market. The settlement code settles ties through "
                     "the explicitly declared TWO_WAY type "
                     "(sportsedge.moneyline_settlement), consistent "
                     "with the pricing readout's separate push_p tie "
                     "mass.",
            "verified_in": (
                "sportsedge/moneyline_settlement.py:"
                f"declared_moneyline_settlement_type({prefix}_MONEYLINE, "
                "DraftKings)=TWO_WAY; "
                "sportsedge/mlb_additional_pit_joiner.py:"
                "_period_moneyline_outcome via settle_moneyline"),
            "rules_sources": (_DK_GUIDE, _DK_RULES),
        }
        out[f"{prefix}_RUN_LINE"] = {
            "status": "VERIFIED",
            "basis": f"Score through {innings} completed innings; "
                     "selected team's runs plus the line vs the "
                     "opponent's runs; exact equality is a PUSH.",
            "verified_in": (
                "sportsedge/mlb_additional_pit_joiner.py:"
                "_period_run_line_outcome"),
        }
        out[f"{prefix}_TOTALS"] = {
            "status": "VERIFIED",
            "basis": f"Combined runs through {innings} completed "
                     "innings vs the line; OVER wins above, UNDER "
                     "below, exact equality is a PUSH.",
            "verified_in": (
                "sportsedge/mlb_additional_pit_joiner.py:"
                "_period_total_outcome"),
        }
        out[f"{prefix}_TEAM_TOTALS"] = {
            "status": "VERIFIED",
            "basis": f"Selected team's runs through {innings} "
                     f"completed innings (facts['{fact_key}']) vs the "
                     "line; OVER wins above, UNDER below, exact "
                     "equality is a PUSH.",
            "verified_in": (
                "sportsedge/mlb_additional_pit_joiner.py:"
                f"_period_team_total_outcome over facts['{fact_key}']"),
        }
    return out


SETTLEMENT_BASIS = _settlement_basis()


class PeriodBindingError(ValueError):
    """One quote's admissibility failure: a specific code + detail."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class PeriodFeatureAssemblyError(ValueError):
    pass


def normalize_period_market(value: Any) -> str | None:
    """Canonical period market for an intake spelling, else None."""
    return PERIOD_MARKET_ALIASES.get(str(value or "").strip().upper())


def innings_for_period_market(market: str) -> int:
    if market in F3_MARKETS:
        return 3
    if market in F7_MARKETS:
        return 7
    raise PeriodBindingError(
        PERIOD_MARKET_UNSUPPORTED, f"not a period market: {market!r}")


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
            raise PeriodBindingError(code, f"unparseable timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PeriodBindingError(code, "timestamp must be timezone-aware")
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

    Returns a normalized quote dict; raises PeriodBindingError otherwise.
    """
    market = normalize_period_market(row.get("market"))
    if market is None:
        raise PeriodBindingError(
            PERIOD_MARKET_UNSUPPORTED,
            f"not a first-3/first-7 period market: {row.get('market')!r}")
    innings = innings_for_period_market(market)
    prefix = f"F{innings}"
    book_raw = str(row.get("book") or row.get("sportsbook") or "").strip()
    if not book_raw:
        raise PeriodBindingError(
            PERIOD_SOURCE_MISSING, "quote names no sportsbook/source")
    event_id = str(row.get("event_id") or row.get("source_event_id")
                   or "").strip()
    if not event_id:
        raise PeriodBindingError(
            PERIOD_EVENT_ID_MISSING,
            "quote carries no sportsbook event ID to bind to the fixture")
    game_pk_raw = row.get("game_pk")
    if game_pk_raw in (None, ""):
        game_pk_raw = row.get("game_id")
    try:
        game_pk = int(str(game_pk_raw).strip())
    except (TypeError, ValueError):
        game_pk = None
    if game_pk is None or game_pk <= 0:
        raise PeriodBindingError(
            PERIOD_FIXTURE_BINDING_MISSING,
            "quote carries no verified MLB gamePk identity")

    # Period: an explicit period must be the market's own FIRST_3 /
    # FIRST_7; absent a period field, the book's period market
    # identity (the market spelling itself) binds.
    period_raw = row.get("period")
    if period_raw not in (None, ""):
        token = str(period_raw).strip().upper().replace(" ", "_").replace("-", "_")
        if token not in _PERIOD_TOKENS_BY_INNINGS[innings]:
            raise PeriodBindingError(
                PERIOD_PERIOD_UNVERIFIED,
                f"period {period_raw!r} is not explicitly "
                f"{PERIOD_LABEL_BY_INNINGS[innings]}; an ambiguous, "
                "full-game or different-period quote refuses")
        period_basis = "EXPLICIT"
    else:
        period_basis = "MARKET_IDENTITY"

    side_raw = str(row.get("side") or row.get("selection") or "").strip().upper()
    line_raw = row.get("line")
    team_side = None
    if market in (f"{prefix}_MONEYLINE", f"{prefix}_RUN_LINE"):
        side = _TEAM_SIDE_TOKENS.get(side_raw)
        if side is None:
            if market == f"{prefix}_MONEYLINE" and side_raw in ("DRAW", "TIE"):
                raise PeriodBindingError(
                    PERIOD_SELECTION_UNVERIFIED,
                    "a three-way DRAW selection is not admissible: "
                    "the period moneyline settlement basis is TWO_WAY "
                    "(DraftKings offers no Draw selection; a tied "
                    "score after the period pushes), so a three-way "
                    "row refuses named and never joins two-way pairing")
            raise PeriodBindingError(
                PERIOD_SELECTION_UNVERIFIED,
                f"{market} selection must be a team side (HOME/AWAY), "
                f"got {side_raw!r}")
    else:
        if side_raw not in ("OVER", "UNDER"):
            raise PeriodBindingError(
                PERIOD_SELECTION_UNVERIFIED,
                f"{market} selection must be OVER or UNDER, got {side_raw!r}")
        side = side_raw
    if market == f"{prefix}_MONEYLINE":
        line = _line(line_raw)
        if line is None:
            if line_raw not in (None, ""):
                raise PeriodBindingError(
                    PERIOD_LINE_UNVERIFIED,
                    f"{prefix} moneyline line is not numeric: {line_raw!r}")
            line = 0.0
        elif line != 0.0:
            raise PeriodBindingError(
                PERIOD_LINE_UNVERIFIED,
                "a period moneyline carrying a nonzero line is a "
                "different contract")
    else:
        line = _line(line_raw)
        if line is None:
            raise PeriodBindingError(
                PERIOD_LINE_UNVERIFIED,
                f"{market} requires a numeric line, got {line_raw!r}")
        if market in (f"{prefix}_TOTALS", f"{prefix}_TEAM_TOTALS") and line < 0:
            raise PeriodBindingError(
                PERIOD_LINE_UNVERIFIED, f"{market} line must be >= 0")
    if market == f"{prefix}_TEAM_TOTALS":
        raw_team_side = str(row.get("team_side") or "").strip().upper()
        if raw_team_side in ("HOME", "AWAY"):
            team_side = raw_team_side
        elif not (row.get("team") or row.get("team_id")):
            raise PeriodBindingError(
                PERIOD_SELECTION_UNVERIFIED,
                f"{prefix} team total names no team (team_side, team or "
                "team_id required)")

    price = _american(row.get("odds", row.get("price")))
    if price is None:
        raise PeriodBindingError(
            PERIOD_PRICE_UNVERIFIED,
            "price must be integer American odds (<= -100 or >= 100)")

    captured_raw = row.get("quote_captured_at")
    if captured_raw in (None, ""):
        raise PeriodBindingError(
            PERIOD_QUOTE_TIMESTAMP_MISSING,
            "quote carries no quote_captured_at timestamp")
    captured = _parse_time(captured_raw, PERIOD_QUOTE_TIMESTAMP_INVALID)
    freshness = check_quote_freshness(captured, now=now)
    if freshness["code"] == QUOTE_STALE:
        raise PeriodBindingError(
            PERIOD_QUOTE_STALE,
            f"quote age {freshness['age_seconds']}s exceeds the 180s "
            "freshness bound at pricing time")
    if freshness["code"] != QUOTE_FRESH:
        raise PeriodBindingError(
            PERIOD_QUOTE_TIMESTAMP_INVALID,
            f"quote freshness verdict {freshness['code']} is not "
            "admissible (future or invalid capture timestamp)")

    kickoff_raw = row.get("kickoff") or row.get("commence_time")
    if kickoff_raw in (None, ""):
        raise PeriodBindingError(
            PERIOD_FIXTURE_BINDING_MISSING,
            "quote carries no kickoff/commence_time to bind the "
            "fixture against the official schedule")
    kickoff = _parse_time(kickoff_raw, PERIOD_FIXTURE_BINDING_MISSING)

    return {
        "market": market,
        "innings": innings,
        "raw_market_name": str(row.get("market") or "").strip(),
        "book": book_raw,
        "book_key": book_raw.lower(),
        "event_id": event_id,
        "game_pk": game_pk,
        "period": PERIOD_LABEL_BY_INNINGS[innings],
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
    """Resolve a period TEAM_TOTALS selection to the fixture's team ID."""
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
        raise PeriodBindingError(
            PERIOD_SELECTION_UNVERIFIED,
            f"team_id {team_id_raw!r} is not one of the fixture's teams")
    team_name = _norm_name(parsed.get("team"))
    if team_name:
        if team_name == _norm_name(fixture.get("away_name")):
            return str(away_id)
        if team_name == _norm_name(fixture.get("home_name")):
            return str(home_id)
    raise PeriodBindingError(
        PERIOD_SELECTION_UNVERIFIED,
        "period team total's team identity does not resolve against "
        "the verified fixture")


def _resolve_fixture(parsed: Mapping[str, Any],
                     fixture_resolver: Callable | None,
                     cache: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """Resolve (once per gamePk) the verified fixture for a quote."""
    game_pk = parsed["game_pk"]
    if game_pk in cache:
        return cache[game_pk]
    if fixture_resolver is None:
        raise PeriodBindingError(
            PERIOD_FIXTURE_BINDING_MISSING,
            "no verified fixture source is available on this path, so "
            "the gamePk binding cannot be verified")
    slate_date = parsed["kickoff"].astimezone(
        CHICAGO_TZ).date().isoformat()
    try:
        fixture = fixture_resolver(game_pk=game_pk, slate_date=slate_date)
    except Exception as exc:
        raise PeriodBindingError(
            PERIOD_FIXTURE_BINDING_MISSING,
            f"fixture resolution failed for gamePk "
            f"{game_pk}: {exc}") from exc
    if not isinstance(fixture, Mapping):
        raise PeriodBindingError(
            PERIOD_FIXTURE_BINDING_MISSING,
            f"gamePk {game_pk} not found on the official "
            f"schedule for {slate_date}")
    if int(fixture["game_pk"]) != game_pk:
        raise PeriodBindingError(
            PERIOD_FIXTURE_BINDING_MISMATCH,
            "resolved fixture gamePk differs from the quote's gamePk")
    first_pitch = fixture["first_pitch_at"]
    if not isinstance(first_pitch, datetime):
        first_pitch = _parse_time(first_pitch, PERIOD_FIXTURE_BINDING_MISMATCH)
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
            raise PeriodBindingError(
                PERIOD_FIXTURE_BINDING_MISMATCH,
                f"quote {field} team {parsed.get(field)!r} does not "
                f"match the verified fixture ({fixture.get(fixture_field)!r})")
    first_pitch = fixture["first_pitch_at"]
    if abs((first_pitch - parsed["kickoff"]).total_seconds()) \
            > FIRST_PITCH_TOLERANCE_SECONDS:
        raise PeriodBindingError(
            PERIOD_FIXTURE_BINDING_MISMATCH,
            "intake kickoff differs from the verified fixture's first "
            f"pitch by more than {FIRST_PITCH_TOLERANCE_SECONDS}s")
    if parsed["captured_at"] >= first_pitch:
        raise PeriodBindingError(
            PERIOD_QUOTE_NOT_PREGAME,
            "quote was captured at or after the verified first pitch")


# Canonical-quote validation for period quotes. The shared quote
# bridge (sportsedge.quote_bridge) validates by market name, and its
# market tables are kept in exact parity with the governed acceptance
# matrix -- which does not carry the period markets yet. Admitting
# them there is registry work (acceptance matrix + catalog + surface
# + provider capability, owned by the integration lane), so this
# binding performs the bridge's own checks locally, field for field,
# and fails closed with PERIOD_CANONICAL_QUOTE_REJECTED exactly where
# the bridge would raise. The emitted quote carries the bridge's
# output shape.
_PERIOD_SIDES_BY_MARKET_KIND = {
    "MONEYLINE": {"HOME", "AWAY", "HOME_ML", "AWAY_ML"},
    "RUN_LINE": {"HOME", "AWAY", "HOME_RL", "AWAY_RL"},
    "TOTALS": {"OVER", "UNDER"},
    "TEAM_TOTALS": {"OVER", "UNDER"},
}


def _validate_period_canonical_quote(raw: Mapping[str, Any]) -> dict[str, Any]:
    def reject(detail: str) -> PeriodBindingError:
        return PeriodBindingError(
            PERIOD_CANONICAL_QUOTE_REJECTED,
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
    innings = 3 if market.startswith("F3_") else 7
    if period != f"F{innings}":
        raise reject("QUOTE_PERIOD_MODEL_MISMATCH")
    kind = market.split("_", 1)[1]
    if side not in _PERIOD_SIDES_BY_MARKET_KIND[kind]:
        raise reject(f"unsupported side for {market}: {side}")
    is_alternate = raw.get("is_alternate")
    if type(is_alternate) is not bool:
        raise reject("QUOTE_IDENTITY_INCOMPLETE")
    raw_line = raw.get("line")
    if raw_line is None and kind == "MONEYLINE":
        line = 0.0
    else:
        try:
            line = float(raw_line)
        except (TypeError, ValueError) as exc:
            raise reject("line must be numeric") from exc
        if not isfinite(line):
            raise reject("line must be finite")
    if kind == "TEAM_TOTALS" and line < 0:
        raise reject("line must be >= 0")
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
    """Bridge-shaped canonical quote (period F3/F7), proven admissible
    by the period-local canonical-quote validation above."""
    raw = {
        "game_id": str(fixture["game_pk"]),
        "period": f"F{parsed['innings']}",
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
    quote = _validate_period_canonical_quote(raw)
    quote["period_period_basis"] = parsed["period_basis"]
    quote["period_event_id"] = parsed["event_id"]
    return quote


def _opposite(side: str) -> str:
    return {"HOME": "AWAY", "AWAY": "HOME",
            "OVER": "UNDER", "UNDER": "OVER"}[side]


def _lines_pair(market: str, own: float, other: float) -> bool:
    if market.endswith("_RUN_LINE"):
        return abs(own + other) < 1e-9
    return abs(own - other) < 1e-9


def _pairing_rung(market: str, side: str, line: float) -> float:
    """The pairing-identity rung of a quote's line (owner ruling
    2026-10-13: the rung line IS part of the pairing identity).

    Run-line rungs are normalized to the AWAY side's signed line
    (team-side normalization), exactly as in the F5 binding: away -0.5
    and home +0.5 are the same rung (-0.5); quotes at different rungs
    never cross-pair. Totals and team totals pair on the identical
    line; the moneyline's only rung is 0.0.
    """
    if market.endswith("_RUN_LINE"):
        rung = line if side == "AWAY" else -line
    else:
        rung = line
    return round(rung, 6) + 0.0  # + 0.0 folds a -0.0 rung into 0.0


def bind_period_quotes(rows: Sequence[Mapping[str, Any]], *, now: datetime,
                       fixture_resolver: Callable | None = None) -> dict[str, Any]:
    """Bind canonical-intake F3/F7 quote rows into admissible pairs.

    ``fixture_resolver`` is a callable (game_pk=..., slate_date=...) ->
    verified fixture mapping or None (the same seam the F5 binding
    uses). With no resolver, every otherwise-valid row fails closed
    with PERIOD_FIXTURE_BINDING_MISSING.

    Returns {"row_results": [...], "pairs": [...]}. Row results carry
    BOUND (with pair_id) or BLOCKED (with reason_code + taxonomy
    blocker). Pairs carry the two canonical quotes, the verified
    fixture, and the market's settlement-basis record.
    """
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("PERIOD_BINDING_NOW_TIMEZONE_REQUIRED")
    now = now.astimezone(timezone.utc)
    row_results: list[dict[str, Any] | None] = [None] * len(rows)
    parsed_by_index: dict[int, dict[str, Any]] = {}
    fixtures_by_pk: dict[int, dict[str, Any]] = {}

    for i, row in enumerate(rows):
        if normalize_period_market(row.get("market")) is None:
            row_results[i] = {"status": "NOT_PERIOD", "input_index": i}
            continue
        try:
            parsed = _parse_quote(row, now=now)
            fixture = _resolve_fixture(
                parsed, fixture_resolver, fixtures_by_pk)
            _cross_check_fixture(parsed, fixture)
            if parsed["market"].endswith("_TEAM_TOTALS"):
                parsed["entity_id"] = _resolve_team_entity(parsed, fixture)
            else:
                parsed["entity_id"] = str(parsed["game_pk"])
            parsed["fixture"] = fixture
            parsed_by_index[i] = parsed
        except PeriodBindingError as exc:
            row_results[i] = {
                "status": "BLOCKED", "input_index": i,
                "market": row.get("market"),
                "reason_code": exc.code, "detail": exc.detail,
                "blocker": BLOCKER_BY_REASON[exc.code],
                "research_only": True,
            }

    # Pairing: group admissible quotes by book/event/fixture/market/
    # entity/rung -- the LINE is part of the pairing identity (owner
    # ruling 2026-10-13, _pairing_rung), so each rung of a ladder is
    # its own group; a group binds only as exactly one opposite pair.
    groups: dict[tuple, list[int]] = {}
    for i, parsed in parsed_by_index.items():
        key = (parsed["book_key"], parsed["event_id"], parsed["game_pk"],
               parsed["market"], parsed["entity_id"],
               _pairing_rung(parsed["market"], parsed["side"],
                             parsed["line"]))
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
            _block(indices, PERIOD_QUOTE_UNPAIRED,
                   "a two-sided period market requires exactly one "
                   f"quote per side in the binding group; found {len(indices)}")
            continue
        first, second = (parsed_by_index[indices[0]],
                         parsed_by_index[indices[1]])
        if _opposite(first["side"]) != second["side"]:
            _block(indices, PERIOD_QUOTE_UNPAIRED,
                   "binding group holds no opposite-selection "
                   "counterpart for either quote")
            continue
        if not _lines_pair(first["market"], first["line"], second["line"]):
            _block(indices, PERIOD_QUOTE_UNPAIRED,
                   "counterpart line is not the paired line for this "
                   "market (run line negates; totals match exactly)")
            continue
        skew = abs((first["captured_at"]
                    - second["captured_at"]).total_seconds())
        if skew > MAX_PAIR_SKEW_SECONDS:
            _block(indices, PERIOD_PAIR_SKEW_EXCEEDED,
                   f"paired captures are {skew:.0f}s apart; the bound "
                   f"is {MAX_PAIR_SKEW_SECONDS}s")
            continue
        try:
            quotes = [
                _canonical_quote(p, p["fixture"], p["entity_id"])
                for p in (first, second)]
        except PeriodBindingError as exc:
            _block(indices, exc.code, exc.detail)
            continue
        pair_id = f"F{first['innings']}PAIR-{len(pairs) + 1:03d}-{first['game_pk']}"
        basis = settlement_basis(first["market"])
        pair = {
            "pair_id": pair_id,
            "market": first["market"],
            "innings": first["innings"],
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
            "rung_line": _pairing_rung(first["market"], first["side"],
                                       first["line"]),
            "quotes": quotes,
            "member_indices": list(indices),
            "settlement_basis": basis,
            "status": "BOUND" if basis["status"] == "VERIFIED"
                      else "SETTLEMENT_UNVERIFIED",
            "binding_version": PERIOD_BINDING_VERSION,
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
                    "reason_code": PERIOD_SETTLEMENT_BASIS_UNVERIFIED,
                    "detail": basis["basis"],
                    "blocker": BLOCKER_BY_REASON[
                        PERIOD_SETTLEMENT_BASIS_UNVERIFIED],
                    "research_only": True,
                }
    return {"row_results": row_results, "pairs": pairs}


# ---------------------------------------------------------------------
# Feature assembly + pricer reachability (verified pregame data only)
# ---------------------------------------------------------------------

def assemble_period_feature_rows(pair: Mapping[str, Any], *,
                                 opener: Callable,
                                 retrieved_at: datetime) -> list[dict[str, Any]]:
    """Assemble the period feature row for a bound pair.

    Uses MLBPeriodHistorySource.period_matchup_features -- strictly-prior
    StatsAPI inning linescores through the period for both clubs plus
    the strictly-prior league period prior, keyed by the verified
    fixture's team IDs and official date. The period score state is one
    joint (away, home) distribution for the matchup, so one feature row
    serves the whole pair (both quotes, and both team-total entities,
    resolve from the same joint state). No pitcher inputs, no
    sportsbook prices. Raises PeriodFeatureAssemblyError on any
    failure.
    """
    from .mlb_f5_features import MLBF5FeatureError
    from .mlb_period_features import MLBPeriodHistorySource
    fixture = pair["fixture"]
    innings = int(pair["innings"])
    source = MLBPeriodHistorySource(opener=opener, retrieved_at=retrieved_at)
    target_date = date.fromisoformat(str(fixture["official_date"]))
    try:
        features = source.period_matchup_features(
            away_team_id=int(fixture["away_team_id"]),
            home_team_id=int(fixture["home_team_id"]),
            target_date=target_date,
            innings=innings,
        )
    except MLBF5FeatureError as exc:
        raise PeriodFeatureAssemblyError(str(exc)) from exc
    features["source"] = "MLB_STATSAPI_STRICT_PRIOR_PERIOD_LINESCORE"
    features["joint_feature_version"] = features["feature_version"]
    return [features]


def price_bound_pair_readouts(pair: Mapping[str, Any],
                              feature_rows: Sequence[Mapping[str, Any]]
                              ) -> list[dict[str, Any]]:
    """Run the shared period engine session over a bound pair's quotes.

    This is a reachability proof, not a card price: it shows the bound
    canonical quotes plus assembled features are exactly what the
    period engine consumes. Only provenance hashes are returned -- no
    probability leaves this function.
    """
    from .shared_period_engine import build_shared_period_engine_session
    fixture = pair["fixture"]
    if len(feature_rows) != 1:
        raise PeriodFeatureAssemblyError(
            "period feature assembly must yield exactly one matchup row")
    feature = feature_rows[0]
    session = build_shared_period_engine_session(innings=int(pair["innings"]))
    readouts = []
    for quote in pair["quotes"]:
        model_input = {
            "game_id": str(fixture["game_pk"]),
            "market": pair["market"],
            "entity_id": str(quote["entity_id"]),
            "line": quote["line"],
            "side": quote["side"],
            "features": dict(feature["features"]),
            "feature_source_hash": feature.get("feature_source_hash"),
        }
        if pair["market"].endswith("_TEAM_TOTALS"):
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
        "period_reason": code,
        "coverage_market": normalize_period_market(row.get("market")),
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
        "innings": pair["innings"],
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
            "period_event_id": q["period_event_id"],
            "period_period_basis": q["period_period_basis"],
        } for q in pair["quotes"]],
        "binding_version": pair["binding_version"],
    }


def phone_period_binding_rows(rows: Sequence[Mapping[str, Any]], *,
                              now: datetime | None = None,
                              getter: Callable | None = None,
                              fixture_resolver: Callable | None = None,
                              opener: Callable | None = None,
                              fetch_enabled: bool = True
                              ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Canonical-card stage for F3/F7 rows: bind, assemble, gate, block.

    Every input row returns exactly one card row. All outcomes are
    BLOCKED rows today -- the gates, in order, are quote admissibility
    (this module), settlement basis, feature assembly, and the period
    deployment gate (the period markets are absent from
    config/deployments.json, so the registry lookup fails closed with
    stage UNKNOWN / "market absent from registry"). A bound pair that
    clears every upstream gate blocks with PERIOD_DEPLOYMENT_NOT_ELIGIBLE
    and carries the bound pair, feature lineage, and pricer-reachability
    hashes as evidence.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("PERIOD_STAGE_NOW_TIMEZONE_REQUIRED")
    rows = list(rows)
    if opener is None and getter is not None:
        opener = opener_from_getter(getter)
    if fixture_resolver is None and fetch_enabled:
        if opener is None:
            from urllib.request import urlopen
            opener = urlopen
        fixture_resolver = make_statsapi_fixture_resolver(opener=opener)
    bound = bind_period_quotes(rows, now=now, fixture_resolver=fixture_resolver)
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
        evidence = {"period_binding": _pair_evidence(pair)}
        if opener is None:
            results[i] = _blocked_card_row(
                rows[i], code=PERIOD_FEATURES_UNAVAILABLE,
                detail="no StatsAPI opener is available on this path, "
                       "so strictly-prior linescore history cannot be "
                       "assembled",
                evidence=evidence)
            continue
        try:
            feature_rows = assemble_period_feature_rows(
                pair, opener=opener, retrieved_at=now)
        except PeriodFeatureAssemblyError as exc:
            results[i] = _blocked_card_row(
                rows[i], code=PERIOD_FEATURES_UNAVAILABLE,
                detail=str(exc), evidence=evidence)
            continue
        feature = feature_rows[0]
        evidence["period_feature_lineage"] = {
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
                rows[i], code=PERIOD_PRICER_READOUT_FAILED,
                detail=f"{type(exc).__name__}: {exc}", evidence=evidence)
            continue
        evidence["period_pricer_reachability"] = {
            "engine": "SHARED_PERIOD_ENGINE",
            "readouts": readouts,
        }
        from .deployments import deployment_for
        deployment = deployment_for(pair["market"])
        evidence["period_deployment"] = {
            "stage": deployment.get("stage"),
            "eligible": deployment.get("eligible"),
            "reason": deployment.get("reason"),
        }
        if deployment.get("eligible") is not True:
            results[i] = _blocked_card_row(
                rows[i], code=PERIOD_DEPLOYMENT_NOT_ELIGIBLE,
                detail=(f"deployment stage "
                        f"{deployment.get('stage')} is not eligible: "
                        f"{deployment.get('reason')}"),
                evidence=evidence)
        else:
            results[i] = _blocked_card_row(
                rows[i], code=PERIOD_CANONICAL_CARD_INTEGRATION_PENDING,
                detail="quote binding, settlement basis, features and "
                       "deployment all clear, but canonical-card "
                       "pricing integration for period markets is not "
                       "built; refusing to price through an unwired route",
                evidence=evidence)
    if any(r is None for r in results):
        raise ValueError("PERIOD_STAGE_RESULT_COUNT_MISMATCH")
    counts: dict[str, int] = {}
    for result in results:
        code = result.get("period_reason", "BOUND")
        counts[code] = counts.get(code, 0) + 1
    receipts = [{
        "source": PERIOD_BINDING_VERSION,
        "status": "PERIOD_BINDING_ACTIVE_DEPLOYMENT_GATED",
        "rows": len(results),
        "bound_pairs": len(bound["pairs"]),
        "outcome_counts": counts,
    }]
    return results, receipts
