"""Research-only benchmarks from the frozen historical CFB market archive.

This module intentionally cannot fit, calibrate, select, or promote a model.  It
reduces the checksum-bound retrospective market archive into deterministic coverage
statistics and game-level market references that may be used only as research
context after model construction.  Unknown row timing is never interpreted as an
opening, decision, or closing timestamp.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import json
from math import isfinite
import re
from statistics import median
from typing import Any, Iterable, Mapping

CFB_MARKET_BENCHMARK_VERSION = "CFB_HISTORICAL_MARKET_BENCHMARK_V1"
_ALLOWED_MARKETS = frozenset({"spread", "total", "money_line"})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CFBMarketBenchmarkError(ValueError):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _side_name(value: Any) -> str:
    return " ".join(_text(value).casefold().split())


def _number(value: Any) -> float | None:
    text = _text(value)
    if not text:
        return None
    try:
        out = float(text)
    except (TypeError, ValueError):
        return None
    return out if isfinite(out) else None


def _season(value: Any) -> int:
    number = _number(value)
    if number is None or int(number) != number or not 1900 <= int(number) <= 2200:
        raise CFBMarketBenchmarkError("CFB_MARKET_BENCHMARK_SEASON_INVALID")
    return int(number)


def _game_sides(game_desc: Any) -> tuple[str, str] | None:
    text = _text(game_desc)
    if text.count("@") != 1:
        return None
    away, home = text.split("@", 1)
    away_name, home_name = _side_name(away), _side_name(home)
    if not away_name or not home_name or away_name == home_name:
        return None
    return away_name, home_name


def _american_implied(odds: float) -> float | None:
    if odds == 0 or not isfinite(odds):
        return None
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return (-odds) / ((-odds) + 100.0)


def _novig_home_probability(home_odds: float, away_odds: float) -> float | None:
    hp, ap = _american_implied(home_odds), _american_implied(away_odds)
    if hp is None or ap is None or hp <= 0 or ap <= 0 or hp + ap <= 0:
        return None
    return hp / (hp + ap)


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def build_historical_market_benchmark(
    rows: Iterable[Mapping[str, Any]],
    *,
    source_sha256: str,
    expected_row_count: int | None = None,
) -> dict[str, Any]:
    """Build deterministic research-only coverage and game-level references.

    A book/game value is admitted to a game-level reference only when that book has
    exactly one distinct numeric value for that market.  Multiple distinct values
    are treated as temporally ambiguous and excluded; no first/last/open/close
    semantics are inferred from row order.
    """
    source_hash = _text(source_sha256).lower()
    if _SHA256.fullmatch(source_hash) is None:
        raise CFBMarketBenchmarkError("CFB_MARKET_BENCHMARK_SOURCE_SHA256_INVALID")
    if expected_row_count is not None:
        if isinstance(expected_row_count, bool):
            raise CFBMarketBenchmarkError("CFB_MARKET_BENCHMARK_EXPECTED_ROWS_INVALID")
        try:
            expected = int(expected_row_count)
        except (TypeError, ValueError) as exc:
            raise CFBMarketBenchmarkError("CFB_MARKET_BENCHMARK_EXPECTED_ROWS_INVALID") from exc
        if expected <= 0:
            raise CFBMarketBenchmarkError("CFB_MARKET_BENCHMARK_EXPECTED_ROWS_INVALID")
    else:
        expected = None

    row_count = 0
    rows_by_market: Counter[str] = Counter()
    rows_by_season: Counter[int] = Counter()
    rows_by_book: Counter[str] = Counter()
    season_market: Counter[tuple[int, str]] = Counter()
    season_book_market: Counter[tuple[int, str, str]] = Counter()
    keyed_rows_by_market: Counter[str] = Counter()
    side_matched_rows_by_market: Counter[str] = Counter()
    opening_line_rows_by_market: Counter[str] = Counter()
    opening_odds_rows_by_market: Counter[str] = Counter()
    unique_keyed_games_by_season: dict[int, set[str]] = defaultdict(set)
    book_seasons: dict[str, set[int]] = defaultdict(set)
    book_markets: dict[str, Counter[str]] = defaultdict(Counter)

    # Market values are retained per exact game/book only.  Sets deliberately expose
    # temporal ambiguity instead of relying on archive row order.
    spread_values: dict[tuple[int, str, str], set[float]] = defaultdict(set)
    total_values: dict[tuple[int, str, str], set[float]] = defaultdict(set)
    moneyline_home: dict[tuple[int, str, str], set[float]] = defaultdict(set)
    moneyline_away: dict[tuple[int, str, str], set[float]] = defaultdict(set)

    for raw in rows:
        if not isinstance(raw, Mapping):
            raise CFBMarketBenchmarkError("CFB_MARKET_BENCHMARK_ROW_INVALID")
        row_count += 1
        season = _season(raw.get("season"))
        market = _text(raw.get("market_type"))
        book = _text(raw.get("book"))
        if market not in _ALLOWED_MARKETS:
            raise CFBMarketBenchmarkError(f"CFB_MARKET_BENCHMARK_MARKET_INVALID:{market or 'MISSING'}")
        if not book:
            raise CFBMarketBenchmarkError("CFB_MARKET_BENCHMARK_BOOK_MISSING")

        rows_by_market[market] += 1
        rows_by_season[season] += 1
        rows_by_book[book] += 1
        season_market[(season, market)] += 1
        season_book_market[(season, book, market)] += 1
        book_seasons[book].add(season)
        book_markets[book][market] += 1
        if _text(raw.get("opening_lines")):
            opening_line_rows_by_market[market] += 1
        if _text(raw.get("opening_odds")):
            opening_odds_rows_by_market[market] += 1

        game_id = _text(raw.get("game_id"))
        fully_keyed = bool(game_id and _text(raw.get("home_team_id")) and _text(raw.get("away_team_id")))
        if fully_keyed:
            keyed_rows_by_market[market] += 1
            unique_keyed_games_by_season[season].add(game_id)
        if not game_id:
            continue

        sides = _game_sides(raw.get("game_desc"))
        if sides is None:
            continue
        away_name, home_name = sides
        abbr = _side_name(raw.get("abbr"))
        side: str | None
        if abbr == home_name:
            side = "home"
        elif abbr == away_name:
            side = "away"
        elif market == "total" and abbr in {"over", "under"}:
            side = abbr
        else:
            side = None
        if side is not None:
            side_matched_rows_by_market[market] += 1

        key = (season, game_id, book)
        if market == "spread" and side in {"home", "away"}:
            line = _number(raw.get("lines"))
            if line is not None:
                spread_values[key].add(line if side == "home" else -line)
        elif market == "total" and side in {"over", "under"}:
            line = _number(raw.get("lines"))
            if line is not None:
                total_values[key].add(line)
        elif market == "money_line" and side in {"home", "away"}:
            odds = _number(raw.get("odds"))
            if odds is not None:
                if side == "home":
                    moneyline_home[key].add(odds)
                else:
                    moneyline_away[key].add(odds)

    if row_count == 0:
        raise CFBMarketBenchmarkError("CFB_MARKET_BENCHMARK_ROWS_REQUIRED")
    if expected is not None and row_count != expected:
        raise CFBMarketBenchmarkError(
            f"CFB_MARKET_BENCHMARK_ROW_COUNT_MISMATCH:{row_count}:{expected}"
        )

    spread_by_game: dict[tuple[int, str], list[float]] = defaultdict(list)
    total_by_game: dict[tuple[int, str], list[float]] = defaultdict(list)
    ml_by_game: dict[tuple[int, str], list[float]] = defaultdict(list)
    ambiguous = Counter()

    for (season, game_id, _book), values in spread_values.items():
        if len(values) == 1:
            spread_by_game[(season, game_id)].append(next(iter(values)))
        elif len(values) > 1:
            ambiguous["spread_book_game"] += 1
    for (season, game_id, _book), values in total_values.items():
        if len(values) == 1:
            total_by_game[(season, game_id)].append(next(iter(values)))
        elif len(values) > 1:
            ambiguous["total_book_game"] += 1
    moneyline_keys = set(moneyline_home) | set(moneyline_away)
    for season, game_id, book in moneyline_keys:
        home_values = moneyline_home.get((season, game_id, book), set())
        away_values = moneyline_away.get((season, game_id, book), set())
        if len(home_values) == 1 and len(away_values) == 1:
            probability = _novig_home_probability(next(iter(home_values)), next(iter(away_values)))
            if probability is not None:
                ml_by_game[(season, game_id)].append(probability)
        elif home_values or away_values:
            ambiguous["moneyline_book_game"] += 1

    all_game_keys = set(spread_by_game) | set(total_by_game) | set(ml_by_game)
    game_references: list[dict[str, Any]] = []
    reference_counts = Counter()
    reference_counts_by_season: dict[int, Counter[str]] = defaultdict(Counter)
    for season, game_id in sorted(all_game_keys):
        spread = spread_by_game.get((season, game_id), [])
        total = total_by_game.get((season, game_id), [])
        ml = ml_by_game.get((season, game_id), [])
        row: dict[str, Any] = {"season": season, "game_id": game_id}
        if spread:
            row["home_spread_consensus"] = float(median(sorted(spread)))
            row["spread_book_count"] = len(spread)
            reference_counts["spread"] += 1
            reference_counts_by_season[season]["spread"] += 1
        if total:
            row["total_consensus"] = float(median(sorted(total)))
            row["total_book_count"] = len(total)
            reference_counts["total"] += 1
            reference_counts_by_season[season]["total"] += 1
        if ml:
            row["home_moneyline_novig_consensus"] = float(median(sorted(ml)))
            row["moneyline_book_count"] = len(ml)
            reference_counts["money_line"] += 1
            reference_counts_by_season[season]["money_line"] += 1
        game_references.append(row)

    seasons = sorted(rows_by_season)
    books = sorted(rows_by_book)
    season_profiles = [
        {
            "season": season,
            "row_count": rows_by_season[season],
            "unique_fully_keyed_games": len(unique_keyed_games_by_season.get(season, set())),
            "market_rows": {market: season_market[(season, market)] for market in sorted(_ALLOWED_MARKETS)},
            "reference_games": {
                market: reference_counts_by_season[season][market] for market in sorted(_ALLOWED_MARKETS)
            },
        }
        for season in seasons
    ]
    book_profiles = [
        {
            "book": book,
            "row_count": rows_by_book[book],
            "season_start": min(book_seasons[book]),
            "season_end": max(book_seasons[book]),
            "season_count": len(book_seasons[book]),
            "market_rows": {market: book_markets[book][market] for market in sorted(_ALLOWED_MARKETS)},
        }
        for book in books
    ]
    matrix = [
        {"season": season, "book": book, "market_type": market, "row_count": count}
        for (season, book, market), count in sorted(season_book_market.items())
    ]

    report: dict[str, Any] = {
        "schema_version": CFB_MARKET_BENCHMARK_VERSION,
        "status": "RESEARCH_ONLY_NOT_PROMOTION_EVIDENCE",
        "source_id": "CFB_HISTORICAL_MARKET_SOURCE_V1",
        "source_sha256": source_hash,
        "row_count": row_count,
        "season_start": min(seasons),
        "season_end": max(seasons),
        "season_count": len(seasons),
        "book_count": len(books),
        "rows_by_market": {market: rows_by_market[market] for market in sorted(_ALLOWED_MARKETS)},
        "keyed_rows_by_market": {market: keyed_rows_by_market[market] for market in sorted(_ALLOWED_MARKETS)},
        "side_matched_rows_by_market": {
            market: side_matched_rows_by_market[market] for market in sorted(_ALLOWED_MARKETS)
        },
        "opening_line_rows_by_market": {
            market: opening_line_rows_by_market[market] for market in sorted(_ALLOWED_MARKETS)
        },
        "opening_odds_rows_by_market": {
            market: opening_odds_rows_by_market[market] for market in sorted(_ALLOWED_MARKETS)
        },
        "reference_game_counts": {
            market: reference_counts[market] for market in sorted(_ALLOWED_MARKETS)
        },
        "ambiguous_book_game_groups": dict(sorted(ambiguous.items())),
        "season_profiles": season_profiles,
        "book_profiles": book_profiles,
        "season_book_market_rows": matrix,
        "game_references": game_references,
        "interpretation": {
            "row_order_has_temporal_semantics": False,
            "opening_fields_promoted_to_pit": False,
            "market_reference_may_rank_model_candidates": False,
            "market_reference_may_train_or_calibrate_model": False,
            "market_reference_is_research_context_only": True,
        },
        "authority": {
            "feature_authority": False,
            "model_p_authority": False,
            "candidate_selection_authority": False,
            "truth_gate_authority": False,
            "clv_authority": False,
            "promotion_authority": False,
            "staking_authority": False,
            "official_bet_authority": False,
        },
    }
    report["report_sha256"] = _canonical_hash(report)
    return report


__all__ = [
    "CFB_MARKET_BENCHMARK_VERSION",
    "CFBMarketBenchmarkError",
    "build_historical_market_benchmark",
]
