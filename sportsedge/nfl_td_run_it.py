"""NFL anytime-touchdown RUN IT pricing.

Transparent bettor-facing TD rows inspired by the disclosed presentation pattern in
the user's MySpariEdge Touchdown Picks material. This module does not reproduce or
claim MySpariEdge proprietary formulas, weights, or training data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from sports.common.ev_math import EVError, devig, parse_utc
from sportsedge.nfl_run_it_scoring import SCORE_LABEL, price_run_it_pick
from sportsedge.truth_gate import american_to_decimal

QUOTE_TTL_SECONDS = 180
MAX_QUOTE_SKEW_SECONDS = 30
REQUIRED_BOOK = "DraftKings"


class NflTdRunItError(ValueError):
    pass


@dataclass(frozen=True)
class TdPick:
    player: str
    game_id: str
    price_american: int
    estimate_p: float
    market_no_vig_p: float
    fair_american: int
    edge_probability_points: float
    ev_per_dollar: float
    score_0_100: int
    score_label: str = SCORE_LABEL


def _utc(value: Any) -> datetime:
    try:
        return parse_utc(value).astimezone(timezone.utc)
    except (EVError, TypeError, ValueError) as exc:
        raise NflTdRunItError("TD_QUOTE_TIMESTAMP_INVALID") from exc


def _american(value: Any) -> int:
    try:
        odds = int(value)
    except (TypeError, ValueError) as exc:
        raise NflTdRunItError("TD_PRICE_INVALID") from exc
    if -100 < odds < 100:
        raise NflTdRunItError("TD_PRICE_INVALID")
    return odds


def price_anytime_td(
    *,
    player: str,
    game_id: str,
    estimate_p: float,
    yes_quote: Mapping[str, Any],
    no_quote: Mapping[str, Any],
    as_of: datetime | str,
) -> TdPick:
    """Price a paired YES/NO anytime-TD market; fail closed on stale identity."""
    if not player.strip() or not game_id.strip():
        raise NflTdRunItError("TD_IDENTITY_INCOMPLETE")
    if not isfinite(estimate_p) or not 0.0 < estimate_p < 1.0:
        raise NflTdRunItError("TD_ESTIMATE_INVALID")
    now = _utc(as_of)
    times = [_utc(yes_quote.get("retrieved_at")), _utc(no_quote.get("retrieved_at"))]
    if any((now - t).total_seconds() > QUOTE_TTL_SECONDS for t in times):
        raise NflTdRunItError("TD_QUOTE_STALE")
    if any((now - t).total_seconds() < -MAX_QUOTE_SKEW_SECONDS for t in times):
        raise NflTdRunItError("TD_QUOTE_CLOCK_SKEW")
    if abs((times[0] - times[1]).total_seconds()) > MAX_QUOTE_SKEW_SECONDS:
        raise NflTdRunItError("TD_PAIRED_QUOTE_TIME_SKEW")
    for q, side in ((yes_quote, "YES"), (no_quote, "NO")):
        if str(q.get("player", "")).strip() != player or str(q.get("game_id", "")).strip() != game_id:
            raise NflTdRunItError("TD_PAIRED_IDENTITY_MISMATCH")
        if str(q.get("selection", "")).upper() != side:
            raise NflTdRunItError("TD_PAIRED_SELECTION_MISMATCH")
        if str(q.get("book", "")).strip() != REQUIRED_BOOK:
            raise NflTdRunItError("TD_BOOK_MISMATCH")
    yes_price, no_price = _american(yes_quote.get("price_american")), _american(no_quote.get("price_american"))
    decimals = [american_to_decimal(yes_price), american_to_decimal(no_price)]
    try:
        market_p = float(devig(decimals, trigger_american=400, max_spread_pp=1.0)[0])
    except EVError as exc:
        raise NflTdRunItError(exc.code) from exc
    priced = price_run_it_pick(
        estimate_p=estimate_p,
        push_p=0.0,
        price_american=yes_price,
        market_no_vig_p=market_p,
    )
    return TdPick(
        player=player,
        game_id=game_id,
        price_american=yes_price,
        estimate_p=estimate_p,
        market_no_vig_p=market_p,
        fair_american=priced.fair_american,
        edge_probability_points=priced.edge_probability_points,
        ev_per_dollar=priced.ev_per_dollar,
        score_0_100=priced.score_0_100,
    )


def rank_td_board(rows: Sequence[TdPick]) -> tuple[TdPick, ...]:
    return tuple(sorted(rows, key=lambda r: (-r.score_0_100, -r.ev_per_dollar, -r.edge_probability_points, r.player)))
