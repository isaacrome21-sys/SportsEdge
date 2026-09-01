from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import csv
from hashlib import sha256
import io
import json
import math
from statistics import mean
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .runtime import parse_timestamp
from .source_lineage import canonical_json_sha256
from .v7_sources import fetch_mlb_live_feed, source_manifest

SAVANT_CSV = "https://baseballsavant.mlb.com/statcast_search/csv"
MLB_STATSAPI = "https://statsapi.mlb.com/api/v1"


class MLBObjectiveDepthError(RuntimeError):
    pass


def _utc(value: Any, field: str) -> datetime:
    try:
        out = value if isinstance(value, datetime) else parse_timestamp(value)
    except Exception as exc:
        raise MLBObjectiveDepthError(f"{field} invalid") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise MLBObjectiveDepthError(f"{field} timezone required")
    return out.astimezone(timezone.utc)


def _float(value: Any) -> float | None:
    if value in (None, "", "None", "nan", "NaN"):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _int(value: Any) -> int | None:
    value = _float(value)
    return None if value is None else int(value)


def fetch_statcast_context_rows(
    *, start_date: date, end_date: date, opener: Callable = urlopen,
) -> tuple[list[dict[str, str]], str, str]:
    """Fetch a bounded pitch-level Savant window with exact-byte provenance."""
    if end_date < start_date:
        raise MLBObjectiveDepthError("Statcast end before start")
    params = {
        "all": "true", "type": "details", "player_type": "batter",
        "game_date_gt": start_date.isoformat(), "game_date_lt": end_date.isoformat(),
    }
    uri = f"{SAVANT_CSV}?{urlencode(params)}"
    req = Request(uri, headers={
        "Accept": "text/csv,*/*", "User-Agent": "SportsEdge-MLB-Context/1.0",
        "Referer": "https://baseballsavant.mlb.com/",
    })
    try:
        with opener(req, timeout=60) as response:
            raw = response.read()
    except Exception as exc:
        raise MLBObjectiveDepthError("STATCAST_CONTEXT_FETCH_FAILED") from exc
    if not raw:
        raise MLBObjectiveDepthError("STATCAST_CONTEXT_EMPTY")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))
        fields = set(reader.fieldnames or ())
        rows = [dict(row) for row in reader]
    except Exception as exc:
        raise MLBObjectiveDepthError("STATCAST_CONTEXT_CSV_INVALID") from exc
    required = {"game_date", "batter", "pitcher", "events", "description"}
    if not required <= fields:
        raise MLBObjectiveDepthError("STATCAST_CONTEXT_SCHEMA_UNSUPPORTED")
    return rows, uri, sha256(raw).hexdigest()


_SWINGS = frozenset({
    "swinging_strike", "swinging_strike_blocked", "foul", "foul_tip",
    "hit_into_play", "hit_into_play_no_out", "hit_into_play_score",
})
_WHIFFS = frozenset({"swinging_strike", "swinging_strike_blocked"})
_TAKES = frozenset({"ball", "blocked_ball", "called_strike"})


def _borderline_take(row: Mapping[str, Any]) -> bool:
    if str(row.get("description") or "") not in _TAKES:
        return False
    x = _float(row.get("plate_x"))
    z = _float(row.get("plate_z"))
    bot = _float(row.get("sz_bot"))
    top = _float(row.get("sz_top"))
    if None in (x, z, bot, top) or top <= bot:
        return False
    # A transparent receiving proxy only: 0.15 ft band around rule-zone edges.
    near_side = 0.80 <= abs(x) <= 1.10 and bot - 0.15 <= z <= top + 0.15
    near_vertical = abs(x) <= 1.10 and (bot - 0.15 <= z <= bot + 0.15 or top - 0.15 <= z <= top + 0.15)
    return bool(near_side or near_vertical)


