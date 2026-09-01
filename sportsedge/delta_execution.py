from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from typing import Any, Callable, Iterable, Mapping, Sequence

from .shared_acquisition_contract import AcquisitionDatum, FreshnessStatus, TrustClass


class DeltaExecutionError(ValueError):
    pass


DependencyKey = tuple[str, str, str]


def datum_key(row: AcquisitionDatum) -> DependencyKey:
    return (str(row.scope_type).upper(), str(row.scope_id), str(row.field_name))


def _stable(value: Any) -> Any:
    if isinstance(value, AcquisitionDatum):
        return asdict(value)
    if isinstance(value, Mapping):
        return {str(k): _stable(v) for k, v in sorted(value.items(), key=lambda x: str(x[0]))}
    if isinstance(value, (list, tuple)):
        return [_stable(v) for v in value]
    if isinstance(value, set):
        return sorted(_stable(v) for v in value)
    if hasattr(value, "value") and type(value).__module__ == "enum":
        return value.value
    return value


def dependency_fingerprint(rows: Iterable[AcquisitionDatum], keys: Iterable[DependencyKey]) -> str:
    """Hash dependency evidence including provenance/freshness, not value alone.

    A source/timestamp/freshness change invalidates reuse even when the normalized
    value happens to be unchanged. This is intentional: a formerly fresh value
    becoming stale must not inherit a prior simulation cache merely because its
    numeric value is identical.
    """
    wanted = set(keys)
    indexed = {datum_key(row): row for row in rows}
    payload = []
    for key in sorted(wanted):
        row = indexed.get(key)
        payload.append({"key": key, "datum": None if row is None else _stable(row)})
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class MarketDependency:
    market_id: str
    sport: str
    game_id: str
    entity_ids: tuple[str, ...] = ()
    model_keys: tuple[DependencyKey, ...] = ()
    simulation_keys: tuple[DependencyKey, ...] = ()
    pricing_keys: tuple[DependencyKey, ...] = ()
    correlation_groups: tuple[str, ...] = ()
    enabled: bool = True

    def validate(self) -> "MarketDependency":
        if not str(self.market_id).strip():
            raise DeltaExecutionError("market_id required")
        if not str(self.sport).strip() or not str(self.game_id).strip():
            raise DeltaExecutionError("sport/game_id required")
        overlap = set(self.model_keys) & set(self.pricing_keys)
        if overlap:
            raise DeltaExecutionError(
                "market dependency cannot classify the same field as Model_P and pricing-only: "
                + repr(sorted(overlap))
            )
        return self


@dataclass(frozen=True)
class DeltaChange:
    key: DependencyKey
    previous: AcquisitionDatum | None
    current: AcquisitionDatum | None
    reason: str


@dataclass(frozen=True)
class DeltaRerunPlan:
    run_id: str
    changed: tuple[DeltaChange, ...]
    model_p_market_ids: tuple[str, ...]
    monte_carlo_market_ids: tuple[str, ...]
    pricing_market_ids: tuple[str, ...]
    reusable_simulation_market_ids: tuple[str, ...]
    blocked_market_ids: tuple[str, ...]
    portfolio_refresh: bool
    affected_correlation_groups: tuple[str, ...]
    reasons_by_market: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def has_work(self) -> bool:
        return bool(
            self.changed or self.model_p_market_ids or self.monte_carlo_market_ids
            or self.pricing_market_ids or self.blocked_market_ids
        )


def _index(rows: Iterable[AcquisitionDatum]) -> dict[DependencyKey, AcquisitionDatum]:
    out: dict[DependencyKey, AcquisitionDatum] = {}
    for row in rows:
        key = datum_key(row)
        if key in out and out[key] != row:
            raise DeltaExecutionError(f"duplicate acquisition dependency:{key}")
        out[key] = row
    return out


def _material_signature(row: AcquisitionDatum | None) -> Any:
    if row is None:
        return None
    # Include provenance/freshness/confirmation. A retrieved_at-only change does not
    # invalidate by itself if the underlying observation/provenance/trust is identical;
    # this avoids rerunning every market merely because a cached datum was re-read.
    return {
        "value": _stable(row.value),
        "source_name": row.source_name,
        "source_uri": row.source_uri,
        "observed_at_utc": row.observed_at_utc,
        "freshness_status": row.freshness_status.value,
        "confirmation_status": row.confirmation_status.value,
        "trust_class": row.trust_class.value,
        "source_sha256": row.source_sha256,
        "ttl_seconds": row.ttl_seconds,
        "manual_fill": row.manual_fill,
        "required_for_evaluation": row.required_for_evaluation,
    }


