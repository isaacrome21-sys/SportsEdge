from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class FreshnessStatus(str, Enum):
    LIVE = "LIVE"
    RECENT = "RECENT"
    STALE = "STALE"
    MISSING = "MISSING"
    SOURCE_FAILED = "SOURCE_FAILED"
    FRESHNESS_UNVERIFIED = "FRESHNESS_UNVERIFIED"


class ConfirmationStatus(str, Enum):
    OFFICIAL = "OFFICIAL"
    VERIFIED = "VERIFIED"
    REPORTED = "REPORTED"
    UNCONFIRMED = "UNCONFIRMED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TrustClass(str, Enum):
    MODEL_P_OBJECTIVE = "MODEL_P_OBJECTIVE"
    CONTEXT_ONLY = "CONTEXT_ONLY"
    MARKET_ONLY = "MARKET_ONLY"
    UNTRUSTED = "UNTRUSTED"


@dataclass(frozen=True)
class AcquisitionDatum:
    sport: str
    scope_type: str
    scope_id: str
    field_name: str
    value: Any
    source_name: str
    source_uri: str
    observed_at_utc: str | None
    retrieved_at_utc: str
    freshness_status: FreshnessStatus
    confirmation_status: ConfirmationStatus
    trust_class: TrustClass
    source_sha256: str | None = None
    ttl_seconds: int | None = None
    manual_fill: bool = False
    required_for_evaluation: bool = True
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc(value: str | datetime | None, *, required: bool) -> datetime | None:
    if value is None:
        if required:
            raise ValueError("timestamp required")
        return None
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        if not text:
            if required:
                raise ValueError("timestamp required")
            return None
        out = datetime.fromisoformat(text)
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return out.astimezone(timezone.utc)


def classify_freshness(*, observed_at: str | datetime | None,
                       retrieved_at: str | datetime, ttl_seconds: int | None,
                       source_failed: bool = False, missing: bool = False) -> FreshnessStatus:
    if source_failed:
        return FreshnessStatus.SOURCE_FAILED
    if missing:
        return FreshnessStatus.MISSING
    retrieved = _utc(retrieved_at, required=True)
    observed = _utc(observed_at, required=False)
    if observed is None:
        return FreshnessStatus.FRESHNESS_UNVERIFIED
    if observed > retrieved:
        raise ValueError("observed_at cannot be after retrieved_at")
    if ttl_seconds is None:
        return FreshnessStatus.RECENT
    if ttl_seconds < 0:
        raise ValueError("ttl_seconds must be non-negative")
    age = (retrieved - observed).total_seconds()
    if age <= ttl_seconds * 0.25:
        return FreshnessStatus.LIVE
    if age <= ttl_seconds:
        return FreshnessStatus.RECENT
    return FreshnessStatus.STALE


def build_datum(*, sport: str, scope_type: str, scope_id: str, field_name: str,
                value: Any, source_name: str, source_uri: str,
                retrieved_at: str | datetime, observed_at: str | datetime | None = None,
                ttl_seconds: int | None = None,
                confirmation_status: ConfirmationStatus = ConfirmationStatus.NOT_APPLICABLE,
                trust_class: TrustClass = TrustClass.CONTEXT_ONLY,
                source_sha256: str | None = None, manual_fill: bool = False,
                required_for_evaluation: bool = True,
                source_failed: bool = False, missing: bool = False,
                note: str | None = None) -> AcquisitionDatum:
    retrieved = _utc(retrieved_at, required=True)
    observed = _utc(observed_at, required=False)
    freshness = classify_freshness(
        observed_at=observed,
        retrieved_at=retrieved,
        ttl_seconds=ttl_seconds,
        source_failed=source_failed,
        missing=missing,
    )
    if manual_fill and observed is None and freshness not in {
        FreshnessStatus.MISSING, FreshnessStatus.SOURCE_FAILED
    }:
        freshness = FreshnessStatus.FRESHNESS_UNVERIFIED
    if trust_class == TrustClass.MODEL_P_OBJECTIVE and freshness in {
        FreshnessStatus.STALE,
        FreshnessStatus.MISSING,
        FreshnessStatus.SOURCE_FAILED,
        FreshnessStatus.FRESHNESS_UNVERIFIED,
    }:
        trust_class = TrustClass.CONTEXT_ONLY
    return AcquisitionDatum(
        sport=str(sport).upper().strip(),
        scope_type=str(scope_type).upper().strip(),
        scope_id=str(scope_id).strip(),
        field_name=str(field_name).strip(),
        value=value,
        source_name=str(source_name).strip(),
        source_uri=str(source_uri).strip(),
        observed_at_utc=None if observed is None else observed.isoformat(),
        retrieved_at_utc=retrieved.isoformat(),
        freshness_status=freshness,
        confirmation_status=confirmation_status,
        trust_class=trust_class,
        source_sha256=source_sha256,
        ttl_seconds=ttl_seconds,
        manual_fill=bool(manual_fill),
        required_for_evaluation=bool(required_for_evaluation),
        note=note,
    )


def scoped_blockers(rows: list[AcquisitionDatum]) -> dict[tuple[str, str], list[str]]:
    """Return blockers keyed to the narrowest affected scope.

    Only evidence explicitly required for evaluation can block. Optional context may
    be stale/missing and remain visible in provenance without suppressing a market.
    A missing player-prop quote blocks that player/market scope, not an unrelated
    game or the full slate. Shared dependencies should be emitted with a shared
    scope_id by the caller when they truly affect multiple markets.
    """
    blocked: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        if not row.required_for_evaluation:
            continue
        if row.freshness_status in {
            FreshnessStatus.STALE,
            FreshnessStatus.MISSING,
            FreshnessStatus.SOURCE_FAILED,
            FreshnessStatus.FRESHNESS_UNVERIFIED,
        }:
            blocked.setdefault((row.scope_type, row.scope_id), []).append(row.field_name)
    return blocked


def delta_changed(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
    keys = set(previous) | set(current)
    return {key: (previous.get(key), current.get(key)) for key in keys if previous.get(key) != current.get(key)}
