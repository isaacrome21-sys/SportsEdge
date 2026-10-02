"""Research-only automatic CFB usage proxy for same-day prop LEANs.

This module is deliberately outside the frozen CFB prop predictive code surface.
It turns current, market-blind CFBD player usage shares into the strict team-usage
shape consumed by the already-frozen shared-path simulator.

CFBD usage fields are descriptive involvement shares, not snap counts, route
participation, injury status, or red-zone usage.  Missing dimensions therefore
use explicit neutral research assumptions.  Those assumptions are recorded in
the output and make the resulting probability surface research-only.  Nothing
here can activate the bettor-facing CFB prop engine, create promotion authority,
or make an OFFICIAL bet.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sportsedge.odds_keyring import OddsKeyringError, fetch_with_key_failover

from .source import (
    CFBGame,
    _auth,
    _cfbd_url,
    _json_get,
    bind_provider_team,
    build_team_alias_index,
)

SCHEMA_VERSION = "CFB_PROP_RESEARCH_PROXY_LIVE_FEATURES_V1"
SOURCE_CONTRACT = "CFB_CFBD_USAGE_PROXY_V1"
ODDS_EVENTS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/events"
OFFENSIVE_POSITIONS = frozenset({"QB", "RB", "FB", "WR", "TE"})
MAX_START_DELTA_SECONDS = 300


class CFBResearchProxyUsageError(ValueError):
    pass


def _dt(value: Any, code: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBResearchProxyUsageError(code) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBResearchProxyUsageError(code)
    return out.astimezone(timezone.utc)


def _share(value: Any, code: str) -> float:
    if isinstance(value, bool):
        raise CFBResearchProxyUsageError(code)
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBResearchProxyUsageError(code) from exc
    if not isfinite(out) or not 0.0 <= out <= 1.0:
        raise CFBResearchProxyUsageError(code)
    return out


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def fetch_cfbd_player_usage(
    *,
    season: int,
    cfbd_api_key: str,
    opener: Callable = urlopen,
) -> list[dict[str, Any]]:
    """Fetch one season-wide market-blind CFBD player-usage snapshot."""
    payload = _json_get(
        _cfbd_url(
            "/player/usage",
            {"year": int(season), "excludeGarbageTime": "true"},
        ),
        headers=_auth(cfbd_api_key),
        opener=opener,
    )
    if not isinstance(payload, list):
        raise CFBResearchProxyUsageError("CFB_PROXY_USAGE_RESPONSE_NOT_LIST")
    rows = [dict(row) for row in payload if isinstance(row, Mapping)]
    if not rows:
        raise CFBResearchProxyUsageError("CFB_PROXY_USAGE_RESPONSE_EMPTY")
    return rows


def fetch_odds_event_identities(
    *,
    api_keys: Sequence[str],
    opener: Callable = urlopen,
) -> list[dict[str, Any]]:
    """Fetch provider event identity only; no market, line, price, or consensus."""
    def _fetch(key: str) -> Any:
        url = ODDS_EVENTS_URL + "?" + urlencode(
            {"apiKey": key, "dateFormat": "iso"}
        )
        try:
            with opener(
                Request(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "SportsEdge-CFB-Proxy-Usage/1",
                    },
                ),
                timeout=20,
            ) as response:
                raw = response.read()
        except Exception as exc:
            raise CFBResearchProxyUsageError(
                f"CFB_PROXY_EVENT_IDENTITY_FETCH_FAILED:{type(exc).__name__}"
            ) from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CFBResearchProxyUsageError(
                "CFB_PROXY_EVENT_IDENTITY_JSON_INVALID"
            ) from exc
        if not isinstance(payload, list):
            raise CFBResearchProxyUsageError(
                "CFB_PROXY_EVENT_IDENTITY_RESPONSE_NOT_LIST"
            )
        return payload

    try:
        payload = fetch_with_key_failover(api_keys, _fetch).value
    except OddsKeyringError as exc:
        raise CFBResearchProxyUsageError(str(exc)) from exc

    out = []
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        event_id = str(row.get("id") or "").strip()
        home = str(row.get("home_team") or "").strip()
        away = str(row.get("away_team") or "").strip()
        commence = str(row.get("commence_time") or "").strip()
        if not event_id or not home or not away or not commence:
            continue
        _dt(commence, "CFB_PROXY_EVENT_START_INVALID")
        out.append(
            {
                "id": event_id,
                "home_team": home,
                "away_team": away,
                "commence_time": commence,
            }
        )
    if not out:
        raise CFBResearchProxyUsageError("CFB_PROXY_EVENT_IDENTITIES_EMPTY")
    return out


def normalize_cfbd_usage_rows(
    rows: Iterable[Mapping[str, Any]], *, season: int
) -> list[dict[str, Any]]:
    """Validate only the documented CFBD usage identity + overall/pass/rush fields."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        try:
            row_season = int(raw.get("season"))
        except (TypeError, ValueError):
            continue
        if row_season != int(season):
            continue
        player_id = str(raw.get("id") or "").strip()
        name = " ".join(str(raw.get("name") or "").strip().split())
        position = str(raw.get("position") or "").strip().upper()
        team = str(raw.get("team") or "").strip()
        usage = raw.get("usage")
        if (
            not player_id
            or not name
            or position not in OFFENSIVE_POSITIONS
            or not team
            or not isinstance(usage, Mapping)
        ):
            continue
        key = (team.casefold(), player_id)
        if key in seen:
            raise CFBResearchProxyUsageError(
                f"CFB_PROXY_USAGE_PLAYER_DUPLICATE:{team}:{player_id}"
            )
        seen.add(key)
        overall = _share(
            usage.get("overall"),
            f"CFB_PROXY_USAGE_OVERALL_INVALID:{team}:{player_id}",
        )
        pass_usage = _share(
            usage.get("pass"),
            f"CFB_PROXY_USAGE_PASS_INVALID:{team}:{player_id}",
        )
        rush_usage = _share(
            usage.get("rush"),
            f"CFB_PROXY_USAGE_RUSH_INVALID:{team}:{player_id}",
        )
        if max(overall, pass_usage, rush_usage) <= 0:
            continue
        out.append(
            {
                "player_id": player_id,
                "player_name": name,
                "position": position,
                "team": team,
                "usage_overall": overall,
                "usage_pass": pass_usage,
                "usage_rush": rush_usage,
            }
        )
    if not out:
        raise CFBResearchProxyUsageError("CFB_PROXY_USAGE_NORMALIZED_EMPTY")
    return out


def _normalize_weights(
    rows: Sequence[Mapping[str, Any]],
    *,
    field: str,
    eligible: Callable[[Mapping[str, Any]], bool],
    code: str,
) -> dict[str, float]:
    selected = [
        row for row in rows
        if eligible(row) and float(row.get(field, 0.0)) > 0.0
    ]
    total = sum(float(row[field]) for row in selected)
    if total <= 0:
        raise CFBResearchProxyUsageError(code)
    return {
        str(row["player_id"]): float(row[field]) / total for row in selected
    }


def build_team_proxy_usage(
    rows: Sequence[Mapping[str, Any]], *, team: str
) -> dict[str, Any]:
    """Build a neutral-assumption team profile from observed CFBD involvement."""
    candidates = [dict(row) for row in rows if str(row.get("team") or "") == team]
    if not candidates:
        raise CFBResearchProxyUsageError(f"CFB_PROXY_USAGE_TEAM_MISSING:{team}")

    qbs = [row for row in candidates if row["position"] == "QB"]
    if not qbs:
        raise CFBResearchProxyUsageError(f"CFB_PROXY_USAGE_QB_MISSING:{team}")
    qbs.sort(
        key=lambda row: (
            float(row["usage_pass"]),
            float(row["usage_overall"]),
            float(row["usage_rush"]),
            str(row["player_id"]),
        ),
        reverse=True,
    )
    quarterback = qbs[0]
    selected = [
        row for row in candidates
        if row["position"] != "QB" or row["player_id"] == quarterback["player_id"]
    ]

    target_weights = _normalize_weights(
        selected,
        field="usage_pass",
        eligible=lambda row: row["position"] in {"RB", "FB", "WR", "TE"},
        code=f"CFB_PROXY_USAGE_TARGET_POOL_EMPTY:{team}",
    )
    rush_weights = _normalize_weights(
        selected,
        field="usage_rush",
        eligible=lambda row: row["position"] in OFFENSIVE_POSITIONS,
        code=f"CFB_PROXY_USAGE_RUSH_POOL_EMPTY:{team}",
    )

    players = []
    observed = []
    for row in selected:
        player_id = str(row["player_id"])
        target_share = float(target_weights.get(player_id, 0.0))
        rush_share = float(rush_weights.get(player_id, 0.0))
        is_qb = player_id == quarterback["player_id"]
        if not is_qb and target_share <= 0 and rush_share <= 0:
            continue
        players.append(
            {
                "player_id": player_id,
                "player_name": row["player_name"],
                "position": row["position"],
                "team": team,
                "active": True,
                # Neutral research assumptions. Do not relabel these as observed.
                "snap_share": 1.0,
                "route_participation": (
                    1.0 if (not is_qb and target_share > 0) else 0.0
                ),
                "target_share": target_share,
                "rush_share": rush_share,
                "red_zone_share": 1.0,
            }
        )
        observed.append(
            {
                "player_id": player_id,
                "usage_overall": row["usage_overall"],
                "usage_pass": row["usage_pass"],
                "usage_rush": row["usage_rush"],
            }
        )

    if len(players) < 2:
        raise CFBResearchProxyUsageError(
            f"CFB_PROXY_USAGE_PLAYER_POOL_TOO_SMALL:{team}"
        )
    return {
        "quarterback_id": str(quarterback["player_id"]),
        "players": players,
        "proxy_provenance": {
            "source": "CFBD_PLAYER_USAGE",
            "observed_fields": [
                "player_id",
                "player_name",
                "position",
                "team",
                "usage.overall",
                "usage.pass",
                "usage.rush",
            ],
            "derived_fields": [
                "target_share=NORMALIZED_NON_QB_USAGE_PASS",
                "rush_share=NORMALIZED_OFFENSIVE_USAGE_RUSH",
                "quarterback_id=MAX_QB_USAGE_PASS",
            ],
            "neutral_assumption_fields": [
                "active=True_FROM_CURRENT_USAGE_PRESENCE_NOT_INJURY_CONFIRMATION",
                "snap_share=1.0_NOT_OBSERVED_SNAP_RATE",
                "route_participation=1.0_FOR_TARGET_ELIGIBLE_NOT_OBSERVED_ROUTE_RATE",
                "red_zone_share=1.0_NO_PLAYER_SPECIFIC_RED_ZONE_TILT",
            ],
            "observed_usage": observed,
        },
    }


def _bind_event(
    game: CFBGame,
    *,
    events: Sequence[Mapping[str, Any]],
    alias_index: Mapping[str, str],
) -> Mapping[str, Any]:
    game_start = _dt(game.start_ts, "CFB_PROXY_GAME_START_INVALID")
    matches = []
    for event in events:
        if not isinstance(event, Mapping):
            continue
        try:
            home = bind_provider_team(
                str(event.get("home_team") or ""), alias_index
            )
            away = bind_provider_team(
                str(event.get("away_team") or ""), alias_index
            )
            start = _dt(
                event.get("commence_time"), "CFB_PROXY_EVENT_START_INVALID"
            )
        except Exception:
            continue
        if home != game.home_team or away != game.away_team:
            continue
        if abs((start - game_start).total_seconds()) > MAX_START_DELTA_SECONDS:
            continue
        matches.append(event)
    if len(matches) != 1:
        raise CFBResearchProxyUsageError(
            f"CFB_PROXY_EVENT_IDENTITY_COUNT_INVALID:{game.game_id}:{len(matches)}"
        )
    return matches[0]


def build_research_proxy_live_features(
    *,
    games: Sequence[CFBGame],
    team_rows: Sequence[Mapping[str, Any]],
    player_usage_rows: Sequence[Mapping[str, Any]],
    provider_events: Sequence[Mapping[str, Any]],
    season: int,
    now: datetime,
    horizon_hours: float = 24.0,
    allowed_model_teams: set[str] | None = None,
) -> dict[str, Any]:
    """Assemble a same-day research proxy snapshot, fail-closing per game."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise CFBResearchProxyUsageError("CFB_PROXY_NOW_TIMEZONE_REQUIRED")
    current = now.astimezone(timezone.utc)
    if not isfinite(float(horizon_hours)) or float(horizon_hours) <= 0:
        raise CFBResearchProxyUsageError("CFB_PROXY_HORIZON_INVALID")
    normalized = normalize_cfbd_usage_rows(player_usage_rows, season=int(season))
    alias_index = build_team_alias_index(team_rows)
    if not alias_index:
        raise CFBResearchProxyUsageError("CFB_PROXY_TEAM_ALIAS_INDEX_EMPTY")

    included = []
    blocked = []
    for game in games:
        start = _dt(game.start_ts, "CFB_PROXY_GAME_START_INVALID")
        lead = (start - current).total_seconds()
        if lead <= 0 or lead > float(horizon_hours) * 3600:
            continue
        if allowed_model_teams is not None and (
            game.home_team not in allowed_model_teams
            or game.away_team not in allowed_model_teams
        ):
            blocked.append(
                {
                    "game_id": game.game_id,
                    "reason": "CFB_PROXY_MODEL_TEAM_PROFILE_MISSING",
                }
            )
            continue
        try:
            event = _bind_event(game, events=provider_events, alias_index=alias_index)
            home_usage = build_team_proxy_usage(normalized, team=game.home_team)
            away_usage = build_team_proxy_usage(normalized, team=game.away_team)
        except CFBResearchProxyUsageError as exc:
            blocked.append({"game_id": game.game_id, "reason": str(exc)})
            continue
        included.append(
            {
                "game_id": game.game_id,
                "provider_event_id": str(event["id"]),
                "game_start_ts": start.isoformat(),
                "home_team": game.home_team,
                "away_team": game.away_team,
                "provider_home_team": str(event["home_team"]),
                "provider_away_team": str(event["away_team"]),
                "home_usage": home_usage,
                "away_usage": away_usage,
            }
        )

    if not included:
        raise CFBResearchProxyUsageError(
            "CFB_PROXY_NO_RUNNABLE_SAME_DAY_GAMES"
        )

    source_payload = {
        "contract": SOURCE_CONTRACT,
        "season": int(season),
        "retrieved_at": current.isoformat(),
        "games": [
            {
                "game_id": row["game_id"],
                "provider_event_id": row["provider_event_id"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "game_start_ts": row["game_start_ts"],
                "home_usage_observed": row["home_usage"]["proxy_provenance"]["observed_usage"],
                "away_usage_observed": row["away_usage"]["proxy_provenance"]["observed_usage"],
            }
            for row in included
        ],
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "sport": "CFB",
        "asof_ts": current.isoformat(),
        "source_manifest_sha256": _canonical_sha(source_payload),
        "input_manifest": source_payload,
        "games": included,
        "blocked_games": blocked,
        "governance": {
            "research_only": True,
            "research_proxy_usage": True,
            "market_fields_consumed": False,
            "sportsbook_event_identity_only": True,
            "sportsbook_prices_consumed": False,
            "usage_synthesized": True,
            "observed_cfbd_usage_fields": [
                "usage.overall",
                "usage.pass",
                "usage.rush",
            ],
            "neutral_assumptions_present": True,
            "injury_status_confirmed": False,
            "true_snap_share_observed": False,
            "true_route_participation_observed": False,
            "true_red_zone_share_observed": False,
            "production_eligible": False,
            "promotion_authority": False,
            "official_eligible": False,
        },
    }


__all__ = [
    "CFBResearchProxyUsageError",
    "SCHEMA_VERSION",
    "SOURCE_CONTRACT",
    "build_research_proxy_live_features",
    "build_team_proxy_usage",
    "fetch_cfbd_player_usage",
    "fetch_odds_event_identities",
    "normalize_cfbd_usage_rows",
]
