from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from typing import Any, Iterable, Mapping, Sequence

from .shared_acquisition_contract import TrustClass


@dataclass(frozen=True)
class ProviderSpec:
    sport: str
    provider_name: str
    domain: str
    priority: int
    trust_class: TrustClass
    ttl_seconds: int | None
    required_fields: tuple[str, ...] = ()
    fallback_for: tuple[str, ...] = ()
    supports_live: bool = True
    supports_history: bool = False
    notes: str | None = None

    def normalized(self) -> "ProviderSpec":
        return ProviderSpec(
            sport=self.sport.upper().strip(),
            provider_name=self.provider_name.strip(),
            domain=self.domain.upper().strip(),
            priority=int(self.priority),
            trust_class=self.trust_class,
            ttl_seconds=self.ttl_seconds,
            required_fields=tuple(str(x).strip() for x in self.required_fields),
            fallback_for=tuple(str(x).strip() for x in self.fallback_for),
            supports_live=bool(self.supports_live),
            supports_history=bool(self.supports_history),
            notes=self.notes,
        )


@dataclass(frozen=True)
class SchemaCheck:
    ok: bool
    missing_fields: tuple[str, ...]
    unexpected_fields: tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True)
class ProviderPlan:
    domain: str
    primary: ProviderSpec | None
    fallbacks: tuple[ProviderSpec, ...]


def schema_fingerprint(fields: Iterable[str]) -> str:
    normalized = sorted({str(x).strip() for x in fields if str(x).strip()})
    raw = dumps(normalized, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(raw).hexdigest()


def validate_schema(
    row: Mapping[str, Any],
    *,
    required_fields: Sequence[str],
    allowed_fields: Sequence[str] | None = None,
) -> SchemaCheck:
    present = {str(x) for x in row.keys()}
    required = {str(x) for x in required_fields}
    missing = tuple(sorted(required - present))
    unexpected: tuple[str, ...] = ()
    if allowed_fields is not None:
        allowed = {str(x) for x in allowed_fields}
        unexpected = tuple(sorted(present - allowed))
    return SchemaCheck(
        ok=not missing,
        missing_fields=missing,
        unexpected_fields=unexpected,
        fingerprint=schema_fingerprint(present),
    )


def build_provider_plans(specs: Iterable[ProviderSpec]) -> dict[str, ProviderPlan]:
    grouped: dict[str, list[ProviderSpec]] = {}
    for raw in specs:
        spec = raw.normalized()
        if spec.priority < 0:
            raise ValueError("provider priority must be non-negative")
        if spec.ttl_seconds is not None and spec.ttl_seconds < 0:
            raise ValueError("provider ttl_seconds must be non-negative")
        grouped.setdefault(spec.domain, []).append(spec)

    plans: dict[str, ProviderPlan] = {}
    for domain, rows in grouped.items():
        ordered = sorted(rows, key=lambda x: (x.priority, x.provider_name.lower()))
        plans[domain] = ProviderPlan(
            domain=domain,
            primary=ordered[0] if ordered else None,
            fallbacks=tuple(ordered[1:]),
        )
    return plans


def domains_safe_for_parallel_fetch(specs: Iterable[ProviderSpec]) -> tuple[tuple[str, ...], ...]:
    """Return independent domains that can be fetched concurrently.

    This is deliberately a planning primitive rather than a network executor so
    callers retain their existing opener/retry/fail-closed semantics. Providers
    inside the same domain remain ordered primary -> fallback; independent
    domains can fan out in parallel.
    """
    domains = sorted({s.normalized().domain for s in specs})
    return tuple((domain,) for domain in domains)


def model_p_provider_allowed(spec: ProviderSpec) -> bool:
    return spec.normalized().trust_class == TrustClass.MODEL_P_OBJECTIVE


def forbid_negative_live_cache(*, event_has_started: bool, payload_is_empty: bool) -> bool:
    """True when an empty live/current payload must not be persisted as evidence.

    Public sports-data packages have documented stale-cache failure modes when an
    empty future/current response is cached. SportsEdge should preserve the
    source failure/missing state, but not promote an empty payload to a durable
    successful cache entry.
    """
    return bool(payload_is_empty and not event_has_started)


def provider_manifest_sha(specs: Iterable[ProviderSpec]) -> str:
    rows = []
    for spec in sorted((x.normalized() for x in specs), key=lambda x: (x.sport, x.domain, x.priority, x.provider_name)):
        rows.append({
            "sport": spec.sport,
            "provider_name": spec.provider_name,
            "domain": spec.domain,
            "priority": spec.priority,
            "trust_class": spec.trust_class.value,
            "ttl_seconds": spec.ttl_seconds,
            "required_fields": spec.required_fields,
            "fallback_for": spec.fallback_for,
            "supports_live": spec.supports_live,
            "supports_history": spec.supports_history,
            "notes": spec.notes,
        })
    raw = dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return sha256(raw).hexdigest()
