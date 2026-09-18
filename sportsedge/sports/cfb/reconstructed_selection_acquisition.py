"""Deterministic, zero-authority acquisition contract for reconstructed CFB selection.

This module defines the frozen request plan and verifiable cache identities only.  It
performs no network I/O, model fitting, candidate evaluation, promotion, or betting
authority. Raw CFBD responses must live in a caller-supplied private cache outside
the public repository.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "CFB_RECONSTRUCTED_SELECTION_ACQUISITION_CONTRACT_V1"
SELECTION_START_SEASON = 2015
SELECTION_END_SEASON = 2025
PRIOR_FALLBACK_SEASON = 2014
MAX_REGULAR_WEEK = 20
EXPECTED_REQUEST_COUNT = 254

_SENSITIVE_KEYS = frozenset({
    "authorization", "api_key", "apikey", "token", "access_token", "secret",
    "cfbd_api_key",
})


class CFBReconstructedAcquisitionError(ValueError):
    pass


@dataclass(frozen=True)
class AcquisitionRequest:
    endpoint: str
    season: int
    end_week: int | None
    provider_contract: str
    query_params: Mapping[str, Any]

    def canonical_payload(self) -> dict[str, Any]:
        endpoint = str(self.endpoint or "").strip()
        provider = str(self.provider_contract or "").strip()
        if not endpoint.startswith("/") or not provider:
            raise CFBReconstructedAcquisitionError("ACQUISITION_REQUEST_IDENTITY_INVALID")
        season = int(self.season)
        if season < PRIOR_FALLBACK_SEASON or season > SELECTION_END_SEASON:
            raise CFBReconstructedAcquisitionError("ACQUISITION_REQUEST_SEASON_OUT_OF_SCOPE")
        end_week = None if self.end_week is None else int(self.end_week)
        if end_week is not None and not 1 <= end_week < MAX_REGULAR_WEEK:
            raise CFBReconstructedAcquisitionError("ACQUISITION_REQUEST_END_WEEK_INVALID")
        params: dict[str, Any] = {}
        for raw_key, value in self.query_params.items():
            key = str(raw_key).strip()
            if not key:
                raise CFBReconstructedAcquisitionError("ACQUISITION_QUERY_KEY_EMPTY")
            if key.lower() in _SENSITIVE_KEYS:
                raise CFBReconstructedAcquisitionError("ACQUISITION_SECRET_IN_QUERY_PROHIBITED")
            if isinstance(value, (str, int, float, bool)) or value is None:
                params[key] = value
            else:
                raise CFBReconstructedAcquisitionError("ACQUISITION_QUERY_VALUE_INVALID")
        return {
            "endpoint": endpoint,
            "season": season,
            "end_week": end_week,
            "provider_contract": provider,
            "query_params": dict(sorted(params.items())),
        }

    @property
    def query_sha256(self) -> str:
        raw = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        return sha256(raw).hexdigest()


def build_reconstructed_selection_plan() -> list[AcquisitionRequest]:
    """Return the exact 254-call conservative replay plan; performs no I/O."""
    plan: list[AcquisitionRequest] = []

    # One full regular-season game payload per metric season, including 2014 fallback.
    for season in range(PRIOR_FALLBACK_SEASON, SELECTION_END_SEASON + 1):
        plan.append(AcquisitionRequest(
            endpoint="/games", season=season, end_week=None,
            provider_contract="CFBD_GAMES_REGULAR_FBS_V1",
            query_params={"year": season, "seasonType": "regular", "classification": "fbs"},
        ))

    # FBS membership and weather apply to selection seasons only.
    for season in range(SELECTION_START_SEASON, SELECTION_END_SEASON + 1):
        plan.append(AcquisitionRequest(
            endpoint="/teams/fbs", season=season, end_week=None,
            provider_contract="CFBD_TEAMS_FBS_V1", query_params={"year": season},
        ))
        plan.append(AcquisitionRequest(
            endpoint="/games/weather", season=season, end_week=None,
            provider_contract="CFBD_GAMES_WEATHER_V1",
            query_params={"year": season, "seasonType": "regular"},
        ))

    # Week 2-20 rows consume current-season metrics through week-1: endWeek 1-19.
    for season in range(SELECTION_START_SEASON, SELECTION_END_SEASON + 1):
        for end_week in range(1, MAX_REGULAR_WEEK):
            plan.append(AcquisitionRequest(
                endpoint="/stats/season/advanced", season=season, end_week=end_week,
                provider_contract="CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
                query_params={
                    "year": season, "endWeek": end_week,
                    "excludeGarbageTime": "true", "classification": "fbs",
                },
            ))

    # Week 1 uses one full immediately-prior-season snapshot; includes 2014 for 2015.
    for prior_season in range(PRIOR_FALLBACK_SEASON, SELECTION_END_SEASON):
        plan.append(AcquisitionRequest(
            endpoint="/stats/season/advanced", season=prior_season, end_week=None,
            provider_contract="CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
            query_params={
                "year": prior_season, "excludeGarbageTime": "true", "classification": "fbs",
            },
        ))

    hashes = [request.query_sha256 for request in plan]
    if len(plan) != EXPECTED_REQUEST_COUNT:
        raise CFBReconstructedAcquisitionError(
            f"ACQUISITION_PLAN_COUNT_DRIFT:{len(plan)}:{EXPECTED_REQUEST_COUNT}"
        )
    if len(set(hashes)) != len(hashes):
        raise CFBReconstructedAcquisitionError("ACQUISITION_PLAN_QUERY_IDENTITY_DUPLICATE")
    return plan


def response_sha256(raw_response: bytes) -> str:
    if not isinstance(raw_response, bytes):
        raise CFBReconstructedAcquisitionError("ACQUISITION_RAW_RESPONSE_BYTES_REQUIRED")
    return sha256(raw_response).hexdigest()


def _utc_timestamp(value: str) -> str:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise CFBReconstructedAcquisitionError("ACQUISITION_RETRIEVAL_TIMESTAMP_REQUIRED")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBReconstructedAcquisitionError("ACQUISITION_RETRIEVAL_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CFBReconstructedAcquisitionError("ACQUISITION_RETRIEVAL_TIMESTAMP_TIMEZONE_REQUIRED")
    return parsed.astimezone(timezone.utc).isoformat()


def build_cache_manifest_entry(
    request: AcquisitionRequest, *, raw_response: bytes, retrieved_at_utc: str
) -> dict[str, Any]:
    """Build redacted cache metadata; raw bytes are hashed but never embedded."""
    identity = request.canonical_payload()
    return {
        "endpoint": identity["endpoint"],
        "season": identity["season"],
        "end_week": identity["end_week"],
        "provider_contract": identity["provider_contract"],
        "query_sha256": request.query_sha256,
        "response_sha256": response_sha256(raw_response),
        "retrieved_at_utc": _utc_timestamp(retrieved_at_utc),
    }


def verify_cached_response(
    request: AcquisitionRequest, *, entry: Mapping[str, Any], raw_response: bytes
) -> bool:
    """Verify a private cached response against its redacted manifest identity."""
    expected = request.canonical_payload()
    for key in ("endpoint", "season", "end_week", "provider_contract"):
        if entry.get(key) != expected[key]:
            return False
    return (
        entry.get("query_sha256") == request.query_sha256
        and entry.get("response_sha256") == response_sha256(raw_response)
        and bool(entry.get("retrieved_at_utc"))
    )


def assert_private_cache_root(cache_root: str | Path, *, repository_root: str | Path) -> Path:
    """Reject any raw-response cache located inside the public repository tree."""
    cache = Path(cache_root).expanduser().resolve()
    repo = Path(repository_root).expanduser().resolve()
    try:
        cache.relative_to(repo)
    except ValueError:
        pass
    else:
        raise CFBReconstructedAcquisitionError("PUBLIC_REPOSITORY_RAW_CACHE_PROHIBITED")
    if cache == repo:
        raise CFBReconstructedAcquisitionError("PUBLIC_REPOSITORY_RAW_CACHE_PROHIBITED")
    return cache


def governance_stamp() -> dict[str, bool]:
    return {
        "network_call_performed": False,
        "attempt_consumed": False,
        "evaluation_performed": False,
        "model_fit_performed": False,
        "model_p_created": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "eligibility_changed": False,
        "staking_authority": False,
        "official_authority": False,
        "backfill_authority": False,
    }


__all__ = [
    "AcquisitionRequest", "CFBReconstructedAcquisitionError", "EXPECTED_REQUEST_COUNT",
    "assert_private_cache_root", "build_cache_manifest_entry",
    "build_reconstructed_selection_plan", "governance_stamp", "response_sha256",
    "verify_cached_response",
]
