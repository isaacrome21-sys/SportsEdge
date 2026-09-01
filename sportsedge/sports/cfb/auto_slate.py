from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ...source_lineage import canonical_json_sha256
from .context_autopull import CFBContextError, ContextObservation, run_context_mode
from .source import CFBD_BASE


def _utc(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        out = value
    else:
        text = str(value or "").strip().replace("Z", "+00:00")
        if not text:
            raise CFBContextError(f"{field} required")
        try:
            out = datetime.fromisoformat(text)
        except ValueError as exc:
            raise CFBContextError(f"{field} invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBContextError(f"{field} timezone required")
    return out.astimezone(timezone.utc)


def _fetch_fbs_season_games(*, season: int, cfbd_api_key: str,
                            opener: Callable = urlopen) -> tuple[list[dict[str, Any]], str, str]:
    key = str(cfbd_api_key or "").strip()
    if not key:
        raise CFBContextError("CFBD_API_KEY_REQUIRED")
    query = urlencode({"year": int(season), "seasonType": "regular", "classification": "fbs"})
    uri = f"{CFBD_BASE}/games?{query}"
    req = Request(uri, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with opener(req, timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        raise CFBContextError("CFBD FBS schedule fetch failed") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise CFBContextError("CFBD FBS schedule JSON invalid") from exc
    if not isinstance(data, list):
        raise CFBContextError("CFBD FBS schedule not list")
    return [dict(row) for row in data if isinstance(row, Mapping)], sha256(raw).hexdigest(), uri


def _game_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    game_id = str(row.get("id") or "").strip()
    if not game_id:
        raise CFBContextError("CFBD game id missing")
    kickoff = _utc(row.get("startDate"), "startDate")
    home = str(row.get("homeTeam") or "").strip()
    away = str(row.get("awayTeam") or "").strip()
    if not home or not away or home == away:
        raise CFBContextError(f"CFBD game team identity invalid:{game_id}")
    # The upstream request itself is classification=fbs. Never admit a caller-supplied
    # FCS row into this lane if a fixture/provider accidentally includes classification.
    classification = str(row.get("classification") or "fbs").strip().lower()
    if classification not in {"fbs", ""}:
        raise CFBContextError(f"NON_FBS_GAME_BLOCKED:{game_id}:{classification}")
    return {
        "game_id": game_id,
        "season": int(row.get("season")),
        "week": int(row.get("week")),
        "kickoff_ts": kickoff.isoformat(),
        "home_team": home,
        "away_team": away,
        "neutral_site": bool(row.get("neutralSite", False)),
        "venue": str(row.get("venue") or "").strip() or None,
        "venue_id": row.get("venueId"),
        "home_conference": str(row.get("homeConference") or "").strip() or None,
        "away_conference": str(row.get("awayConference") or "").strip() or None,
        "subdivision": "FBS",
    }


def discover_cfb_auto_games(*, as_of: Any, cfbd_api_key: str,
                            season: int | None = None, min_lead_minutes: int = 0,
                            horizon_minutes: int = 7 * 24 * 60,
                            opener: Callable = urlopen) -> dict[str, Any]:
    """Discover the upcoming FBS slate without an operator-maintained game list."""
    pit = _utc(as_of, "as_of")
    if isinstance(min_lead_minutes, bool) or not isinstance(min_lead_minutes, int):
        raise CFBContextError("min_lead_minutes must be integer")
    if isinstance(horizon_minutes, bool) or not isinstance(horizon_minutes, int):
        raise CFBContextError("horizon_minutes must be integer")
    if min_lead_minutes < 0 or horizon_minutes < min_lead_minutes:
        raise CFBContextError("AUTO slate window invalid")
    resolved_season = int(season if season is not None else pit.year)
    rows, digest, uri = _fetch_fbs_season_games(season=resolved_season, cfbd_api_key=cfbd_api_key, opener=opener)
    lower, upper = pit + timedelta(minutes=min_lead_minutes), pit + timedelta(minutes=horizon_minutes)
    games: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        game = _game_from_row(row)
        kickoff = _utc(game["kickoff_ts"], "kickoff_ts")
        if not lower <= kickoff <= upper:
            continue
        if game["game_id"] in seen:
            raise CFBContextError(f"duplicate CFB game_id:{game['game_id']}")
        seen.add(game["game_id"])
        games.append(game)
    games.sort(key=lambda item: (item["kickoff_ts"], item["game_id"]))
    return {
        "schema_version": 1, "sport": "CFB", "subdivision": "FBS",
        "as_of_utc": pit.isoformat(), "season": resolved_season,
        "min_lead_minutes": min_lead_minutes, "horizon_minutes": horizon_minutes,
        "schedule_source_uri": uri, "schedule_source_sha256": digest, "games": games,
    }


def _static_provider(*, payload: Mapping[str, Any], source_uri: str,
                     source_sha256: str, source_name: str, observed_at: datetime) -> Callable:
    frozen = dict(payload)
    def provider(game_id: str, pit: datetime) -> Mapping[str, Any]:
        return {"status": "AVAILABLE", "payload": frozen, "source_name": source_name,
                "source_uri": source_uri, "source_sha256": source_sha256,
                "observed_at": min(observed_at, pit)}
    return provider


def build_cfb_auto_context_slate(*, as_of: Any, cfbd_api_key: str,
                                 season: int | None = None, mode: str = "AUTO",
                                 min_lead_minutes: int = 0,
                                 horizon_minutes: int = 7 * 24 * 60,
                                 provider_factory: Callable[[Mapping[str, Any], datetime], Mapping[str, Callable]] | None = None,
                                 manual_observations_by_game: Mapping[str, Iterable[ContextObservation]] | None = None,
                                 opener: Callable = urlopen) -> dict[str, Any]:
    requested = str(mode or "").strip().upper()
    if requested not in {"AUTO", "HYBRID"}:
        raise CFBContextError("AUTO slate mode must be AUTO or HYBRID")
    pit = _utc(as_of, "as_of")
    plan = discover_cfb_auto_games(as_of=pit, cfbd_api_key=cfbd_api_key, season=season,
                                   min_lead_minutes=min_lead_minutes,
                                   horizon_minutes=horizon_minutes, opener=opener)
    manual = dict(manual_observations_by_game or {})
    bundles: list[dict[str, Any]] = []
    for game in plan["games"]:
        providers: dict[str, Callable] = {}
        identity_payload = {key: game[key] for key in (
            "game_id", "season", "week", "kickoff_ts", "home_team", "away_team",
            "neutral_site", "venue", "venue_id", "home_conference", "away_conference", "subdivision")}
        providers["game_metadata"] = _static_provider(
            payload=identity_payload, source_uri=plan["schedule_source_uri"],
            source_sha256=plan["schedule_source_sha256"], source_name="CFBD_FBS_SCHEDULE",
            observed_at=pit)
        if game.get("venue") or game.get("venue_id"):
            providers["venue_weather"] = _static_provider(
                payload={"venue": game.get("venue"), "venue_id": game.get("venue_id"),
                         "weather": None, "weather_status": "UNAVAILABLE"},
                source_uri=plan["schedule_source_uri"], source_sha256=plan["schedule_source_sha256"],
                source_name="CFBD_FBS_VENUE", observed_at=pit)
        if provider_factory is not None:
            extra = dict(provider_factory(game, pit) or {})
            unknown = set(extra) - {
                "venue_weather", "rest_travel", "injury_availability", "depth_chart_role",
                "team_efficiency_pace", "defensive_matchup", "coaching_tendencies",
                "player_usage_workload", "workload_leash"}
            if unknown:
                raise CFBContextError("unknown auto provider classes:" + ",".join(sorted(unknown)))
            providers.update(extra)
        bundles.append(run_context_mode(
            mode=requested, game_id=game["game_id"], as_of=pit, providers=providers,
            manual_observations=list(manual.get(game["game_id"], ())),
        ))
    payload = {
        "schema_version": 1, "sport": "CFB", "subdivision": "FBS",
        "collection_mode": requested, "as_of_utc": plan["as_of_utc"],
        "schedule_source_sha256": plan["schedule_source_sha256"],
        "game_count": len(bundles), "games": bundles,
        "model_p_eligible": False, "truth_gate_eligible": False,
        "validation_status": "UNVALIDATED_CONTEXT_SIDE_CAR",
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload
