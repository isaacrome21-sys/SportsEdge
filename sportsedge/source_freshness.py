"""Per-source freshness evaluation for MLB dynamic inputs.

Freshness is source-specific. ABSENT and STALE are deliberately distinct states:
ABSENT may be a legitimate pregame condition under the source contract, while
STALE indicates a collector/runtime failure to re-verify an input in time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Mapping

DEFAULT_CONTRACT = Path("config/mlb_source_freshness_contract.json")
VALID_STATES = {"FRESH", "ABSENT", "STALE", "INVALID"}


@dataclass(frozen=True)
class FreshnessResult:
    source: str
    state: str
    age_seconds: float | None
    max_age_seconds: int | None
    policy: str
    provider_tier: str
    reason: str


def _parse_ts(value: Any) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("TIMESTAMP_MISSING")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("TIMESTAMP_TIMEZONE_REQUIRED")
    return dt.astimezone(timezone.utc)


def load_freshness_contract(path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("sources"), dict):
        raise ValueError("SOURCE_FRESHNESS_CONTRACT_MALFORMED")
    return value


def evaluate_source_freshness(
    source: str,
    payload: Mapping[str, Any] | None,
    *,
    now: datetime | None = None,
    contract_path: str | Path = DEFAULT_CONTRACT,
) -> FreshnessResult:
    contract = load_freshness_contract(contract_path)
    cfg = contract["sources"].get(source)
    if not isinstance(cfg, dict):
        raise ValueError(f"SOURCE_NOT_IN_FRESHNESS_CONTRACT:{source}")
    provider_tier = str(cfg.get("provider_tier") or "UNKNOWN")
    max_age = cfg.get("max_age_seconds")
    if max_age is not None:
        if isinstance(max_age, bool) or not isinstance(max_age, int) or max_age <= 0:
            raise ValueError(f"SOURCE_TTL_INVALID:{source}")
    if payload is None:
        return FreshnessResult(
            source, "ABSENT", None, max_age,
            str(cfg.get("absence_policy") or "BLOCK"), provider_tier,
            "SOURCE_ABSENT",
        )
    if not isinstance(payload, Mapping):
        return FreshnessResult(source, "INVALID", None, max_age, "BLOCK", provider_tier, "SOURCE_PAYLOAD_NOT_OBJECT")

    # Immutable hash-verified artifacts do not age on a wall clock.
    if max_age is None:
        artifact_hash = payload.get("artifact_hash") or payload.get("sha256")
        verified = payload.get("hash_verified") is True
        if verified and isinstance(artifact_hash, str) and artifact_hash.strip():
            return FreshnessResult(source, "FRESH", None, None, "ALLOW", provider_tier, "HASH_VERIFIED_IMMUTABLE_ARTIFACT")
        return FreshnessResult(source, "INVALID", None, None, "BLOCK", provider_tier, "IMMUTABLE_ARTIFACT_HASH_NOT_VERIFIED")

    clock_field = str(cfg.get("freshness_clock") or "retrieved_at")
    try:
        observed = _parse_ts(payload.get(clock_field))
    except Exception as exc:
        return FreshnessResult(source, "INVALID", None, max_age, "BLOCK", provider_tier, f"{type(exc).__name__}:{exc}")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("NOW_TIMEZONE_REQUIRED")
    current = current.astimezone(timezone.utc)
    age = (current - observed).total_seconds()
    if age < -300:
        return FreshnessResult(source, "INVALID", age, max_age, "BLOCK", provider_tier, "SOURCE_TIMESTAMP_IN_FUTURE")
    if age > max_age:
        return FreshnessResult(
            source, "STALE", age, max_age,
            str(cfg.get("stale_policy") or "BLOCK"), provider_tier,
            f"SOURCE_STALE:{int(age)}s>{max_age}s",
        )
    return FreshnessResult(source, "FRESH", max(0.0, age), max_age, "ALLOW", provider_tier, "SOURCE_WITHIN_TTL")


def source_state_dict(result: FreshnessResult) -> dict[str, Any]:
    if result.state not in VALID_STATES:
        raise ValueError("SOURCE_STATE_INVALID")
    return {
        "source": result.source,
        "state": result.state,
        "age_seconds": result.age_seconds,
        "max_age_seconds": result.max_age_seconds,
        "policy": result.policy,
        "provider_tier": result.provider_tier,
        "reason": result.reason,
    }