def summarize_statcast_window(
    rows: Iterable[Mapping[str, Any]], *, entity_ids: Iterable[int] | None = None,
) -> dict[str, Any]:
    """Build pitch-level rolling skill detail without market-derived inputs."""
    selected = None if entity_ids is None else {int(x) for x in entity_ids}
    batters: dict[int, dict[str, Any]] = defaultdict(lambda: {
        "pitches":0,"swings":0,"whiffs":0,"chase_opportunities":0,"chase_swings":0,
        "bbe":0,"ev":[],"xwoba":[],"xba":[],"xslg":[],"barrels":0,
    })
    pitchers: dict[int, dict[str, Any]] = defaultdict(lambda: {
        "pitches":0,"swings":0,"whiffs":0,"chase_opportunities":0,"chase_swings":0,
        "release_speed":[],"spin":[],"pitch_types":defaultdict(int),"bbe":0,"ev_allowed":[],"xwoba_allowed":[],
    })
    catchers: dict[int, dict[str, Any]] = defaultdict(lambda: {
        "borderline_takes":0,"borderline_called_strikes":0,"cs":0,"sb":0,"passed_balls":0,
    })
    for raw in rows:
        batter, pitcher, catcher = _int(raw.get("batter")), _int(raw.get("pitcher")), _int(raw.get("fielder_2"))
        desc = str(raw.get("description") or "").strip()
        zone = _int(raw.get("zone"))
        swing = desc in _SWINGS
        whiff = desc in _WHIFFS
        chase_opp = zone in {11,12,13,14}
        ev = _float(raw.get("launch_speed"))
        xwoba = _float(raw.get("estimated_woba_using_speedangle"))
        xba = _float(raw.get("estimated_ba_using_speedangle"))
        xslg = _float(raw.get("estimated_slg_using_speedangle"))
        lsa = _int(raw.get("launch_speed_angle"))
        if batter is not None and (selected is None or batter in selected):
            a = batters[batter]; a["pitches"] += 1; a["swings"] += int(swing); a["whiffs"] += int(whiff)
            a["chase_opportunities"] += int(chase_opp); a["chase_swings"] += int(chase_opp and swing)
            if ev is not None: a["bbe"] += 1; a["ev"].append(ev); a["barrels"] += int(lsa == 6)
            if xwoba is not None: a["xwoba"].append(xwoba)
            if xba is not None: a["xba"].append(xba)
            if xslg is not None: a["xslg"].append(xslg)
        if pitcher is not None and (selected is None or pitcher in selected):
            p = pitchers[pitcher]; p["pitches"] += 1; p["swings"] += int(swing); p["whiffs"] += int(whiff)
            p["chase_opportunities"] += int(chase_opp); p["chase_swings"] += int(chase_opp and swing)
            velo, spin = _float(raw.get("release_speed")), _float(raw.get("release_spin_rate"))
            if velo is not None: p["release_speed"].append(velo)
            if spin is not None: p["spin"].append(spin)
            pitch_type = str(raw.get("pitch_type") or "").strip()
            if pitch_type: p["pitch_types"][pitch_type] += 1
            if ev is not None: p["bbe"] += 1; p["ev_allowed"].append(ev)
            if xwoba is not None: p["xwoba_allowed"].append(xwoba)
        if catcher is not None and (selected is None or catcher in selected):
            c = catchers[catcher]
            if _borderline_take(raw):
                c["borderline_takes"] += 1
                c["borderline_called_strikes"] += int(desc == "called_strike")
            event = str(raw.get("events") or "").strip()
            c["cs"] += int(event.startswith("caught_stealing"))
            c["sb"] += int(event.startswith("stolen_base"))
            c["passed_balls"] += int(event == "passed_ball")

    def rate(n, d): return None if not d else round(float(n) / float(d), 6)
    def avg(xs): return None if not xs else round(float(mean(xs)), 4)
    batter_out = {}
    for entity, a in batters.items():
        batter_out[str(entity)] = {
            "pitches":a["pitches"], "swing_rate":rate(a["swings"],a["pitches"]),
            "whiff_per_swing":rate(a["whiffs"],a["swings"]), "chase_rate":rate(a["chase_swings"],a["chase_opportunities"]),
            "bbe":a["bbe"], "avg_exit_velocity":avg(a["ev"]), "barrel_rate":rate(a["barrels"],a["bbe"]),
            "xwoba_contact":avg(a["xwoba"]), "xba_contact":avg(a["xba"]), "xslg_contact":avg(a["xslg"]),
        }
    pitcher_out = {}
    for entity, p in pitchers.items():
        total = sum(p["pitch_types"].values())
        pitcher_out[str(entity)] = {
            "pitches":p["pitches"], "whiff_per_swing":rate(p["whiffs"],p["swings"]),
            "chase_rate":rate(p["chase_swings"],p["chase_opportunities"]), "avg_release_speed":avg(p["release_speed"]),
            "avg_spin_rate":avg(p["spin"]), "pitch_mix":{k:rate(v,total) for k,v in sorted(p["pitch_types"].items())},
            "bbe":p["bbe"], "avg_exit_velocity_allowed":avg(p["ev_allowed"]), "xwoba_contact_allowed":avg(p["xwoba_allowed"]),
        }
    catcher_out = {}
    for entity, c in catchers.items():
        catcher_out[str(entity)] = {
            "borderline_takes":c["borderline_takes"],
            "borderline_called_strike_rate_proxy":rate(c["borderline_called_strikes"],c["borderline_takes"]),
            "caught_stealing_events":c["cs"], "stolen_base_events":c["sb"], "passed_ball_events":c["passed_balls"],
            "framing_metric_status":"RECEIVING_PROXY_NOT_OFFICIAL_FRAMING_RUNS",
        }
    return {"batters":batter_out,"pitchers":pitcher_out,"catchers":catcher_out}


