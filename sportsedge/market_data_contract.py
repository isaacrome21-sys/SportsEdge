"""Provider-neutral market-data contracts for SportsEdge.

Market prices and public-betting context are execution/context inputs only. They
must never be consumed as predictive Model_P features.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping


class MarketDataContractError(ValueError):
    pass


def canonical_json_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return sha256(raw).hexdigest()


def require_aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise MarketDataContractError(f"{field}_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class MarketQuote:
    provider: str
    book: str
    sport_key: str
    provider_event_id: str
    market: str
    selection: str
    american_odds: int
    captured_at: datetime
    provider_updated_at: datetime
    raw_payload_sha256: str
    point: float | None = None
    home_team: str | None = None
    away_team: str | None = None
    commence_time: datetime | None = None
    in_play: bool = False

    def __post_init__(self) -> None:
        for field_name in ("provider", "book", "sport_key", "provider_event_id", "market", "selection"):
            if not str(getattr(self, field_name)).strip():
                raise MarketDataContractError(f"{field_name.upper()}_REQUIRED")
        if int(self.american_odds) == 0:
            raise MarketDataContractError("AMERICAN_ODDS_INVALID")
        object.__setattr__(self, "captured_at", require_aware_utc(self.captured_at, field="CAPTURED_AT"))
        object.__setattr__(self, "provider_updated_at", require_aware_utc(self.provider_updated_at, field="PROVIDER_UPDATED_AT"))
        if self.commence_time is not None:
            object.__setattr__(self, "commence_time", require_aware_utc(self.commence_time, field="COMMENCE_TIME"))
        if len(self.raw_payload_sha256) != 64:
            raise MarketDataContractError("RAW_PAYLOAD_SHA256_INVALID")

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "book": self.book,
            "sport_key": self.sport_key,
            "provider_event_id": self.provider_event_id,
            "market": self.market,
            "selection": self.selection,
            "american_odds": int(self.american_odds),
            "point": self.point,
            "captured_at": self.captured_at.isoformat(),
            "provider_updated_at": self.provider_updated_at.isoformat(),
            "raw_payload_sha256": self.raw_payload_sha256,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "commence_time": self.commence_time.isoformat() if self.commence_time else None,
            "in_play": bool(self.in_play),
            "model_p_feature_authority": False,
            "market_binding_authority": True,
        }


@dataclass(frozen=True)
class PublicBettingSplit:
    source: str
    sport_key: str
    event_key: str
    market: str
    selection: str
    ticket_percent: float | None
    money_percent: float | None
    captured_at: datetime
    source_updated_at: datetime | None = None
    raw_payload_sha256: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("source", "sport_key", "event_key", "market", "selection"):
            if not str(getattr(self, field_name)).strip():
                raise MarketDataContractError(f"{field_name.upper()}_REQUIRED")
        object.__setattr__(self, "captured_at", require_aware_utc(self.captured_at, field="CAPTURED_AT"))
        if self.source_updated_at is not None:
            object.__setattr__(self, "source_updated_at", require_aware_utc(self.source_updated_at, field="SOURCE_UPDATED_AT"))
        for name in ("ticket_percent", "money_percent"):
            value = getattr(self, name)
            if value is not None and not (0.0 <= float(value) <= 100.0):
                raise MarketDataContractError(f"{name.upper()}_OUT_OF_RANGE")
        if self.ticket_percent is None and self.money_percent is None:
            raise MarketDataContractError("PUBLIC_BETTING_SPLIT_EMPTY")
        if self.raw_payload_sha256 is not None and len(self.raw_payload_sha256) != 64:
            raise MarketDataContractError("RAW_PAYLOAD_SHA256_INVALID")

    @property
    def money_ticket_divergence(self) -> float | None:
        if self.ticket_percent is None or self.money_percent is None:
            return None
        return float(self.money_percent) - float(self.ticket_percent)

    def as_context_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "sport_key": self.sport_key,
            "event_key": self.event_key,
            "market": self.market,
            "selection": self.selection,
            "ticket_percent": self.ticket_percent,
            "money_percent": self.money_percent,
            "money_ticket_divergence": self.money_ticket_divergence,
            "captured_at": self.captured_at.isoformat(),
            "source_updated_at": self.source_updated_at.isoformat() if self.source_updated_at else None,
            "raw_payload_sha256": self.raw_payload_sha256,
            "model_p_feature_authority": False,
            "promotion_authority": False,
            "context_only": True,
        }


def stamp_raw_payload(row: Mapping[str, Any], raw_payload: Any) -> dict[str, Any]:
    return {**dict(row), "raw_payload_sha256": canonical_json_sha256(raw_payload)}
