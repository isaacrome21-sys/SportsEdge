"""Credential-free planner for MLB historical event-odds replay acquisition.

The planner translates durable PIT observations into exact provider requests for the
markets The Odds API documents directly. It emits request descriptors only: no API
key, network call, quote reconstruction, timestamp rounding, or promotion authority.
Unsupported canonical markets remain explicit source gaps.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from .provider_market_catalog import NO_DIRECT_PROVIDER_KEY, provider_key_for_market

SPORT_KEY = "baseball_mlb"
HISTORICAL_EVENT_ODDS_PATH = "/v4/historical/sports/baseball_mlb/events/{event_id}/odds"
HISTORICAL_EVENTS_PATH = "/v4/historical/sports/baseball_mlb/events"
DEFAULT_BOOKS = ("pinnacle", "draftkings", "fanduel", "betmgm", "williamhill_us")


class MLBHistoricalRequestPlanError(ValueError):
    pass


def _dt(value: Any, field: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        raise MLBHistoricalRequestPlanError(f"{field}_REQUIRED")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MLBHistoricalRequestPlanError(f"{field}_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBHistoricalRequestPlanError(f"{field}_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _books_for_market(policy: Mapping[str, Any], market: str) -> tuple[str, ...]:
    tiers = ((policy.get("benchmark") or {}).get("market_tiers") or {})
    for tier_name, raw in tiers.items():
        if market not in (raw.get("markets") or []):
            continue
        if tier_name == "N_WAY_UNAUTHORIZED_V1":
            return ()
        books = tuple(str(book).strip().lower() for book in (raw.get("book_hierarchy") or []) if str(book).strip())
        if not books:
            raise MLBHistoricalRequestPlanError(f"BOOK_HIERARCHY_EMPTY:{market}")
        return books
    raise MLBHistoricalRequestPlanError(f"MARKET_NOT_IN_REPLAY_POLICY:{market}")


def _event_locator(obs: Mapping[str, Any]) -> dict[str, Any]:
    provider_event_id = str(obs.get("source_event_id") or obs.get("provider_event_id") or "").strip()
    if provider_event_id:
        return {"event_id": provider_event_id, "identity_resolution_required": False}
    home = str(obs.get("source_home_team_name") or obs.get("home_team") or "").strip()
    away = str(obs.get("source_away_team_name") or obs.get("away_team") or "").strip()
    first_pitch = _iso(_dt(obs.get("first_pitch_ts"), "first_pitch_ts"))
    if home and away and home != away:
        return {
            "event_identity": {"home_team": home, "away_team": away, "commence_time": first_pitch},
            "identity_resolution_required": True,
            "identity_lookup": {
                "path": HISTORICAL_EVENTS_PATH,
                "query": {"date": None, "dateFormat": "iso"},
            },
        }
    raise MLBHistoricalRequestPlanError("PROVIDER_EVENT_ID_OR_EXACT_EVENT_IDENTITY_REQUIRED")


def _request_id(observation_key: str, kind: str, requested_at: str, market: str) -> str:
    raw = f"{observation_key}|{kind}|{requested_at}|{market}".encode("utf-8")
    return sha256(raw).hexdigest()[:24]


def build_historical_event_request_plan(
    observations: Iterable[Mapping[str, Any]], *, replay_policy: Mapping[str, Any],
) -> dict[str, Any]:
    """Create exact decision/close request descriptors from PIT observations.

    Decision requests preserve the observation timestamp exactly. Close requests use
    one microsecond before first pitch; the provider may return an earlier 5-minute
    snapshot, and the replay layer judges its actual provider timestamp. The planner
    never rounds or claims that requested time was observed time.
    """
    requests: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    seen_request_ids: set[str] = set()
    seen_observation_keys: set[str] = set()

    for index, raw in enumerate(observations):
        if not isinstance(raw, Mapping):
            raise MLBHistoricalRequestPlanError(f"OBSERVATION_MAPPING_REQUIRED:{index}")
        observation_key = str(raw.get("observation_key") or "").strip()
        if not observation_key or observation_key in seen_observation_keys:
            raise MLBHistoricalRequestPlanError("OBSERVATION_KEY_MISSING_OR_DUPLICATE")
        seen_observation_keys.add(observation_key)
        market = str(raw.get("market") or "").strip().upper()
        provider_market = provider_key_for_market(market)
        books = _books_for_market(replay_policy, market)
        if not books:
            gaps.append({
                "observation_key": observation_key,
                "market": market,
                "reason": "N_WAY_UNAUTHORIZED_V1",
                "request_generated": False,
            })
            continue
        if provider_market is None:
            gaps.append({
                "observation_key": observation_key,
                "market": market,
                "reason": NO_DIRECT_PROVIDER_KEY.get(market, "NO_DIRECT_PROVIDER_MARKET"),
                "request_generated": False,
            })
            continue
        locator = _event_locator(raw)
        decision = _dt(raw.get("quote_ts") or raw.get("decision_ts"), "decision_ts")
        first_pitch = _dt(raw.get("first_pitch_ts"), "first_pitch_ts")
        if not decision < first_pitch:
            raise MLBHistoricalRequestPlanError("DECISION_NOT_PREGAME")
        moments = (
            ("DECISION", decision),
            ("CLOSE", first_pitch - timedelta(microseconds=1)),
        )
        for kind, moment in moments:
            requested_at = _iso(moment)
            request_id = _request_id(observation_key, kind, requested_at, market)
            if request_id in seen_request_ids:
                raise MLBHistoricalRequestPlanError("REQUEST_ID_COLLISION")
            seen_request_ids.add(request_id)
            query = {
                "regions": "us",
                "markets": provider_market,
                "date": requested_at,
                "dateFormat": "iso",
                "oddsFormat": "american",
                "bookmakers": ",".join(books),
            }
            request = {
                "request_id": request_id,
                "observation_key": observation_key,
                "kind": kind,
                "canonical_market": market,
                "provider_market": provider_market,
                "requested_at": requested_at,
                "book_hierarchy": list(books),
                "path_template": HISTORICAL_EVENT_ODDS_PATH,
                "query_without_api_key": query,
                "estimated_max_usage_credits": 10,
                **locator,
            }
            if request.get("identity_resolution_required"):
                request["identity_lookup"]["query"]["date"] = requested_at
            requests.append(request)

    return {
        "schema_version": 1,
        "sport_key": SPORT_KEY,
        "request_count": len(requests),
        "source_gap_count": len(gaps),
        "estimated_max_usage_credits": sum(int(row["estimated_max_usage_credits"]) for row in requests)
        + sum(1 for row in requests if row.get("identity_resolution_required")),
        "requests": requests,
        "source_gaps": gaps,
        "rules": {
            "timestamps_rounded": False,
            "provider_observed_timestamp_must_be_retained": True,
            "provider_may_return_closest_snapshot_at_or_before_request": True,
            "replay_freshness_must_be_judged_from_provider_timestamp": True,
            "credentials_in_plan": False,
            "promotion_authority": False,
        },
    }


def canonical_plan_sha256(plan: Mapping[str, Any]) -> str:
    encoded = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    return sha256(encoded).hexdigest()