def _json_snapshot(uri: str, *, opener: Callable = urlopen) -> tuple[Any, str]:
    try:
        with opener(Request(uri, headers={"Accept":"application/json","User-Agent":"SportsEdge/1.0"}), timeout=30) as response:
            raw = response.read()
    except Exception as exc:
        raise MLBObjectiveDepthError("MLB_STATSAPI_FETCH_FAILED") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MLBObjectiveDepthError("MLB_STATSAPI_JSON_INVALID") from exc
    return payload, sha256(raw).hexdigest()


def _team_ids(live: Mapping[str, Any]) -> tuple[int | None, int | None]:
    teams = ((live.get("gameData") or {}).get("teams") or {})
    return _int((teams.get("home") or {}).get("id")), _int((teams.get("away") or {}).get("id"))


def _player_ids(live: Mapping[str, Any]) -> set[int]:
    teams = (((live.get("liveData") or {}).get("boxscore") or {}).get("teams") or {})
    out: set[int] = set()
    for side in ("home","away"):
        for player in ((teams.get(side) or {}).get("players") or {}).values():
            pid = _int(((player or {}).get("person") or {}).get("id"))
            if pid is not None: out.add(pid)
    return out


def _recent_team_feeds(
    *, team_id: int, as_of: datetime, days: int = 4, opener: Callable = urlopen,
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]]]:
    end = as_of.date() - timedelta(days=1)
    start = end - timedelta(days=days-1)
    uri = f"{MLB_STATSAPI}/schedule?" + urlencode({
        "sportId":1,"teamId":int(team_id),"startDate":start.isoformat(),"endDate":end.isoformat(),
    })
    schedule, schedule_sha = _json_snapshot(uri, opener=opener)
    game_pks: list[int] = []
    for d in (schedule.get("dates") or []) if isinstance(schedule, Mapping) else []:
        for game in d.get("games") or []:
            if str(((game.get("status") or {}).get("abstractGameState") or "")).lower() == "final":
                pk = _int(game.get("gamePk"))
                if pk is not None: game_pks.append(pk)
    feeds, manifests = [], [{"provider":"MLB_STATSAPI_SCHEDULE","source_url":uri,"payload_sha256":schedule_sha}]
    for pk in game_pks:
        snap = fetch_mlb_live_feed(pk, opener=opener, retrieved_at=as_of)
        if isinstance(snap.payload, Mapping): feeds.append(snap.payload)
        manifests.append(source_manifest(snap))
    return feeds, manifests


