"""Fail-closed status accounting for the required SportsEdge MLB Full Model markets.

Every required family is emitted exactly once.  A family may produce a priced
candidate or an explicit non-candidate state; it may never silently disappear.
The strictest applicable deployment registry wins so a legacy deployment cannot
bypass a newer validation contract (for example Statcast-required V5).
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

REQUIRED_FULL_MODEL_MARKETS = (
    "MONEYLINE",
    "RUN_LINE",
    "TOTALS",
    "NRFI",
    "YRFI",
    "HITS",
    "TOTAL_BASES",
    "PITCHER_BB",
)

PUBLIC_STATES = (
    "PRICED_CANDIDATE",
    "NO_PRICE",
    "MODEL_NOT_ELIGIBLE",
    "BLOCKED",
)

# Markets whose current standard is governed by the newer Statcast V5 registry.
STRICT_REGISTRY_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI"})


class FullModelStatusError(ValueError):
    pass


def _rows(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, Mapping)]


def _market(row: Mapping[str, Any]) -> str:
    return str(row.get("market") or row.get("market_family") or "").upper()


def _registry_market(registry: Mapping[str, Any] | None, family: str) -> Mapping[str, Any] | None:
    markets = (registry or {}).get("markets")
    if not isinstance(markets, Mapping):
        return None
    row = markets.get(family)
    return row if isinstance(row, Mapping) else None


def effective_deployment(
    family: str,
    *,
    legacy_registry: Mapping[str, Any] | None,
    strict_registry: Mapping[str, Any] | None,
) -> Mapping[str, Any] | None:
    """Return the registry row that is allowed to govern current eligibility."""
    family = str(family).upper()
    if family in STRICT_REGISTRY_MARKETS:
        strict = _registry_market(strict_registry, family)
        if strict is None:
            return {
                "eligible": False,
                "stage": "STRICT_REGISTRY_MISSING",
                "reason": "strict Statcast deployment registry has no market row",
            }
        return strict
    return _registry_market(legacy_registry, family)


def build_required_market_status(
    *,
    legacy_registry: Mapping[str, Any] | None,
    strict_registry: Mapping[str, Any] | None,
    quote_rows: Sequence[Mapping[str, Any]] | None = None,
    card_rows: Sequence[Mapping[str, Any]] | None = None,
    source_failures: Sequence[Mapping[str, Any]] | None = None,
    runtime_blocks: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build the eight-family Full Model status matrix.

    Priority is intentionally fail-closed:
      1. current model eligibility/attestation;
      2. explicit runtime blocker;
      3. legitimate price availability;
      4. priced candidate.

    A price can never make an ineligible model eligible.
    """
    quotes = _rows(list(quote_rows or []))
    cards = _rows(list(card_rows or []))
    failures = _rows(list(source_failures or []))
    runtime_blocks = {str(k).upper(): str(v) for k, v in (runtime_blocks or {}).items() if str(v)}

    q_by_market = Counter(_market(x) for x in quotes)
    c_by_market = Counter(_market(x) for x in cards)
    failures_by_market: dict[str, list[str]] = {}
    for row in failures:
        fam = _market(row)
        if not fam:
            continue
        reason = str(row.get("reason") or row.get("error") or row.get("code") or "PRICE_SOURCE_FAILED")
        failures_by_market.setdefault(fam, []).append(reason)

    out: list[dict[str, Any]] = []
    for family in REQUIRED_FULL_MODEL_MARKETS:
        deployment = effective_deployment(
            family,
            legacy_registry=legacy_registry,
            strict_registry=strict_registry,
        )
        eligible = bool((deployment or {}).get("eligible") is True)
        stage = str((deployment or {}).get("stage") or "DEPLOYMENT_EVIDENCE_MISSING")
        deployment_reason = str((deployment or {}).get("reason") or "deployment/attestation evidence missing")
        quote_count = int(q_by_market.get(family, 0))
        candidate_count = int(c_by_market.get(family, 0))

        if not eligible:
            state = "MODEL_NOT_ELIGIBLE"
            reason = f"{stage}: {deployment_reason}"
        elif family in runtime_blocks:
            state = "BLOCKED"
            reason = runtime_blocks[family]
        elif quote_count <= 0:
            state = "NO_PRICE"
            details = failures_by_market.get(family) or []
            reason = details[0] if details else "no reachable legitimate fresh sportsbook quote for this market"
        else:
            state = "PRICED_CANDIDATE"
            reason = "model eligible and legitimate price present; candidate remains subject to per-candidate identity/freshness/edge gates"

        if state not in PUBLIC_STATES:
            raise FullModelStatusError(f"FULL_MODEL_STATE_INVALID:{family}:{state}")
        out.append({
            "market_family": family,
            "state": state,
            "model_eligible": eligible,
            "validation_stage": stage,
            "quote_count": quote_count,
            "candidate_count": candidate_count,
            "reason": reason,
        })

    if tuple(row["market_family"] for row in out) != REQUIRED_FULL_MODEL_MARKETS:
        raise FullModelStatusError("FULL_MODEL_MARKET_ACCOUNTING_INCOMPLETE")
    return {
        "schema_version": 1,
        "required_market_families": list(REQUIRED_FULL_MODEL_MARKETS),
        "markets": out,
        "complete_accounting": len(out) == len(REQUIRED_FULL_MODEL_MARKETS),
        "policy": "priced_candidate_or_explicit_fail_closed_status_no_silent_omission",
    }
