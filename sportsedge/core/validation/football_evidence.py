"""Fail-closed evidence contract for real football model validation.

This layer exists to prevent fixture/synthetic acceptance tests from being
mistaken for predictive validation.  It consumes already-computed per-season,
per-market M1/M2 log-loss rows and produces promotion evidence summaries.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Iterable


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_ALLOWED_SPORTS = {"nfl", "cfb"}


@dataclass(frozen=True)
class FootballValidationBundle:
    sport: str
    provenance: str
    source_uri: str
    source_sha256: str
    rows: list[dict]


@dataclass(frozen=True)
class MarketValidationEvidence:
    sport: str
    market: str
    fold_wins: int
    fold_total: int
    fold_win_rate: float
    mean_m1_log_loss: float
    mean_m2_log_loss: float
    seasons: tuple[int, ...]
    source_uri: str
    source_sha256: str


@dataclass(frozen=True)
class ValidatedFootballHistory:
    bundle: FootballValidationBundle
    seasons: tuple[int, ...]
    markets: tuple[str, ...]


def _finite(value: object, *, name: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}_NOT_NUMERIC") from exc
    if not math.isfinite(x):
        raise ValueError(f"{name}_NONFINITE")
    return x


def validate_real_history_bundle(bundle: FootballValidationBundle) -> ValidatedFootballHistory:
    sport = str(bundle.sport).strip().lower()
    if sport not in _ALLOWED_SPORTS:
        raise ValueError("UNSUPPORTED_FOOTBALL_SPORT")
    if str(bundle.provenance).strip().lower() != "real":
        raise ValueError("REAL_HISTORY_REQUIRED")
    if not str(bundle.source_uri).strip():
        raise ValueError("SOURCE_URI_REQUIRED")
    if not _SHA256_RE.fullmatch(str(bundle.source_sha256).strip()):
        raise ValueError("SOURCE_SHA256_REQUIRED")
    if not isinstance(bundle.rows, list) or not bundle.rows:
        raise ValueError("VALIDATION_ROWS_REQUIRED")

    seasons: set[int] = set()
    markets: set[str] = set()
    seen: set[tuple[int, str]] = set()
    for row in bundle.rows:
        if not isinstance(row, dict):
            raise ValueError("VALIDATION_ROW_NOT_OBJECT")
        try:
            season = int(row["season"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("SEASON_REQUIRED") from exc
        market = str(row.get("market", "")).strip().lower()
        if not market:
            raise ValueError("MARKET_REQUIRED")
        m1 = _finite(row.get("m1_log_loss"), name="M1_LOG_LOSS")
        m2 = _finite(row.get("m2_log_loss"), name="M2_LOG_LOSS")
        if m1 < 0 or m2 < 0:
            raise ValueError("LOG_LOSS_NEGATIVE")
        key = (season, market)
        if key in seen:
            raise ValueError("DUPLICATE_SEASON_MARKET_FOLD")
        seen.add(key)
        seasons.add(season)
        markets.add(market)

    if len(seasons) < 2:
        raise ValueError("INSUFFICIENT_WALKFORWARD_SEASONS")

    return ValidatedFootballHistory(
        bundle=FootballValidationBundle(
            sport=sport,
            provenance="real",
            source_uri=str(bundle.source_uri).strip(),
            source_sha256=str(bundle.source_sha256).lower(),
            rows=list(bundle.rows),
        ),
        seasons=tuple(sorted(seasons)),
        markets=tuple(sorted(markets)),
    )


def build_promotion_evidence(validated: ValidatedFootballHistory) -> dict[str, MarketValidationEvidence]:
    out: dict[str, MarketValidationEvidence] = {}
    rows = validated.bundle.rows
    for market in validated.markets:
        market_rows = [r for r in rows if str(r["market"]).strip().lower() == market]
        market_rows.sort(key=lambda r: int(r["season"]))
        if not market_rows:
            continue
        wins = sum(float(r["m2_log_loss"]) < float(r["m1_log_loss"]) for r in market_rows)
        total = len(market_rows)
        seasons = tuple(int(r["season"]) for r in market_rows)
        out[market] = MarketValidationEvidence(
            sport=validated.bundle.sport,
            market=market,
            fold_wins=wins,
            fold_total=total,
            fold_win_rate=wins / total,
            mean_m1_log_loss=sum(float(r["m1_log_loss"]) for r in market_rows) / total,
            mean_m2_log_loss=sum(float(r["m2_log_loss"]) for r in market_rows) / total,
            seasons=seasons,
            source_uri=validated.bundle.source_uri,
            source_sha256=validated.bundle.source_sha256,
        )
    return out