def _pitcher_usage_from_feed(feed: Mapping[str, Any], team_id: int) -> list[dict[str, Any]]:
    game_date = str(((feed.get("gameData") or {}).get("datetime") or {}).get("originalDate") or "")
    box = (((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {})
    teams = ((feed.get("gameData") or {}).get("teams") or {})
    side = None
    for candidate in ("home","away"):
        if _int((teams.get(candidate) or {}).get("id")) == int(team_id): side = candidate; break
    if side is None: return []
    team_box = box.get(side) or {}
    pitcher_order = [int(x) for x in team_box.get("pitchers") or []]
    players = team_box.get("players") or {}
    out = []
    for idx, pid in enumerate(pitcher_order):
        row = players.get(f"ID{pid}") or {}
        pitching = ((row.get("stats") or {}).get("pitching") or {})
        out.append({
            "pitcher_id":pid,"game_date":game_date,"starter":idx==0,
            "pitches_thrown":_int(pitching.get("pitchesThrown")),
            "innings_pitched":pitching.get("inningsPitched"),
            "batters_faced":_int(pitching.get("battersFaced")),
        })
    return out


def summarize_recent_pitching_usage(feeds: Iterable[Mapping[str, Any]], *, team_id: int, as_of: datetime) -> dict[str, Any]:
    grouped: dict[int,list[dict[str,Any]]] = defaultdict(list)
    for feed in feeds:
        for row in _pitcher_usage_from_feed(feed, team_id): grouped[int(row["pitcher_id"])].append(row)
    relievers, starters = {}, {}
    for pid, rows in grouped.items():
        rows.sort(key=lambda r:r["game_date"])
        dates = sorted({r["game_date"] for r in rows if r["game_date"]})
        payload = {
            "appearances":len(rows),"dates":dates,"pitches_thrown":sum(r["pitches_thrown"] or 0 for r in rows),
            "last_pitches_thrown":rows[-1]["pitches_thrown"],"last_game_date":rows[-1]["game_date"],
            "pitched_consecutive_calendar_days": any(
                (date.fromisoformat(b)-date.fromisoformat(a)).days == 1 for a,b in zip(dates,dates[1:])
            ) if len(dates)>1 else False,
        }
        target = starters if all(r["starter"] for r in rows) else relievers
        target[str(pid)] = payload
    return {
        "team_id":int(team_id),"lookback_end":(as_of.date()-timedelta(days=1)).isoformat(),
        "relievers":relievers,"starters":starters,"high_leverage_status":"UNAVAILABLE_FROM_BOXSCORE_ONLY",
    }


def fetch_team_fielding_fallback(*, team_id: int, season: int, opener: Callable = urlopen) -> tuple[dict[str, Any] | None, str, str]:
    uri = f"{MLB_STATSAPI}/teams/{int(team_id)}/stats?" + urlencode({"stats":"season","group":"fielding","season":int(season)})
    payload, digest = _json_snapshot(uri, opener=opener)
    splits = []
    try:
        splits = payload["stats"][0]["splits"]
    except Exception:
        pass
    stat = dict((splits[0] or {}).get("stat") or {}) if splits else None
    if not stat: return None, uri, digest
    return {
        "team_id":int(team_id),"fielding_percentage":stat.get("fielding"),"errors":stat.get("errors"),
        "assists":stat.get("assists"),"putouts":stat.get("putOuts"),"double_plays":stat.get("doublePlays"),
        "oaa_status":"UNAVAILABLE_IN_STATSAPI_FIELDING_FALLBACK",
    }, uri, digest


def build_mlb_objective_depth_providers(*, opener: Callable = urlopen, statcast_days: int = 30) -> dict[str, Callable]:
    """Return cached objective providers for the MLB hybrid context lane."""
    statcast_cache: dict[str, tuple[dict[str,Any],str,str]] = {}
    recent_cache: dict[tuple[int,str], tuple[list[Mapping[str,Any]],list[dict[str,Any]]]] = {}
    fielding_cache: dict[tuple[int,int], tuple[dict[str,Any]|None,str,str]] = {}

    def statcast(as_of: datetime, live: Mapping[str,Any]):
        key = as_of.date().isoformat()
        if key not in statcast_cache:
            end = as_of.date() - timedelta(days=1)
            start = end - timedelta(days=int(statcast_days)-1)
            rows, uri, digest = fetch_statcast_context_rows(start_date=start,end_date=end,opener=opener)
            statcast_cache[key] = (summarize_statcast_window(rows, entity_ids=_player_ids(live)),uri,digest)
        return statcast_cache[key]

    def bullpen(game_pk:int, as_of:datetime, live:Mapping[str,Any]):
        home,away = _team_ids(live); teams = [x for x in (home,away) if x is not None]
        result, manifests = {}, []
        for team in teams:
            key=(team,as_of.date().isoformat())
            if key not in recent_cache: recent_cache[key]=_recent_team_feeds(team_id=team,as_of=as_of,opener=opener)
            feeds, m = recent_cache[key]; manifests.extend(m)
            result[str(team)] = summarize_recent_pitching_usage(feeds,team_id=team,as_of=as_of)["relievers"]
        return {"teams":result,"source_manifests":manifests,"lookback_days":4}

    def workload(game_pk:int, as_of:datetime, live:Mapping[str,Any]):
        home,away = _team_ids(live); result, manifests = {}, []
        for team in [x for x in (home,away) if x is not None]:
            key=(team,as_of.date().isoformat())
            if key not in recent_cache: recent_cache[key]=_recent_team_feeds(team_id=team,as_of=as_of,opener=opener)
            feeds,m=recent_cache[key]; manifests.extend(m)
            result[str(team)] = summarize_recent_pitching_usage(feeds,team_id=team,as_of=as_of)
        return {"teams":result,"source_manifests":manifests,"lookback_days":4}

    def platoon(game_pk:int,as_of:datetime,live:Mapping[str,Any]):
        summary,uri,digest=statcast(as_of,live)
        return {"batters":summary["batters"],"pitchers":summary["pitchers"],"window_days":statcast_days,"source_uri":uri,"source_sha256":digest}

    def catcher(game_pk:int,as_of:datetime,live:Mapping[str,Any]):
        summary,uri,digest=statcast(as_of,live)
        return {"catchers":summary["catchers"],"window_days":statcast_days,"source_uri":uri,"source_sha256":digest,
                "metric_scope":"BORDERLINE_CALLED_STRIKE_RECEIVING_PROXY+SB_CS_PB_EVENTS"}

    def defense(game_pk:int,as_of:datetime,live:Mapping[str,Any]):
        home,away=_team_ids(live); season=int(((live.get("gameData") or {}).get("game") or {}).get("season") or as_of.year)
        teams={}; manifests=[]
        for team in [x for x in (home,away) if x is not None]:
            key=(team,season)
            if key not in fielding_cache: fielding_cache[key]=fetch_team_fielding_fallback(team_id=team,season=season,opener=opener)
            payload,uri,digest=fielding_cache[key]
            teams[str(team)]=payload; manifests.append({"source_url":uri,"payload_sha256":digest,"provider":"MLB_STATSAPI_FIELDING"})
        return {"teams":teams,"source_manifests":manifests,"defense_scope":"OFFICIAL_FIELDING_FALLBACK_NO_OAA"}

    return {"bullpen":bullpen,"workload":workload,"platoon":platoon,"catcher_framing":catcher,"defense":defense}
