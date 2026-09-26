"""Anytime-TD RUN IT board with independent model estimate and locked Score B.

Quote hygiene (#898 design):
- ≥3 books must supply a complete YES/NO pair at the same line semantics
  (anytime TD has no numeric line; pairs are per book).
- Divergent book coverage that cannot form a 3-book consensus →
  BLOCKED_QUOTE_HYGIENE or BLOCKED_INSUFFICIENT_BOOKS for that row only.
- Never select the best-edge book: executable YES price is the median across
  qualifying books; no-vig is the median of per-book POWER no-vig.

Per-row failures return status=BLOCKED with a reason; other rows still rank.
Estimates must pass nfl_prop_shared_sim._assert_no_market_inputs.

No Model_P, Truth Gate, freeze, eligibility, or OFFICIAL authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from statistics import median
from typing import Any, Mapping, Sequence

from sports.common.ev_math import EVError, devig, parse_utc
from sportsedge.nfl_prop_shared_sim import NflPropSimulationError, _assert_no_market_inputs
from sportsedge.nfl_run_it_score_binding import score_b_by_identity
from sportsedge.truth_gate import american_to_decimal

TTL = 180
SKEW = 30
MIN_BOOKS = 3


class NflTdBoardError(ValueError):
    pass


@dataclass(frozen=True)
class TdBoardPick:
    rank: int
    game_id: str
    player: str
    status: str
    block_reason: str | None
    price_american: int | None
    estimate_p: float
    market_no_vig_p: float | None
    edge_probability_points: float | None
    ev_per_dollar: float | None
    fair_american: int | None
    score_0_100: int | None
    books_used: tuple[str, ...]


def _ts(value: Any) -> datetime:
    try:
        return parse_utc(value).astimezone(timezone.utc)
    except (EVError, TypeError, ValueError) as exc:
        raise NflTdBoardError("QUOTE_TIME_INVALID") from exc


def _american(p: float) -> int:
    if not 0 < p < 1:
        raise NflTdBoardError("ESTIMATE_P_INVALID")
    if p >= 0.5:
        return int(round(-100 * p / (1 - p)))
    return int(round(100 * (1 - p) / p))


def _median_int(values: Sequence[int]) -> int:
    ordered = sorted(values)
    return int(round(median(ordered)))


def _blocked(
    *,
    rank: int,
    game_id: str,
    player: str,
    estimate_p: float,
    reason: str,
) -> TdBoardPick:
    return TdBoardPick(
        rank=rank,
        game_id=game_id,
        player=player,
        status="BLOCKED",
        block_reason=reason,
        price_american=None,
        estimate_p=estimate_p,
        market_no_vig_p=None,
        edge_probability_points=None,
        ev_per_dollar=None,
        fair_american=None,
        score_0_100=None,
        books_used=(),
    )


def run_td_board(
    *,
    estimates: Sequence[Mapping[str, Any]],
    quotes: Sequence[Mapping[str, Any]],
    qualification_snapshots: Sequence[Mapping[str, Any]],
    as_of: datetime | str,
) -> list[TdBoardPick]:
    now = _ts(as_of)
    try:
        scores = score_b_by_identity(qualification_snapshots)
    except Exception as exc:
        raise NflTdBoardError(f"QUALIFICATION_BINDING_FAILED:{exc}") from exc

    est: dict[tuple[str, str], float] = {}
    for row in estimates:
        try:
            _assert_no_market_inputs(row)
        except NflPropSimulationError as exc:
            raise NflTdBoardError("MARKET_INPUT_FORBIDDEN_IN_TD_ESTIMATE") from exc
        key = (str(row.get("game_id") or "").strip(), str(row.get("player") or "").strip())
        try:
            p = float(row["estimate_p"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NflTdBoardError("ESTIMATE_P_REQUIRED") from exc
        if not all(key) or not isfinite(p) or not 0 < p < 1:
            raise NflTdBoardError("TD_ESTIMATE_INVALID")
        est[key] = p

    # book -> (game, player) -> side -> (price, retrieved)
    by_book: dict[str, dict[tuple[str, str], dict[str, tuple[int, datetime]]]] = {}
    for quote in quotes:
        game = str(quote.get("game_id") or "").strip()
        player = str(quote.get("player") or "").strip()
        side = str(quote.get("selection") or "").upper().strip()
        book = str(quote.get("book") or "").lower().strip()
        if not game or not player or side not in {"YES", "NO"} or not book:
            continue  # skip malformed; row hygiene decides later
        try:
            retrieved = _ts(quote.get("retrieved_at"))
            price = int(quote["price_american"])
        except (NflTdBoardError, KeyError, TypeError, ValueError):
            continue
        if -100 < price < 100:
            continue
        age = (now - retrieved).total_seconds()
        if age > TTL or age < -SKEW:
            # mark via absence from fresh pairs; row logic will BLOCK
            by_book.setdefault(book, {}).setdefault((game, player), {})[f"_stale_{side}"] = (price, retrieved)
            continue
        by_book.setdefault(book, {}).setdefault((game, player), {})[side] = (price, retrieved)

    ranked_ready: list[dict[str, Any]] = []
    blocked_rows: list[TdBoardPick] = []

    for key, p in est.items():
        game_id, player = key
        fresh_pairs: dict[str, dict[str, tuple[int, datetime]]] = {}
        stale_seen = False
        for book, players in by_book.items():
            sides = players.get(key, {})
            if any(s.startswith("_stale_") for s in sides):
                stale_seen = True
            if set(sides.keys()) >= {"YES", "NO"}:
                if abs((sides["YES"][1] - sides["NO"][1]).total_seconds()) > SKEW:
                    stale_seen = True
                    continue
                fresh_pairs[book] = {"YES": sides["YES"], "NO": sides["NO"]}

        if len(fresh_pairs) < MIN_BOOKS:
            reason = "BLOCKED_QUOTE_STALE" if stale_seen and len(fresh_pairs) == 0 else "BLOCKED_INSUFFICIENT_BOOKS"
            if len(fresh_pairs) > 0 and len(fresh_pairs) < MIN_BOOKS:
                reason = "BLOCKED_INSUFFICIENT_BOOKS"
            blocked_rows.append(
                _blocked(rank=0, game_id=game_id, player=player, estimate_p=p, reason=reason)
            )
            continue

        yes_prices = [fresh_pairs[b]["YES"][0] for b in sorted(fresh_pairs)]
        no_prices = [fresh_pairs[b]["NO"][0] for b in sorted(fresh_pairs)]
        no_vig_vals: list[float] = []
        sensitivity_fail = False
        for book in sorted(fresh_pairs):
            pair = fresh_pairs[book]
            dec = [american_to_decimal(pair["YES"][0]), american_to_decimal(pair["NO"][0])]
            try:
                nv = float(devig(dec, trigger_american=400, max_spread_pp=1.0)[0])
            except EVError:
                sensitivity_fail = True
                break
            no_vig_vals.append(nv)
        if sensitivity_fail:
            blocked_rows.append(
                _blocked(
                    rank=0,
                    game_id=game_id,
                    player=player,
                    estimate_p=p,
                    reason="BLOCKED_DEVIG_SENSITIVITY",
                )
            )
            continue

        score_key = (game_id, "anytime_td", player)
        if score_key not in scores:
            blocked_rows.append(
                _blocked(
                    rank=0,
                    game_id=game_id,
                    player=player,
                    estimate_p=p,
                    reason="BLOCKED_MISSING_QUALIFICATION",
                )
            )
            continue

        # Median price — never best-edge book selection.
        price = _median_int(yes_prices)
        no_vig = float(median(no_vig_vals))
        ev = p * (american_to_decimal(price) - 1) - (1 - p)
        edge = p - no_vig
        ranked_ready.append(
            {
                "game_id": game_id,
                "player": player,
                "status": "OK",
                "block_reason": None,
                "price_american": price,
                "estimate_p": p,
                "market_no_vig_p": no_vig,
                "edge_probability_points": edge,
                "ev_per_dollar": ev,
                "fair_american": _american(p),
                "score_0_100": scores[score_key],
                "books_used": tuple(sorted(fresh_pairs)),
            }
        )

    ranked_ready.sort(
        key=lambda r: (
            -r["ev_per_dollar"],
            -r["edge_probability_points"],
            r["game_id"],
            r["player"],
        )
    )
    out: list[TdBoardPick] = []
    for i, row in enumerate(ranked_ready, 1):
        out.append(TdBoardPick(rank=i, **row))
    # Blocked rows after OK ranks, stable by identity
    blocked_rows.sort(key=lambda r: (r.game_id, r.player))
    for i, row in enumerate(blocked_rows, start=len(out) + 1):
        out.append(
            TdBoardPick(
                rank=i,
                game_id=row.game_id,
                player=row.player,
                status=row.status,
                block_reason=row.block_reason,
                price_american=None,
                estimate_p=row.estimate_p,
                market_no_vig_p=None,
                edge_probability_points=None,
                ev_per_dollar=None,
                fair_american=None,
                score_0_100=None,
                books_used=(),
            )
        )
    return out
