"""Deterministic fail-closed bridge from timestamped source facts to live features.

Implements the checked design contract used by SportsEdge: future facts, stale
facts, conflicting facts, missing facts, and sportsbook-derived model features
all fail closed. The bridge produces *features*, never Model_P.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite
from typing import Any, Mapping, Sequence

from .hits_engine import FEATURE_CONTRACT_VERSION as HITS_FEATURE_VERSION
from .runtime import parse_timestamp
from .total_bases_engine import FEATURE_CONTRACT_VERSION as TB_FEATURE_VERSION


class FeatureBridgeError(ValueError):
    def __init__(self, reason: str, detail: Mapping[str, Any] | None = None):
        self.reason = reason
        self.detail = dict(detail or {})
        super().__init__(f"{reason}: {self.detail}")


BANNED_FACT_PATTERNS = (
    "sportsbook", "market_probability", "market_prob", "implied_probability",
    "implied_prob", "american_odds", "decimal_odds", "novig", "no_vig",
    "dk_prob", "closing_prob", "consensus_prob",
)

FEATURE_VERSIONS = {
    "HITS": HITS_FEATURE_VERSION,
    "TOTAL_BASES": TB_FEATURE_VERSION,
}

REQUIRED_FEATURES = {
    "HITS": ("b_rate", "p_rate", "pa_pool"),
    "TOTAL_BASES": ("rates_s", "rates_d", "rates_t", "rates_hr", "p_h", "p_hr", "park", "pa_pool"),
}


@dataclass(frozen=True)
class SourceFact:
    source_id: str
    fact_key: str
    value: Any
    provider: str
    event_time: datetime
    retrieved_at: datetime
    status: str | None = None


@dataclass(frozen=True)
class Provenance:
    feature: str
    source_id: str
    provider: str
    event_time: str
    retrieved_at: str


def _dt(value: Any, name: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise FeatureBridgeError("MALFORMED", {"field": name, "detail": "timezone required"})
        return dt.astimezone(timezone.utc)
    if isinstance(value, str):
        try:
            return parse_timestamp(value)
        except Exception as exc:
            raise FeatureBridgeError("MALFORMED", {"field": name, "detail": str(exc)}) from exc
    raise FeatureBridgeError("MALFORMED", {"field": name, "detail": "datetime/ISO string required"})


def parse_source_fact(raw: Mapping[str, Any]) -> SourceFact:
    if not isinstance(raw, Mapping):
        raise FeatureBridgeError("MALFORMED", {"detail": "source fact must be object"})
    for key in ("source_id", "fact_key", "provider", "event_time", "retrieved_at"):
        if key not in raw or raw[key] in (None, ""):
            raise FeatureBridgeError("MALFORMED", {"field": key})
    status = raw.get("status")
    if status is not None and status not in ("CONFIRMED", "PROJECTED"):
        raise FeatureBridgeError("MALFORMED", {"field": "status"})
    return SourceFact(
        source_id=str(raw["source_id"]), fact_key=str(raw["fact_key"]),
        value=raw.get("value"), provider=str(raw["provider"]),
        event_time=_dt(raw["event_time"], "event_time"),
        retrieved_at=_dt(raw["retrieved_at"], "retrieved_at"), status=status,
    )


def _banned(fact_key: str) -> bool:
    low = fact_key.lower()
    return any(p in low for p in BANNED_FACT_PATTERNS)


def _canonical_value(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise FeatureBridgeError("MALFORMED", {"detail": "fact value not canonical JSON"}) from exc


def _resolve_one(
    *, feature: str, fact_key: str, facts: Sequence[SourceFact], now: datetime,
    wager_cutoff: datetime, ttl_seconds: float,
) -> tuple[Any, Provenance, str | None]:
    if _banned(fact_key):
        raise FeatureBridgeError("BANNED_FACT", {"fact_key": fact_key})
    candidates = [f for f in facts if f.fact_key == fact_key]
    if not candidates:
        raise FeatureBridgeError("MISSING", {"fact_key": fact_key})
    valid: list[SourceFact] = []
    stale: list[dict[str, Any]] = []
    for f in candidates:
        if _banned(f.fact_key):
            raise FeatureBridgeError("BANNED_FACT", {"fact_key": f.fact_key, "source_id": f.source_id})
        if f.event_time > wager_cutoff:
            raise FeatureBridgeError("FUTURE_EVENT_TIME", {"fact_key": fact_key, "source_id": f.source_id})
        if f.retrieved_at > now:
            raise FeatureBridgeError("FUTURE_RETRIEVAL_TIME", {"fact_key": fact_key, "source_id": f.source_id})
        age = (now - f.retrieved_at).total_seconds()
        if age > ttl_seconds:
            stale.append({"source_id": f.source_id, "age_seconds": age})
            continue
        valid.append(f)
    if not valid:
        raise FeatureBridgeError("STALE", {"fact_key": fact_key, "limit_seconds": ttl_seconds, "candidates": stale})

    by_value: dict[str, list[SourceFact]] = {}
    for f in valid:
        by_value.setdefault(_canonical_value(f.value), []).append(f)
    if len(by_value) != 1:
        raise FeatureBridgeError("CONFLICT", {"fact_key": fact_key, "source_ids": sorted(f.source_id for f in valid)})

    # Identical duplicates are harmless; canonical source selection makes output
    # invariant to input ordering.
    chosen = sorted(valid, key=lambda f: (f.retrieved_at, f.source_id), reverse=True)[0]
    prov = Provenance(
        feature, chosen.source_id, chosen.provider,
        chosen.event_time.isoformat(), chosen.retrieved_at.isoformat(),
    )
    return chosen.value, prov, chosen.status


def resolve_feature_row(
    *, market: str, game_pk: int, player_id: int, team_id: int,
    feature_fact_keys: Mapping[str, str], sources: Sequence[Mapping[str, Any]],
    ttl_by_feature: Mapping[str, float], now: datetime | str, wager_cutoff: datetime | str,
) -> dict[str, Any]:
    """Resolve one versioned feature row for live_slate. Never emits probability."""
    if market not in REQUIRED_FEATURES:
        raise FeatureBridgeError("UNSUPPORTED_MARKET", {"market": market})
    required = REQUIRED_FEATURES[market]
    if set(feature_fact_keys) != set(required):
        raise FeatureBridgeError("CONTRACT_MISMATCH", {"expected": list(required), "got": sorted(feature_fact_keys)})
    if set(ttl_by_feature) != set(required):
        raise FeatureBridgeError("CONTRACT_MISMATCH", {"detail": "ttl keys must exactly match required features"})
    current = _dt(now, "now")
    cutoff = _dt(wager_cutoff, "wager_cutoff")
    facts = [parse_source_fact(x) for x in sources]

    values: dict[str, Any] = {}
    provenance: list[dict[str, Any]] = []
    statuses: set[str] = set()
    for feature in required:
        ttl = ttl_by_feature[feature]
        if isinstance(ttl, bool):
            raise FeatureBridgeError("MALFORMED", {"feature": feature, "detail": "ttl invalid"})
        try:
            ttl = float(ttl)
        except (TypeError, ValueError) as exc:
            raise FeatureBridgeError("MALFORMED", {"feature": feature, "detail": "ttl invalid"}) from exc
        if not isfinite(ttl) or ttl <= 0:
            raise FeatureBridgeError("MALFORMED", {"feature": feature, "detail": "ttl must be finite > 0"})
        value, prov, status = _resolve_one(
            feature=feature, fact_key=feature_fact_keys[feature], facts=facts,
            now=current, wager_cutoff=cutoff, ttl_seconds=ttl,
        )
        values[feature] = value
        provenance.append(asdict(prov))
        if status is not None:
            statuses.add(status)

    if len(statuses) > 1:
        raise FeatureBridgeError("CONFLICT", {"detail": "mixed lineup statuses", "statuses": sorted(statuses)})
    lineup_status = next(iter(statuses)) if statuses else None

    if market == "HITS":
        payload = {"b_rate": values["b_rate"], "p_rate": values["p_rate"], "pa_pool": values["pa_pool"]}
    else:
        payload = {
            "rates": {"s":values["rates_s"],"d":values["rates_d"],"t":values["rates_t"],"hr":values["rates_hr"]},
            "p_h":values["p_h"], "p_hr":values["p_hr"], "park":values["park"], "pa_pool":values["pa_pool"],
        }

    # Source-subset hash is for audit/provenance. live_slate derives the final
    # candidate build_hash after line/side and confirmed MLB identity are bound.
    audit_material = json.dumps({"market":market,"features":payload,"provenance":provenance}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    row = {
        "game_pk": int(game_pk), "player_id": int(player_id), "team_id": int(team_id),
        "market": market, "feature_version": FEATURE_VERSIONS[market],
        **payload,
        "source_subset_hash": hashlib.sha256(audit_material.encode()).hexdigest(),
        "provenance": provenance,
    }
    if lineup_status is not None:
        row["source_lineup_status"] = lineup_status
    return row
