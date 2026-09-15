"""Fail-closed market-provider eligibility checks.

Routing/provenance only: this module grants no model, promotion, staking, or
OFFICIAL authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

DEFAULT_CONTRACT = Path("config/market_provider_contract_v1.json")


class ProviderContractError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderAdmission:
    provider: str
    market: str
    sportsbook: str | None
    exact_book_satisfied: bool
    ttl_seconds: int


def _norm(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _aware(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ProviderContractError("SOURCE_TIMESTAMP_MISSING_WHEN_REQUIRED")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ProviderContractError("SOURCE_TIMESTAMP_TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def load_contract(path: str | Path = DEFAULT_CONTRACT) -> Mapping[str, Any]:
    payload = json.loads(Path(path).read_text())
    if payload.get("schema_version") != "MARKET_PROVIDER_CONTRACT_V1":
        raise ProviderContractError("PROVIDER_CONTRACT_SCHEMA_MISMATCH")
    if payload.get("non_silent_satisfaction") is not True:
        raise ProviderContractError("NON_SILENT_SATISFACTION_NOT_ENFORCED")
    return payload


def admit_quote(
    quote: Mapping[str, Any],
    *,
    required_book: str | None = None,
    now: datetime | None = None,
    contract_path: str | Path = DEFAULT_CONTRACT,
) -> ProviderAdmission:
    contract = load_contract(contract_path)
    provider = str(quote.get("quote_provider") or "").strip()
    market = str(quote.get("market") or "").strip().upper()
    rules = {str(row.get("provider")): row for row in contract.get("rules") or []}
    rule = rules.get(provider)
    if rule is None:
        raise ProviderContractError("SOURCE_PROVIDER_UNREGISTERED")
    if market not in {str(x).upper() for x in rule.get("markets") or []}:
        raise ProviderContractError("SOURCE_DOES_NOT_COVER_MARKET")

    freshness = rule.get("freshness") or {}
    ttl = int(freshness.get("ttl_seconds") or 0)
    if ttl <= 0:
        raise ProviderContractError("SOURCE_TTL_INVALID")
    current = _aware(now or datetime.now(timezone.utc))
    if freshness.get("timestamp_required"):
        source_time = _aware(quote.get("source_updated_at") or quote.get("provider_last_update"))
        age = (current - source_time).total_seconds()
        if age < 0:
            raise ProviderContractError("SOURCE_TIMESTAMP_AFTER_FETCH")
        if age > ttl:
            raise ProviderContractError("SOURCE_TIMESTAMP_STALE")

    sportsbook = str(quote.get("sportsbook") or "").strip() or None
    exact = False
    if required_book:
        if not sportsbook or _norm(sportsbook) != _norm(required_book):
            raise ProviderContractError("SOURCE_BOOK_IDENTITY_MISSING_FOR_EXACT_BOOK_CONTRACT")
        # Exact-book admission is based on this source's own sportsbook field;
        # it never inherits the identity of a failed-over primary provider.
        exact = True

    return ProviderAdmission(provider, market, sportsbook, exact, ttl)
