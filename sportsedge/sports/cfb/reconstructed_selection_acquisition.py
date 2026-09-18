"""Quota-gated CFBD acquisition for reconstructed CFB candidate selection.

This module is selection-input plumbing only. It performs no model fit, candidate
scoring, Model_P creation, Truth Gate evaluation, promotion, staking, OFFICIAL
selection, forward-clock mutation, or prospective-evidence backfill.

Raw CFBD response bytes are hashed in memory and are never written by this
module. Only a deterministic projection plus the raw-response SHA256 is cached.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE_URL = "https://api.collegefootballdata.com"
SCHEMA_VERSION = "CFB_RECONSTRUCTED_SELECTION_ACQUISITION_V1"
CACHE_ENTRY_SCHEMA = "CFB_RECONSTRUCTED_SELECTION_CACHE_ENTRY_V1"
PUBLIC_MANIFEST_SCHEMA = "CFB_RECONSTRUCTED_SELECTION_ACQUISITION_PUBLIC_V1"


class CFBAcquisitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RequestSpec:
    endpoint: str
    season: int
    end_week: int | None
    provider_contract: str
    query: tuple[tuple[str, str], ...]

    @property
    def query_dict(self) -> dict[str, str]:
        return dict(self.query)

    @property
    def query_sha256(self) -> str:
        payload = {
            "endpoint": self.endpoint,
            "provider_contract": self.provider_contract,
            "query": list(self.query),
        }
        return _sha_json(payload)


def _authority() -> dict[str, bool]:
    return {
        "attempt_consumed": False,
        "evaluation_performed": False,
        "model_p": False,
        "truth_gate": False,
        "promotion": False,
        "eligibility": False,
        "staking": False,
        "official": False,
        "forward_clock": False,
        "prospective_backfill": False,
    }


def _canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _sha_json(payload: Any) -> str:
    return sha256(_canonical_bytes(payload)).hexdigest()


def _sha_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _int(value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise CFBAcquisitionError("INTEGER_FIELD_INVALID")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise CFBAcquisitionError("INTEGER_FIELD_INVALID") from exc
    if out < minimum:
        raise CFBAcquisitionError("INTEGER_FIELD_INVALID")
    return out


def validate_private_preflight(report: Mapping[str, Any]) -> None:
    if report.get("schema_version") != "CFB_CFBD_PROVIDER_PREFLIGHT_V1":
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_SCHEMA_MISMATCH")
    if report.get("status") != "VERIFIED_BEFORE_FIRST_REPLAY_CALL":
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_NOT_VERIFIED")
    if not str(report.get("active_cfbd_tier") or "").strip():
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_TIER_MISSING")
    monthly = _int(report.get("monthly_quota"), minimum=1)
    remaining = _int(report.get("remaining_quota"))
    planned = _int(report.get("planned_new_calls"))
    reserve = _int(report.get("retry_reserve_calls"))
    if monthly < remaining:
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_QUOTA_INCONSISTENT")
    if remaining < planned + reserve:
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_BUDGET_NO_LONGER_FITS")
    if report.get("weather_entitled") is not True:
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_WEATHER_NOT_ENTITLED")
    if report.get("verified_cache_reuse") is not True:
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_CACHE_REUSE_NOT_VERIFIED")
    if report.get("resume_from_verified_cache") is not True:
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_CACHE_RESUME_NOT_VERIFIED")
    if report.get("restart_from_2015") is not False:
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_FULL_RESTART_FORBIDDEN")
    if report.get("retry_backoff") is not True:
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_RETRY_BACKOFF_NOT_VERIFIED")
    if report.get("historical_replay_calls_performed") != 0:
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_ALREADY_SPENT_REPLAY_CALLS")
    authority = report.get("authority") or {}
    if not authority or any(value is not False for value in authority.values()):
        raise CFBAcquisitionError("PRIVATE_PREFLIGHT_AUTHORITY_LEAK")


def load_budget(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "CFB_CFBD_RECONSTRUCTED_SELECTION_BUDGET_V1":
        raise CFBAcquisitionError("BUDGET_SCHEMA_MISMATCH")
    return payload


def _query(**kwargs: Any) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(k), str(v)) for k, v in kwargs.items() if v is not None))


def build_request_plan(config: Mapping[str, Any]) -> tuple[RequestSpec, ...]:
    start = _int(config.get("selection_start_season"), minimum=1900)
    end = _int(config.get("selection_end_season"), minimum=start)
    prior = _int(config.get("prior_fallback_season"), minimum=1900)
    max_week = _int(config.get("max_regular_week_planning_bound"), minimum=2)
    if prior != start - 1:
        raise CFBAcquisitionError("PRIOR_FALLBACK_SEASON_MISMATCH")

    specs: list[RequestSpec] = []

    for season in range(prior, end + 1):
        specs.append(RequestSpec(
            endpoint="/games",
            season=season,
            end_week=None,
            provider_contract="CFBD_GAMES_REGULAR_FBS_V1",
            query=_query(year=season, seasonType="regular", classification="fbs"),
        ))

    for season in range(start, end + 1):
        specs.append(RequestSpec(
            endpoint="/teams/fbs",
            season=season,
            end_week=None,
            provider_contract="CFBD_TEAMS_FBS_YEAR_V1",
            query=_query(year=season),
        ))
        specs.append(RequestSpec(
            endpoint="/games/weather",
            season=season,
            end_week=None,
            provider_contract="CFBD_GAMES_WEATHER_REGULAR_FBS_V1",
            query=_query(year=season, seasonType="regular", classification="fbs"),
        ))

        # Week 1 must use the immediately-prior-season snapshot. endWeek at the
        # planning bound intentionally means "all available regular-season games
        # through the bound" and is distinct from the current-season snapshots.
        specs.append(RequestSpec(
            endpoint="/stats/season/advanced",
            season=season - 1,
            end_week=max_week,
            provider_contract="CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
            query=_query(year=season - 1, endWeek=max_week),
        ))
        for end_week in range(1, max_week):
            specs.append(RequestSpec(
                endpoint="/stats/season/advanced",
                season=season,
                end_week=end_week,
                provider_contract="CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
                query=_query(year=season, endWeek=end_week),
            ))

    expected = _int((config.get("planned_new_calls_upper_bound") or {}).get("total"))
    if len(specs) != expected:
        raise CFBAcquisitionError(
            f"REQUEST_PLAN_COUNT_MISMATCH:expected={expected}:actual={len(specs)}"
        )
    identities = {(s.endpoint, s.query_sha256) for s in specs}
    if len(identities) != len(specs):
        raise CFBAcquisitionError("REQUEST_PLAN_IDENTITY_DUPLICATE")
    return tuple(specs)


def _pick(obj: Mapping[str, Any], *path: str) -> Any:
    current: Any = obj
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _project_advanced(rows: Iterable[Any]) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        offense = raw.get("offense") if isinstance(raw.get("offense"), Mapping) else {}
        defense = raw.get("defense") if isinstance(raw.get("defense"), Mapping) else {}
        projected.append({
            "season": raw.get("season"),
            "team": raw.get("team"),
            "conference": raw.get("conference"),
            "offense": {
                "ppa": offense.get("ppa"),
                "successRate": offense.get("successRate"),
                "explosiveness": offense.get("explosiveness"),
                "drives": offense.get("drives"),
                "totalOpportunies": offense.get("totalOpportunies"),
                "pointsPerOpportunity": offense.get("pointsPerOpportunity"),
                "rushingPlays": {
                    "ppa": _pick(offense, "rushingPlays", "ppa"),
                    "successRate": _pick(offense, "rushingPlays", "successRate"),
                },
                "passingPlays": {
                    "ppa": _pick(offense, "passingPlays", "ppa"),
                    "successRate": _pick(offense, "passingPlays", "successRate"),
                },
                "standardDowns": {
                    "ppa": _pick(offense, "standardDowns", "ppa"),
                    "successRate": _pick(offense, "standardDowns", "successRate"),
                },
                "passingDowns": {
                    "ppa": _pick(offense, "passingDowns", "ppa"),
                    "successRate": _pick(offense, "passingDowns", "successRate"),
                },
                "fieldPosition": {
                    "averageStart": _pick(offense, "fieldPosition", "averageStart"),
                },
            },
            "defense": {
                "ppa": defense.get("ppa"),
                "successRate": defense.get("successRate"),
                "explosiveness": defense.get("explosiveness"),
                "drives": defense.get("drives"),
                "totalOpportunies": defense.get("totalOpportunies"),
                "pointsPerOpportunity": defense.get("pointsPerOpportunity"),
                "rushingPlays": {
                    "ppa": _pick(defense, "rushingPlays", "ppa"),
                    "successRate": _pick(defense, "rushingPlays", "successRate"),
                },
                "passingPlays": {
                    "ppa": _pick(defense, "passingPlays", "ppa"),
                    "successRate": _pick(defense, "passingPlays", "successRate"),
                },
                "standardDowns": {
                    "ppa": _pick(defense, "standardDowns", "ppa"),
                    "successRate": _pick(defense, "standardDowns", "successRate"),
                },
                "passingDowns": {
                    "ppa": _pick(defense, "passingDowns", "ppa"),
                    "successRate": _pick(defense, "passingDowns", "successRate"),
                },
                "fieldPosition": {
                    "averageStart": _pick(defense, "fieldPosition", "averageStart"),
                },
            },
        })
    return projected


def _project_games(rows: Iterable[Any]) -> list[dict[str, Any]]:
    fields = (
        "id", "season", "week", "seasonType", "startDate", "startTime",
        "completed", "neutralSite", "homeTeam", "awayTeam", "homePoints",
        "awayPoints", "homeConference", "awayConference", "venueId", "venue",
    )
    return [
        {key: raw.get(key) for key in fields}
        for raw in rows
        if isinstance(raw, Mapping)
    ]


def _project_fbs(rows: Iterable[Any]) -> list[dict[str, Any]]:
    fields = ("id", "school", "mascot", "abbreviation", "conference", "classification")
    return [
        {key: raw.get(key) for key in fields}
        for raw in rows
        if isinstance(raw, Mapping)
    ]


def _project_weather(rows: Iterable[Any]) -> list[dict[str, Any]]:
    fields = (
        "id", "season", "week", "seasonType", "startTime", "gameIndoors",
        "venueId", "venue", "temperature", "dewPoint", "humidity",
        "precipitation", "snowfall", "windDirection", "windSpeed", "pressure",
        "weatherCondition",
    )
    return [
        {key: raw.get(key) for key in fields}
        for raw in rows
        if isinstance(raw, Mapping)
    ]


def project_payload(spec: RequestSpec, payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise CFBAcquisitionError(f"CFBD_PAYLOAD_NOT_LIST:{spec.endpoint}")
    if spec.endpoint == "/stats/season/advanced":
        return _project_advanced(payload)
    if spec.endpoint == "/games":
        return _project_games(payload)
    if spec.endpoint == "/teams/fbs":
        return _project_fbs(payload)
    if spec.endpoint == "/games/weather":
        return _project_weather(payload)
    raise CFBAcquisitionError(f"UNSUPPORTED_ENDPOINT:{spec.endpoint}")


def _cache_path(cache_root: Path, spec: RequestSpec) -> Path:
    slug = spec.endpoint.strip("/").replace("/", "__") or "root"
    return cache_root / slug / f"{spec.query_sha256}.json"


def _load_verified_cache(path: Path, spec: RequestSpec) -> dict[str, Any] | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != CACHE_ENTRY_SCHEMA:
        raise CFBAcquisitionError(f"CACHE_SCHEMA_MISMATCH:{path}")
    if payload.get("endpoint") != spec.endpoint:
        raise CFBAcquisitionError(f"CACHE_ENDPOINT_MISMATCH:{path}")
    if payload.get("query_sha256") != spec.query_sha256:
        raise CFBAcquisitionError(f"CACHE_QUERY_SHA_MISMATCH:{path}")
    if payload.get("provider_contract") != spec.provider_contract:
        raise CFBAcquisitionError(f"CACHE_PROVIDER_CONTRACT_MISMATCH:{path}")
    projection = payload.get("projection")
    if payload.get("projection_sha256") != _sha_json(projection):
        raise CFBAcquisitionError(f"CACHE_PROJECTION_SHA_MISMATCH:{path}")
    response_sha = str(payload.get("response_sha256") or "")
    if len(response_sha) != 64:
        raise CFBAcquisitionError(f"CACHE_RESPONSE_SHA_INVALID:{path}")
    return payload


def _request_bytes(
    spec: RequestSpec,
    api_key: str,
    *,
    opener: Callable = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    retries: int = 3,
) -> bytes:
    key = str(api_key or "").strip()
    if not key:
        raise CFBAcquisitionError("CFBD_API_KEY_MISSING")
    url = f"{BASE_URL}{spec.endpoint}?{urlencode(spec.query_dict)}"
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": "SportsEdge-CFB-reconstructed-selection/1",
        },
    )
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with opener(request, timeout=30) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt >= retries:
                break
            sleep(float(2 ** attempt))
    raise CFBAcquisitionError(
        f"CFBD_FETCH_FAILED:{spec.endpoint}:{type(last).__name__ if last else 'UNKNOWN'}"
    ) from last


def acquire_one(
    spec: RequestSpec,
    *,
    api_key: str,
    cache_root: Path,
    opener: Callable = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[dict[str, Any], bool]:
    cache_path = _cache_path(cache_root, spec)
    cached = _load_verified_cache(cache_path, spec)
    if cached is not None:
        return cached, True

    raw = _request_bytes(spec, api_key, opener=opener, sleep=sleep)
    response_sha = sha256(raw).hexdigest()
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBAcquisitionError(f"CFBD_INVALID_JSON:{spec.endpoint}") from exc
    projection = project_payload(spec, parsed)
    retrieved = now().astimezone(timezone.utc).isoformat()
    payload = {
        "schema_version": CACHE_ENTRY_SCHEMA,
        "endpoint": spec.endpoint,
        "season": spec.season,
        "end_week": spec.end_week,
        "provider_contract": spec.provider_contract,
        "query": spec.query_dict,
        "query_sha256": spec.query_sha256,
        "response_sha256": response_sha,
        "retrieved_at_utc": retrieved,
        "raw_response_persisted": False,
        "projection": projection,
        "projection_sha256": _sha_json(projection),
        "authority": _authority(),
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload, False


def acquire_plan(
    specs: Iterable[RequestSpec],
    *,
    api_key: str,
    cache_root: Path,
    opener: Callable = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[list[dict[str, Any]], int, int]:
    entries: list[dict[str, Any]] = []
    reused = 0
    fetched = 0
    for spec in specs:
        row, was_reused = acquire_one(
            spec,
            api_key=api_key,
            cache_root=cache_root,
            opener=opener,
            sleep=sleep,
            now=now,
        )
        if was_reused:
            reused += 1
        else:
            fetched += 1
        entries.append({
            "endpoint": row["endpoint"],
            "season": row["season"],
            "end_week": row["end_week"],
            "provider_contract": row["provider_contract"],
            "query_sha256": row["query_sha256"],
            "response_sha256": row["response_sha256"],
            "projection_sha256": row["projection_sha256"],
            "retrieved_at_utc": row["retrieved_at_utc"],
            "cache_path": str(_cache_path(cache_root, spec)),
        })
    return entries, reused, fetched


def build_public_manifest(
    *,
    private_preflight_path: Path,
    public_preflight_path: Path,
    budget_path: Path,
    cache_manifest: list[dict[str, Any]],
    reused_calls: int,
    fetched_calls: int,
) -> dict[str, Any]:
    private = json.loads(private_preflight_path.read_text(encoding="utf-8"))
    public = json.loads(public_preflight_path.read_text(encoding="utf-8"))
    validate_private_preflight(private)
    if public.get("schema_version") != "CFB_CFBD_PROVIDER_PREFLIGHT_PUBLIC_V1":
        raise CFBAcquisitionError("PUBLIC_PREFLIGHT_SCHEMA_MISMATCH")
    if public.get("status") != "VERIFIED_BEFORE_FIRST_REPLAY_CALL":
        raise CFBAcquisitionError("PUBLIC_PREFLIGHT_NOT_VERIFIED")
    if public.get("historical_replay_calls_performed") != 0:
        raise CFBAcquisitionError("PUBLIC_PREFLIGHT_REPLAY_CALL_LEAK")
    public_authority = public.get("authority") or {}
    if not public_authority or any(value is not False for value in public_authority.values()):
        raise CFBAcquisitionError("PUBLIC_PREFLIGHT_AUTHORITY_LEAK")
    budget = load_budget(budget_path)
    planned = _int((budget.get("planned_new_calls_upper_bound") or {}).get("total"))
    if fetched_calls > planned:
        raise CFBAcquisitionError("FETCHED_CALL_COUNT_EXCEEDS_FROZEN_PLAN")
    return {
        "schema_version": PUBLIC_MANIFEST_SCHEMA,
        "status": "ACQUISITION_COMPLETE_NO_MODEL_EVALUATION",
        "selection_provenance_class": "RECONSTRUCTED_HISTORICAL_NOT_PIT",
        "feature_value_source_contract": "CFBD_STATS_SEASON_ADVANCED_ENDWEEK_V1",
        "start_season": budget["selection_start_season"],
        "end_season": budget["selection_end_season"],
        "prior_fallback_season": budget["prior_fallback_season"],
        "planned_new_calls_upper_bound": planned,
        "new_calls_performed": fetched_calls,
        "verified_cache_entries_reused": reused_calls,
        "cache_entry_count": len(cache_manifest),
        "cache_manifest": cache_manifest,
        "private_preflight_sha256": _sha_file(private_preflight_path),
        "public_preflight_sha256": _sha_file(public_preflight_path),
        "budget_sha256": _sha_file(budget_path),
        "account_tier_verified_privately": True,
        "monthly_quota_verified_privately": True,
        "remaining_quota_verified_privately": True,
        "weather_entitlement_verified_privately": True,
        "call_plan_fit_verified_privately": True,
        "exact_account_quota_values_published": False,
        "raw_cfbd_responses_persisted_to_public_repository": False,
        "no_2026_forward_outcomes": True,
        "market_data_in_predictive_features": False,
        "authority": _authority(),
    }


__all__ = [
    "CFBAcquisitionError",
    "PUBLIC_MANIFEST_SCHEMA",
    "RequestSpec",
    "acquire_one",
    "acquire_plan",
    "build_public_manifest",
    "build_request_plan",
    "load_budget",
    "project_payload",
    "validate_private_preflight",
]
