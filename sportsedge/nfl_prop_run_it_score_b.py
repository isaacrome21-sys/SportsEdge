"""Broad NFL player-prop RUN IT board with locked Score B.

Quote hygiene (#898 design):
- ≥3 books must supply a complete OVER/UNDER pair at the identical line.
- Different lines across books → BLOCKED_QUOTE_HYGIENE.
- Fewer than 3 books at the consensus line → BLOCKED_INSUFFICIENT_BOOKS.

Price vs benchmark split:
- Executable price = one pre-declared book (default draftkings) and its real
  posted price for the selection. EV and fair_american use that price only.
- Benchmark = median of per-book POWER_V1 no-vig across qualifying books.
- Never choose the executable book by price or edge.
- If the executable book lacks a fresh pair at the agreed line →
  BLOCKED_EXECUTABLE_BOOK_MISSING.

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

PROP_FAMILIES = frozenset(
    {
        "receptions",
        "receiving_yards",
        "passing_yards",
        "rushing_yards",
        "rush_attempts",
        "pass_attempts",
        "completions",
        "pass_tds",
        "interceptions",
        "rush_receiving_yards",
    }
)
TTL = 180
SKEW = 30
MIN_BOOKS = 3
DEFAULT_EXECUTABLE_BOOK = "draftkings"


class NflPropBoardError(ValueError):
    pass


@dataclass(frozen=True)
class PropPick:
    rank: int
    game_id: str
    player: str
    market: str
    selection: str
    line: float
    status: str
    block_reason: str | None
    book: str | None
    price_american: int | None
    estimate_p: float
    push_p: float
    fair_american: int | None
    market_no_vig_p: float | None
    edge_probability_points: float | None
    ev_per_dollar: float | None
    score_0_100: int | None
    books_used: tuple[str, ...]


def _ts(value: Any) -> datetime:
    try:
        return parse_utc(value).astimezone(timezone.utc)
    except (EVError, TypeError, ValueError) as exc:
        raise NflPropBoardError("QUOTE_TIME_INVALID") from exc


def _fair(p: float) -> int:
    if not 0 < p < 1:
        raise NflPropBoardError("FAIR_P_INVALID")
    if p >= 0.5:
        return int(round(-100 * p / (1 - p)))
    return int(round(100 * (1 - p) / p))


def _blocked(
    *,
    rank: int,
    game_id: str,
    player: str,
    market: str,
    selection: str,
    line: float,
    estimate_p: float,
    push_p: float,
    reason: str,
) -> PropPick:
    return PropPick(
        rank=rank,
        game_id=game_id,
        player=player,
        market=market,
        selection=selection,
        line=line,
        status="BLOCKED",
        block_reason=reason,
        book=None,
        price_american=None,
        estimate_p=estimate_p,
        push_p=push_p,
        fair_american=None,
        market_no_vig_p=None,
        edge_probability_points=None,
        ev_per_dollar=None,
        score_0_100=None,
        books_used=(),
    )


def run_prop_board(
    *,
    estimates: Sequence[Mapping[str, Any]],
    quotes: Sequence[Mapping[str, Any]],
    qualification_snapshots: Sequence[Mapping[str, Any]],
    as_of: datetime | str,
    executable_book: str = DEFAULT_EXECUTABLE_BOOK,
) -> list[PropPick]:
    now = _ts(as_of)
    exec_book = str(executable_book or DEFAULT_EXECUTABLE_BOOK).lower().strip()
    if not exec_book:
        raise NflPropBoardError("EXECUTABLE_BOOK_REQUIRED")

    try:
        scores = score_b_by_identity(qualification_snapshots)
    except Exception as exc:
        raise NflPropBoardError(f"QUALIFICATION_BINDING_FAILED:{exc}") from exc

    est: dict[tuple[str, str, str, str, float], tuple[float, float]] = {}
    for row in estimates:
        try:
            _assert_no_market_inputs(row)
        except NflPropSimulationError as exc:
            raise NflPropBoardError("MARKET_INPUT_FORBIDDEN_IN_PROP_ESTIMATE") from exc
        game = str(row.get("game_id") or "").strip()
        player = str(row.get("player") or "").strip()
        market = str(row.get("market") or "").strip()
        side = str(row.get("selection") or "").upper().strip()
        if not game or not player or market not in PROP_FAMILIES or side not in {"OVER", "UNDER"}:
            raise NflPropBoardError("PROP_ESTIMATE_IDENTITY_INVALID")
        try:
            line = float(row["line"])
            p = float(row["estimate_p"])
            push = float(row.get("push_p", 0))
        except (KeyError, TypeError, ValueError) as exc:
            raise NflPropBoardError("PROP_ESTIMATE_NUMERIC_INVALID") from exc
        if not all(map(isfinite, (line, p, push))) or line < 0 or p <= 0 or p >= 1 or push < 0 or p + push > 1:
            raise NflPropBoardError("PROP_ESTIMATE_MASS_INVALID")
        est[(game, player, market, side, line)] = (p, push)

    by_book: dict[str, dict[tuple[str, str, str], dict[float, dict[str, tuple[int, datetime]]]]] = {}
    for quote in quotes:
        game = str(quote.get("game_id") or "").strip()
        player = str(quote.get("player") or "").strip()
        market = str(quote.get("market") or "").strip()
        side = str(quote.get("selection") or "").upper().strip()
        book = str(quote.get("book") or "").lower().strip()
        if not game or not player or market not in PROP_FAMILIES or side not in {"OVER", "UNDER"} or not book:
            continue
        try:
            line = float(quote["line"])
            price = int(quote["price_american"])
            retrieved = _ts(quote.get("retrieved_at"))
        except (NflPropBoardError, KeyError, TypeError, ValueError):
            continue
        if -100 < price < 100:
            continue
        age = (now - retrieved).total_seconds()
        if age > TTL or age < -SKEW:
            continue
        by_book.setdefault(book, {}).setdefault((game, player, market), {}).setdefault(line, {})[
            side
        ] = (price, retrieved)

    ranked_ready: list[dict[str, Any]] = []
    blocked_rows: list[PropPick] = []

    for (game, player, market, side, line), (p, push) in est.items():
        identity = (game, player, market)

        book_lines: dict[str, set[float]] = {}
        book_pairs_at_line: dict[str, dict[str, tuple[int, datetime]]] = {}
        for book, idents in by_book.items():
            lines_map = idents.get(identity, {})
            book_lines[book] = set(lines_map.keys())
            for posted_line, sides in lines_map.items():
                if abs(posted_line - line) > 1e-9:
                    continue
                if set(sides.keys()) >= {"OVER", "UNDER"}:
                    if abs((sides["OVER"][1] - sides["UNDER"][1]).total_seconds()) > SKEW:
                        continue
                    book_pairs_at_line[book] = sides

        observed_lines: set[float] = set()
        for lines in book_lines.values():
            observed_lines |= lines
        if len(observed_lines) > 1:
            blocked_rows.append(
                _blocked(
                    rank=0,
                    game_id=game,
                    player=player,
                    market=market,
                    selection=side,
                    line=line,
                    estimate_p=p,
                    push_p=push,
                    reason="BLOCKED_QUOTE_HYGIENE",
                )
            )
            continue

        if len(book_pairs_at_line) < MIN_BOOKS:
            blocked_rows.append(
                _blocked(
                    rank=0,
                    game_id=game,
                    player=player,
                    market=market,
                    selection=side,
                    line=line,
                    estimate_p=p,
                    push_p=push,
                    reason="BLOCKED_INSUFFICIENT_BOOKS",
                )
            )
            continue

        if exec_book not in book_pairs_at_line:
            blocked_rows.append(
                _blocked(
                    rank=0,
                    game_id=game,
                    player=player,
                    market=market,
                    selection=side,
                    line=line,
                    estimate_p=p,
                    push_p=push,
                    reason="BLOCKED_EXECUTABLE_BOOK_MISSING",
                )
            )
            continue

        no_vig_vals: list[float] = []
        sensitivity_fail = False
        for book in sorted(book_pairs_at_line):
            pair = book_pairs_at_line[book]
            dec = [american_to_decimal(pair["OVER"][0]), american_to_decimal(pair["UNDER"][0])]
            try:
                nv = devig(dec, trigger_american=400, max_spread_pp=1.0)
            except EVError:
                sensitivity_fail = True
                break
            idx = 0 if side == "OVER" else 1
            no_vig_vals.append(float(nv[idx]))
        if sensitivity_fail:
            blocked_rows.append(
                _blocked(
                    rank=0,
                    game_id=game,
                    player=player,
                    market=market,
                    selection=side,
                    line=line,
                    estimate_p=p,
                    push_p=push,
                    reason="BLOCKED_DEVIG_SENSITIVITY",
                )
            )
            continue

        score_key = (game, market, player)
        if score_key not in scores:
            blocked_rows.append(
                _blocked(
                    rank=0,
                    game_id=game,
                    player=player,
                    market=market,
                    selection=side,
                    line=line,
                    estimate_p=p,
                    push_p=push,
                    reason="BLOCKED_MISSING_QUALIFICATION",
                )
            )
            continue

        # Executable: fixed book only — never median, never best edge.
        price = int(book_pairs_at_line[exec_book][side][0])
        no_vig = float(median(no_vig_vals))
        loss = max(0.0, 1 - p - push)
        decisive = p + loss
        if decisive <= 0:
            blocked_rows.append(
                _blocked(
                    rank=0,
                    game_id=game,
                    player=player,
                    market=market,
                    selection=side,
                    line=line,
                    estimate_p=p,
                    push_p=push,
                    reason="BLOCKED_NON_PUSH_MASS_ZERO",
                )
            )
            continue
        fair_p = p / decisive
        edge = fair_p - no_vig
        ev = p * (american_to_decimal(price) - 1) - loss
        ranked_ready.append(
            {
                "game_id": game,
                "player": player,
                "market": market,
                "selection": side,
                "line": line,
                "status": "OK",
                "block_reason": None,
                "book": exec_book,
                "price_american": price,
                "estimate_p": p,
                "push_p": push,
                "fair_american": _fair(fair_p),
                "market_no_vig_p": no_vig,
                "edge_probability_points": edge,
                "ev_per_dollar": ev,
                "score_0_100": scores[score_key],
                "books_used": tuple(sorted(book_pairs_at_line)),
            }
        )

    ranked_ready.sort(
        key=lambda r: (
            -r["ev_per_dollar"],
            -r["edge_probability_points"],
            r["game_id"],
            r["market"],
            r["player"],
            r["selection"],
            r["line"],
        )
    )
    out: list[PropPick] = []
    for i, row in enumerate(ranked_ready, 1):
        out.append(PropPick(rank=i, **row))
    blocked_rows.sort(key=lambda r: (r.game_id, r.market, r.player, r.selection, r.line))
    for i, row in enumerate(blocked_rows, start=len(out) + 1):
        out.append(
            PropPick(
                rank=i,
                game_id=row.game_id,
                player=row.player,
                market=row.market,
                selection=row.selection,
                line=row.line,
                status="BLOCKED",
                block_reason=row.block_reason,
                book=None,
                price_american=None,
                estimate_p=row.estimate_p,
                push_p=row.push_p,
                fair_american=None,
                market_no_vig_p=None,
                edge_probability_points=None,
                ev_per_dollar=None,
                score_0_100=None,
                books_used=(),
            )
        )
    return out
