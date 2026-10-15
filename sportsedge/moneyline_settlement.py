"""Typed moneyline settlement: TWO_WAY vs THREE_WAY, declared per book.

Isaac's F5 settlement ruling (2026-10-12): DraftKings' published rules
distinguish two moneyline settlement types, and they must be implemented
as explicitly distinct types rather than a market convention:

* TWO_WAY -- only the two team selections are offered; "Draw"/"Tie" is
  not a selection. A tie settles as PUSH (stake returned).
* THREE_WAY -- home / draw / away are all selections. A tie settles as
  the DRAW selection: team selections LOSE, the draw selection WINS,
  and there is no push.

DraftKings' own published taxonomy (General Betting Rules -> Market
Rules, https://sportsbook.draftkings.com/help/general-betting-rules/market-rules)
defines exactly these two market types: for 2-Way Moneyline Markets a
draw is not offered as a selection and tied selections settle as Push;
3-Way Moneyline Markets additionally offer the tie/draw as a selection.

Verified declarations (each checked against the book's published rules
before being recorded here -- an undeclared (market, book) pair fails
closed, it never inherits a type from another market or book):

* F5_MONEYLINE @ DraftKings = TWO_WAY. The DraftKings baseball betting
  guide's first-five-innings section
  (https://sportsbook.draftkings.com/help/how-to-bet/baseball-betting-guide)
  offers only the two teams for the F5 moneyline and states that a team
  bet tied after five innings pushes with the stake refunded.
* MONEYLINE (full game) @ DraftKings = TWO_WAY. Same market-rules
  taxonomy; the full-game baseball moneyline offers only the two teams.

Settlement functions in this module refuse with
SETTLEMENT_TYPE_UNDECLARED when no verified declaration exists, so a
moneyline tie can never be settled by guessing a book's policy.

Research only. No betting authority, no staking, no order placement.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Mapping

from .odds_api_source import normalize_name

SETTLEMENT_TYPE_MODEL_VERSION = "MONEYLINE_SETTLEMENT_TYPES_V1"

SETTLEMENT_TYPE_UNDECLARED = "SETTLEMENT_TYPE_UNDECLARED"
MONEYLINE_DRAW_SELECTION_NOT_OFFERED = (
    "MONEYLINE_DRAW_SELECTION_NOT_OFFERED_TWO_WAY")
MONEYLINE_SIDE_INVALID = "MONEYLINE_SIDE_INVALID"

DK_MARKET_RULES_URL = (
    "https://sportsbook.draftkings.com/help/general-betting-rules/"
    "market-rules")
DK_BASEBALL_GUIDE_URL = (
    "https://sportsbook.draftkings.com/help/how-to-bet/"
    "baseball-betting-guide")


class MoneylineSettlementError(ValueError):
    """A moneyline settlement that cannot be typed or settled."""


class MoneylineSettlementType(str, Enum):
    """The two explicitly distinct moneyline settlement types."""

    TWO_WAY = "TWO_WAY"
    THREE_WAY = "THREE_WAY"


_TEAM_HOME = frozenset({"HOME", "HOME_ML"})
_TEAM_AWAY = frozenset({"AWAY", "AWAY_ML"})
_DRAW = frozenset({"DRAW", "TIE"})

# Verified (market, sportsbook) -> settlement-type declarations. Keys are
# normalized with the same normalize_name the settlement joiners use to
# compare sportsbook identities, so "DraftKings" / "draftkings" /
# "draft kings" resolve identically everywhere.
_DECLARATIONS: dict[tuple[str, str], Mapping[str, Any]] = {}


def _declare(*, market: str, sportsbook: str,
             settlement_type: MoneylineSettlementType, basis: str,
             sources: tuple[str, ...]) -> None:
    _DECLARATIONS[(market, normalize_name(sportsbook))] = {
        "market": market,
        "sportsbook": sportsbook,
        "settlement_type": settlement_type,
        "basis": basis,
        "sources": sources,
        "model_version": SETTLEMENT_TYPE_MODEL_VERSION,
    }


_declare(
    market="F5_MONEYLINE",
    sportsbook="DraftKings",
    settlement_type=MoneylineSettlementType.TWO_WAY,
    basis=(
        "VERIFIED_TWO_WAY -- DraftKings offers only the two teams for "
        "the first-five-innings moneyline (no Draw selection), and its "
        "published baseball guide states a team bet tied after the "
        "fifth inning pushes with the stake refunded; under DraftKings' "
        "published market-rules taxonomy that is a 2-Way Moneyline "
        "Market, whose ties settle as Push. Owner ruling 2026-10-12 "
        "adopts the same two-way/three-way distinction."),
    sources=(DK_BASEBALL_GUIDE_URL, DK_MARKET_RULES_URL),
)
for _period_market in ("F3_MONEYLINE", "F7_MONEYLINE"):
    _declare(
        market=_period_market,
        sportsbook="DraftKings",
        settlement_type=MoneylineSettlementType.TWO_WAY,
        basis=(
            "VERIFIED_TWO_WAY -- DraftKings offers only the two teams "
            "for the first-3-innings and first-7-innings moneylines "
            "(no Draw selection; enumerated in the Oct 13 2026 "
            "DraftKings catalog capture's 1st-3 / 1st-7 innings sets), "
            "and its published baseball guide states a team bet tied "
            "after the period pushes with the stake refunded; under "
            "DraftKings' published market-rules taxonomy that is a "
            "2-Way Moneyline Market, whose ties settle as Push -- the "
            "same published-rules basis as the F5_MONEYLINE "
            "declaration. Owner ruling 2026-10-12 adopts the same "
            "two-way/three-way distinction."),
        sources=(DK_BASEBALL_GUIDE_URL, DK_MARKET_RULES_URL),
    )
_declare(
    market="MONEYLINE",
    sportsbook="DraftKings",
    settlement_type=MoneylineSettlementType.TWO_WAY,
    basis=(
        "VERIFIED_TWO_WAY -- the DraftKings full-game baseball "
        "moneyline offers only the two teams (no Draw selection); "
        "under DraftKings' published market-rules taxonomy that is a "
        "2-Way Moneyline Market, whose ties settle as Push."),
    sources=(DK_MARKET_RULES_URL, DK_BASEBALL_GUIDE_URL),
)


def moneyline_settlement_declaration(
        market: Any, sportsbook: Any) -> dict[str, Any] | None:
    """The verified declaration for (market, sportsbook), else None."""
    key = (str(market or "").strip().upper(),
           normalize_name(sportsbook))
    declaration = _DECLARATIONS.get(key)
    return dict(declaration) if declaration is not None else None


def declared_moneyline_settlement_type(
        market: Any, sportsbook: Any) -> MoneylineSettlementType | None:
    """The declared settlement type, or None when unverified."""
    declaration = moneyline_settlement_declaration(market, sportsbook)
    if declaration is None:
        return None
    return declaration["settlement_type"]


def require_moneyline_settlement_type(
        market: Any, sportsbook: Any) -> MoneylineSettlementType:
    """The declared type, failing closed when none is verified."""
    settlement_type = declared_moneyline_settlement_type(
        market, sportsbook)
    if settlement_type is None:
        raise MoneylineSettlementError(
            f"{SETTLEMENT_TYPE_UNDECLARED}: no verified moneyline "
            f"settlement type for market={market!r} "
            f"sportsbook={sportsbook!r}")
    return settlement_type


def _coerce_type(
        settlement_type: Any) -> MoneylineSettlementType:
    if isinstance(settlement_type, MoneylineSettlementType):
        return settlement_type
    try:
        return MoneylineSettlementType(str(settlement_type).strip().upper())
    except ValueError:
        raise MoneylineSettlementError(
            f"{SETTLEMENT_TYPE_UNDECLARED}: moneyline settlement type "
            f"is not declared (got {settlement_type!r})") from None


def settle_moneyline(settlement_type: Any, *, side: Any,
                     selected_runs: float, other_runs: float) -> str:
    """Settle one moneyline selection under an explicit type.

    Returns WIN / LOSS / PUSH. TWO_WAY: a tie is a PUSH and a DRAW
    selection does not exist. THREE_WAY: a tie makes team selections
    LOSE and the DRAW selection WIN -- never a push. An undeclared or
    unrecognized type fails closed with SETTLEMENT_TYPE_UNDECLARED.
    """
    resolved = _coerce_type(settlement_type)
    direction = str(side or "").strip().upper()
    tied = float(selected_runs) == float(other_runs)
    if direction in _DRAW:
        if resolved is MoneylineSettlementType.TWO_WAY:
            raise MoneylineSettlementError(
                f"{MONEYLINE_DRAW_SELECTION_NOT_OFFERED}: a two-way "
                "moneyline has no draw selection")
        return "WIN" if tied else "LOSS"
    if direction in _TEAM_HOME or direction in _TEAM_AWAY:
        if tied:
            return ("PUSH" if resolved is MoneylineSettlementType.TWO_WAY
                    else "LOSS")
        return "WIN" if float(selected_runs) > float(other_runs) else "LOSS"
    raise MoneylineSettlementError(
        f"{MONEYLINE_SIDE_INVALID}: {side!r}")


def moneyline_winning_outcome(settlement_type: Any, *,
                              home_runs: float, away_runs: float) -> str:
    """The winning outcome of a moneyline market under an explicit type.

    Returns HOME / AWAY / PUSH (two-way tie) / DRAW (three-way tie).
    The PUSH-vs-DRAW distinction is the whole point of the type model:
    a three-way tie is a decided DRAW outcome, never a push.
    """
    resolved = _coerce_type(settlement_type)
    if float(home_runs) > float(away_runs):
        return "HOME"
    if float(away_runs) > float(home_runs):
        return "AWAY"
    return ("PUSH" if resolved is MoneylineSettlementType.TWO_WAY
            else "DRAW")
