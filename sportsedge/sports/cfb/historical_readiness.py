"""Historical-data readiness checks for CFB walk-forward and Truth Gate replay.

This module does not certify model skill. It only answers whether the historical data
can support a legitimate chronological replay under the v1.2 contracts. Closing-only
archives remain explicitly insufficient for CLV certification.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .historical_market import HistoricalMarketArchive, HistoricalQuote


REQUIRED_MARKETS = ("MONEYLINE", "SPREAD", "TOTAL")


class CFBHistoricalReadinessError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise CFBHistoricalReadinessError(f"{field}:TIMESTAMP_REQUIRED")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBHistoricalReadinessError(f"{field}:ISO8601_REQUIRED") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CFBHistoricalReadinessError(f"{field}:TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def _complementary(market: str, sides: set[str]) -> bool:
    expected = {"HOME", "AWAY"} if market in {"MONEYLINE", "SPREAD"} else {"OVER", "UNDER"}
    return sides == expected


def _paired_snapshots(quotes: Iterable[HistoricalQuote]) -> dict[tuple[str, int, str, str, float | None], dict[str, list[str]]]:
    """Return exact-contract paths with synchronized decision and closing snapshots."""

    by_snapshot: dict[tuple[str, int, str, str, float | None, str], list[HistoricalQuote]] = {}
    for quote in quotes:
        q = quote.validate()
        by_snapshot.setdefault(
            (q.game_id, q.season, q.market, q.book, q.line, q.captured_ts), []
        ).append(q)

    paths: dict[tuple[str, int, str, str, float | None], dict[str, list[str]]] = {}
    for (game_id, season, market, book, line, captured_ts), rows in by_snapshot.items():
        if len(rows) != 2 or not _complementary(market, {row.side for row in rows}):
            continue
        bucket = paths.setdefault((game_id, season, market, book, line), {"decision": [], "close": []})
        if all(row.is_closing for row in rows):
            bucket["close"].append(captured_ts)
        elif not any(row.is_closing for row in rows):
            bucket["decision"].append(captured_ts)
    return paths


@dataclass(frozen=True)
class CFBHistoricalReadinessReport:
    required_seasons: tuple[int, ...]
    feature_seasons_present: tuple[int, ...]
    feature_games_by_season: Mapping[int, int]
    pit_feature_rows: int
    invalid_pit_feature_rows: int
    paired_contract_paths_by_market: Mapping[str, int]
    paired_contract_seasons_by_market: Mapping[str, tuple[int, ...]]
    closing_only_archive: bool
    walk_forward_ready: bool
    clv_replay_ready: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["feature_games_by_season"] = {str(k): int(v) for k, v in self.feature_games_by_season.items()}
        payload["paired_contract_paths_by_market"] = dict(self.paired_contract_paths_by_market)
        payload["paired_contract_seasons_by_market"] = {
            key: list(value) for key, value in self.paired_contract_seasons_by_market.items()
        }
        return payload


def assess_cfb_historical_readiness(
    feature_rows: Iterable[Mapping[str, Any]],
    market_archive: HistoricalMarketArchive,
    *,
    required_seasons: Iterable[int],
    required_feature_contract: str = "CFB_JOINT_GAME_FEATURES_V2",
) -> CFBHistoricalReadinessReport:
    """Fail loudly on missing PIT seasons or missing decision->close paired paths.

    Feature rows are expected to be finalized game-level PIT rows. A row is considered
    PIT-valid only when its feature timestamp is strictly before kickoff and it declares
    the expected feature contract. Source-level leakage still must be attested separately.
    """

    seasons_required = tuple(sorted({int(x) for x in required_seasons}))
    if len(seasons_required) < 4:
        raise CFBHistoricalReadinessError("READINESS_REQUIRES_AT_LEAST_FOUR_FORWARD_SEASONS")
    rows = [dict(row) for row in feature_rows]
    valid_rows: list[dict[str, Any]] = []
    invalid = 0
    for row in rows:
        try:
            season = int(row.get("season"))
            game_id = str(row.get("game_id") or "").strip()
            if not game_id:
                raise ValueError("game_id")
            if str(row.get("feature_contract") or "") != required_feature_contract:
                raise ValueError("feature_contract")
            feature_ts = _utc(row.get("feature_asof_ts"), "feature_asof_ts")
            game_ts = _utc(row.get("game_start_ts"), "game_start_ts")
            if feature_ts >= game_ts:
                raise ValueError("feature_after_kick")
            if season not in seasons_required:
                continue
            valid_rows.append(row)
        except Exception:
            invalid += 1

    feature_games_by_season = {
        season: len({str(row.get("game_id")) for row in valid_rows if int(row.get("season")) == season})
        for season in seasons_required
    }
    feature_seasons_present = tuple(sorted(season for season, count in feature_games_by_season.items() if count > 0))

    archive = market_archive.validate()
    paths = _paired_snapshots(archive.quotes)
    paired_counts: dict[str, int] = {}
    paired_seasons: dict[str, tuple[int, ...]] = {}
    for market in REQUIRED_MARKETS:
        qualifying = [
            (key, value) for key, value in paths.items()
            if key[2] == market and value["decision"] and value["close"] and key[1] in seasons_required
        ]
        paired_counts[market] = len(qualifying)
        paired_seasons[market] = tuple(sorted({key[1] for key, _ in qualifying}))

    blockers: list[str] = []
    missing_feature_seasons = sorted(set(seasons_required) - set(feature_seasons_present))
    if missing_feature_seasons:
        blockers.append("PIT_FEATURE_SEASONS_MISSING:" + ",".join(map(str, missing_feature_seasons)))
    if invalid:
        blockers.append(f"INVALID_PIT_FEATURE_ROWS:{invalid}")
    for market in REQUIRED_MARKETS:
        missing_market_seasons = sorted(set(seasons_required) - set(paired_seasons[market]))
        if missing_market_seasons:
            blockers.append(
                f"{market}:PAIRED_DECISION_CLOSE_SEASONS_MISSING:" + ",".join(map(str, missing_market_seasons))
            )
    if not archive.has_intraday_path:
        blockers.append("MARKET_ARCHIVE_CLOSING_ONLY_OR_NO_INTRADAY_PATH")
    if not archive.has_two_sided_prices:
        blockers.append("MARKET_ARCHIVE_TWO_SIDED_PRICES_MISSING")

    walk_forward_ready = not missing_feature_seasons and invalid == 0
    clv_replay_ready = walk_forward_ready and all(
        set(seasons_required).issubset(set(paired_seasons[market])) for market in REQUIRED_MARKETS
    ) and archive.clv_capable
    return CFBHistoricalReadinessReport(
        required_seasons=seasons_required,
        feature_seasons_present=feature_seasons_present,
        feature_games_by_season=feature_games_by_season,
        pit_feature_rows=len(valid_rows),
        invalid_pit_feature_rows=invalid,
        paired_contract_paths_by_market=paired_counts,
        paired_contract_seasons_by_market=paired_seasons,
        closing_only_archive=not archive.has_intraday_path,
        walk_forward_ready=walk_forward_ready,
        clv_replay_ready=clv_replay_ready,
        blockers=tuple(blockers),
    )