def detect_delta(previous: Iterable[AcquisitionDatum], current: Iterable[AcquisitionDatum]) -> tuple[DeltaChange, ...]:
    before, after = _index(previous), _index(current)
    changes: list[DeltaChange] = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if _material_signature(old) == _material_signature(new):
            continue
        if old is None:
            reason = "DEPENDENCY_ADDED"
        elif new is None:
            reason = "DEPENDENCY_REMOVED"
        elif old.value != new.value:
            reason = "VALUE_CHANGED"
        elif old.freshness_status != new.freshness_status:
            reason = "FRESHNESS_CHANGED"
        elif old.trust_class != new.trust_class:
            reason = "TRUST_CHANGED"
        elif old.source_sha256 != new.source_sha256 or old.source_uri != new.source_uri:
            reason = "PROVENANCE_CHANGED"
        elif old.confirmation_status != new.confirmation_status:
            reason = "CONFIRMATION_CHANGED"
        else:
            reason = "DEPENDENCY_METADATA_CHANGED"
        changes.append(DeltaChange(key=key, previous=old, current=new, reason=reason))
    return tuple(changes)


def _unsafe(row: AcquisitionDatum | None) -> bool:
    return row is None or row.freshness_status in {
        FreshnessStatus.STALE,
        FreshnessStatus.MISSING,
        FreshnessStatus.SOURCE_FAILED,
        FreshnessStatus.FRESHNESS_UNVERIFIED,
    }


def _market_required_keys(dep: MarketDependency) -> set[DependencyKey]:
    return set(dep.model_keys) | set(dep.simulation_keys) | set(dep.pricing_keys)


def plan_delta_rerun(
    *,
    run_id: str,
    previous: Iterable[AcquisitionDatum],
    current: Iterable[AcquisitionDatum],
    dependencies: Sequence[MarketDependency],
    shared_critical_keys: Iterable[DependencyKey] = (),
) -> DeltaRerunPlan:
    """Build a minimal rerun plan from objective/market dependency changes.

    Rules:
    - pricing-only / MARKET_ONLY changes never trigger Model_P or Monte Carlo;
    - objective Model_P input changes trigger Model_P -> MC -> pricing;
    - simulation-only objective changes trigger MC -> pricing, not Model_P;
    - unsafe required evidence blocks only dependent markets;
    - shared-critical changes invalidate every enabled market;
    - any repricing refreshes portfolio/correlation exposure globally.
    """
    if not str(run_id).strip():
        raise DeltaExecutionError("run_id required")
    deps = [dep.validate() for dep in dependencies if dep.enabled]
    if len({dep.market_id for dep in deps}) != len(deps):
        raise DeltaExecutionError("duplicate market_id dependency")
    before_rows, current_rows = list(previous), list(current)
    current_index = _index(current_rows)
    changed = detect_delta(before_rows, current_rows)
    changed_keys = {change.key for change in changed}
    shared_changed = changed_keys & set(shared_critical_keys)

    model: set[str] = set()
    mc: set[str] = set()
    pricing: set[str] = set()
    blocked: set[str] = set()
    reasons: dict[str, list[str]] = {}
    groups: set[str] = set()

    for dep in deps:
        required = _market_required_keys(dep)
        unsafe = [key for key in required if _unsafe(current_index.get(key)) and (
            current_index.get(key) is None or current_index[key].required_for_evaluation
        )]
        if unsafe:
            blocked.add(dep.market_id)
            reasons.setdefault(dep.market_id, []).append(
                "REQUIRED_DEPENDENCY_UNSAFE:" + ",".join("/".join(key) for key in sorted(unsafe))
            )
            groups.update(dep.correlation_groups)
            continue

        relevant = changed_keys & required
        if shared_changed:
            # A genuinely shared critical objective dependency must invalidate the
            # full predictive path. Callers should not classify quotes as shared critical.
            model.add(dep.market_id); mc.add(dep.market_id); pricing.add(dep.market_id)
            reasons.setdefault(dep.market_id, []).append("SHARED_CRITICAL_DEPENDENCY_CHANGED")
            groups.update(dep.correlation_groups)
            continue
        if not relevant:
            continue

        model_relevant = relevant & set(dep.model_keys)
        sim_relevant = relevant & set(dep.simulation_keys)
        price_relevant = relevant & set(dep.pricing_keys)

        if model_relevant:
            # MARKET_ONLY must never feed upstream even if a caller mistakenly lists
            # such a key under model_keys. Fail closed on the classification error.
            for key in model_relevant:
                row = current_index.get(key)
                if row is not None and row.trust_class == TrustClass.MARKET_ONLY:
                    raise DeltaExecutionError(f"MARKET_ONLY dependency leaked into Model_P:{key}")
            model.add(dep.market_id); mc.add(dep.market_id); pricing.add(dep.market_id)
            reasons.setdefault(dep.market_id, []).append("MODEL_INPUT_CHANGED")
        elif sim_relevant:
            for key in sim_relevant:
                row = current_index.get(key)
                if row is not None and row.trust_class == TrustClass.MARKET_ONLY:
                    raise DeltaExecutionError(f"MARKET_ONLY dependency leaked into simulation:{key}")
            mc.add(dep.market_id); pricing.add(dep.market_id)
            reasons.setdefault(dep.market_id, []).append("SIMULATION_INPUT_CHANGED")
        elif price_relevant:
            pricing.add(dep.market_id)
            reasons.setdefault(dep.market_id, []).append("MARKET_PRICE_CHANGED")
        groups.update(dep.correlation_groups)

    all_ids = {dep.market_id for dep in deps}
    reusable = all_ids - model - mc - blocked
    refresh = bool(model or mc or pricing or blocked)
    # Portfolio sizing sees the full slate whenever any candidate can change. Correlation
    # groups identify where the change originated, but sizing is intentionally global.
    return DeltaRerunPlan(
        run_id=str(run_id),
        changed=changed,
        model_p_market_ids=tuple(sorted(model)),
        monte_carlo_market_ids=tuple(sorted(mc)),
        pricing_market_ids=tuple(sorted(pricing)),
        reusable_simulation_market_ids=tuple(sorted(reusable)),
        blocked_market_ids=tuple(sorted(blocked)),
        portfolio_refresh=refresh,
        affected_correlation_groups=tuple(sorted(groups)),
        reasons_by_market={key: tuple(value) for key, value in sorted(reasons.items())},
    )


