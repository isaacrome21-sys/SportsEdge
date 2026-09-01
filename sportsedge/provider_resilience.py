from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from typing import Any, Callable, Iterable, Mapping, Sequence

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


@dataclass(frozen=True)
class ProviderAttempt:
    provider_name: str
    status: str
    detail: str | None = None
    schema_fingerprint: str | None = None


@dataclass(frozen=True)
class ProviderOutcome:
    domain: str
    status: str
    provider_name: str | None
    payload: Any
    attempts: tuple[ProviderAttempt, ...]


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
    domains = sorted({s.normalized().domain for s in specs})
    return tuple((domain,) for domain in domains)


def model_p_provider_allowed(spec: ProviderSpec) -> bool:
    return spec.normalized().trust_class == TrustClass.MODEL_P_OBJECTIVE


def forbid_negative_live_cache(*, event_has_started: bool, payload_is_empty: bool) -> bool:
    return bool(payload_is_empty and not event_has_started)


def _ordered_specs(plan: ProviderPlan) -> tuple[ProviderSpec, ...]:
    return tuple(x for x in ((plan.primary,) + plan.fallbacks) if x is not None)


def execute_provider_plan(
    plan: ProviderPlan,
    fetchers: Mapping[str, Callable[[], Any]],
    *,
    require_model_p_objective: bool = False,
) -> ProviderOutcome:
    """Execute one domain primary -> fallback without weakening trust or schema rules."""
    attempts: list[ProviderAttempt] = []
    saw_transport_failure = False
    for spec in _ordered_specs(plan):
        if require_model_p_objective and not model_p_provider_allowed(spec):
            attempts.append(ProviderAttempt(spec.provider_name, "REJECTED_TRUST"))
            continue
        fetcher = fetchers.get(spec.provider_name)
        if fetcher is None:
            attempts.append(ProviderAttempt(spec.provider_name, "MISSING_FETCHER"))
            continue
        try:
            payload = fetcher()
        except Exception as exc:
            saw_transport_failure = True
            attempts.append(ProviderAttempt(spec.provider_name, "SOURCE_FAILED", type(exc).__name__))
            continue
        if payload is None:
            attempts.append(ProviderAttempt(spec.provider_name, "MISSING"))
            continue
        if spec.required_fields:
            if not isinstance(payload, Mapping):
                attempts.append(ProviderAttempt(spec.provider_name, "SCHEMA_FAILED", "payload-not-mapping"))
                continue
            check = validate_schema(payload, required_fields=spec.required_fields)
            if not check.ok:
                attempts.append(ProviderAttempt(
                    spec.provider_name,
                    "SCHEMA_FAILED",
                    ",".join(check.missing_fields),
                    check.fingerprint,
                ))
                continue
            attempts.append(ProviderAttempt(spec.provider_name, "AVAILABLE", schema_fingerprint=check.fingerprint))
        else:
            attempts.append(ProviderAttempt(spec.provider_name, "AVAILABLE"))
        return ProviderOutcome(plan.domain, "AVAILABLE", spec.provider_name, payload, tuple(attempts))

    status = "SOURCE_FAILED" if saw_transport_failure else "MISSING"
    return ProviderOutcome(plan.domain, status, None, None, tuple(attempts))


def acquire_domains_concurrently(
    plans: Mapping[str, ProviderPlan],
    fetchers_by_domain: Mapping[str, Mapping[str, Callable[[], Any]]],
    *,
    model_p_domains: Iterable[str] = (),
    max_workers: int = 8,
) -> dict[str, ProviderOutcome]:
    """Fan out independent domains concurrently; preserve ordered fallbacks inside each domain."""
    if isinstance(max_workers, bool) or int(max_workers) < 1:
        raise ValueError("max_workers must be positive")
    required = {str(x).upper().strip() for x in model_p_domains}
    unknown = required - set(plans)
    if unknown:
        raise ValueError(f"unknown model_p_domains: {sorted(unknown)}")
    if not plans:
        return {}
    workers = min(int(max_workers), len(plans))
    outcomes: dict[str, ProviderOutcome] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                execute_provider_plan,
                plan,
                fetchers_by_domain.get(domain, {}),
                require_model_p_objective=domain in required,
            ): domain
            for domain, plan in plans.items()
        }
        for future in as_completed(futures):
            domain = futures[future]
            outcomes[domain] = future.result()
    return {domain: outcomes[domain] for domain in sorted(outcomes)}


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