@dataclass(frozen=True)
class DeltaExecutionResult:
    run_id: str
    plan: DeltaRerunPlan
    market_results: Mapping[str, Any]
    portfolio_result: Any
    execution_result: Any


def execute_delta_rerun(
    *,
    plan: DeltaRerunPlan,
    prior_market_results: Mapping[str, Any],
    model_p_fn: Callable[[str, Any | None], Any],
    monte_carlo_fn: Callable[[str, Any, Any | None], Any],
    pricing_fn: Callable[[str, Any, Any | None], Any],
    portfolio_fn: Callable[[Mapping[str, Any], Sequence[str]], Any],
    execution_gate_fn: Callable[[Mapping[str, Any], Any, Sequence[str]], Any],
) -> DeltaExecutionResult:
    """Execute a dependency-scoped delta without changing the original run id.

    Callbacks keep this orchestration sport-agnostic. Existing Monte Carlo artifacts
    are reused only for markets not listed for model/simulation invalidation. Pricing
    can rerun independently for quote-only changes. Portfolio/execution always sees
    the complete slate after an affected market has been recomputed.
    """
    state = dict(prior_market_results)
    blocked = set(plan.blocked_market_ids)

    for market_id in blocked:
        prior = state.get(market_id)
        state[market_id] = {
            "market_id": market_id,
            "bet_status": "BLOCKED",
            "reason": ";".join(plan.reasons_by_market.get(market_id, ("REQUIRED_DEPENDENCY_UNSAFE",))),
            "prior_result": prior,
        }

    for market_id in plan.model_p_market_ids:
        prior = state.get(market_id)
        state[market_id] = {"model_p": model_p_fn(market_id, prior), "prior_result": prior}

    for market_id in plan.monte_carlo_market_ids:
        current = state.get(market_id)
        model_value = current.get("model_p") if isinstance(current, Mapping) else None
        if model_value is None and market_id not in plan.model_p_market_ids:
            prior = prior_market_results.get(market_id)
            model_value = prior.get("model_p") if isinstance(prior, Mapping) else None
        simulation = monte_carlo_fn(market_id, model_value, current)
        if isinstance(current, Mapping):
            merged = dict(current); merged["monte_carlo"] = simulation; state[market_id] = merged
        else:
            state[market_id] = {"model_p": model_value, "monte_carlo": simulation, "prior_result": current}

    for market_id in plan.pricing_market_ids:
        if market_id in blocked:
            continue
        current = state.get(market_id)
        priced = pricing_fn(market_id, current, prior_market_results.get(market_id))
        state[market_id] = priced

    portfolio = None
    execution = None
    if plan.portfolio_refresh:
        portfolio = portfolio_fn(state, plan.affected_correlation_groups)
        execution = execution_gate_fn(state, portfolio, plan.blocked_market_ids)

    return DeltaExecutionResult(
        run_id=plan.run_id,
        plan=plan,
        market_results=state,
        portfolio_result=portfolio,
        execution_result=execution,
    )
