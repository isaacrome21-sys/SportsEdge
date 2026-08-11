"""Native MLB-history construction for the validated Hits feature contract.

The formulas and cutoffs mirror the historical fixture builder exactly:
- batter cumulative H/PA shrunk with SH_B=100 toward LEAGUE_HIT
- opposing starter cumulative H/BFP from starts only, shrunk with SH_P=200
- batter PA workload pool from actual prior starts only, last 30 starts
- all statistics are restricted to MLB regular-season games on dates strictly
  before the target officialDate. Same-date games are intentionally excluded.

No sportsbook, weather, BvP, Statcast, or public-model data enters this module.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://statsapi.mlb.com/api/v1"
FIRST_SEASON = 2021
SH_B = 100
SH_P = 200
LEAGUE_HIT = 0.2258248698094686
LEAGUE_PH = 0.2258
MIN_STARTS = 5
PA_POOL_LIMIT = 30
FEATURE_TTL_SECONDS = 3600
PROVIDER = "MLB_STATSAPI_HISTORY"


class MLBHitsFeatureError(RuntimeError):
    pass


class JsonHistoryCache:
    """Optional content cache for immutable/prior-date MLB responses."""
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory) if directory else None
        if self.directory:
            self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path | None:
        if self.directory is None:
            return None
        return self.directory / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")

    def get(self, url: str) -> Any | None:
        p = self._path(url)
        if p is None or not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception as exc:
            raise MLBHitsFeatureError("HISTORY_CACHE_CORRUPT") from exc

    def put(self, url: str, value: Any) -> None:
        p = self._path(url)
        if p is None:
            return
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(raw)
        tmp.replace(p)


def _url(path: str, params: Mapping[str, Any] | None = None) -> str:
    out = BASE + path
    if params:
        out += "?" + urlencode(dict(params))
    return out


def _get_json(url: str, *, opener: Callable = urlopen, cache: JsonHistoryCache | None = None) -> Any:
    if cache:
        hit = cache.get(url)
        if hit is not None:
            return hit
    try:
        with opener(Request(url, headers={"Accept": "application/json"}), timeout=15) as response:
            value = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise MLBHitsFeatureError("MLB_HISTORY_FETCH_FAILED") from exc
    if cache:
        cache.put(url, value)
    return value


def _target_date(value: str | date) -> date:
    if isinstance(value, datetime):
        raise MLBHitsFeatureError("GAME_DATE_MUST_BE_DATE_NOT_DATETIME")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise MLBHitsFeatureError("GAME_DATE_INVALID")
    text = value.strip()
    try:
        if len(text) == 8 and text.isdigit():
            return datetime.strptime(text, "%Y%m%d").date()
        return date.fromisoformat(text)
    except ValueError as exc:
        raise MLBHitsFeatureError("GAME_DATE_INVALID") from exc


def _positive_id(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise MLBHitsFeatureError(f"{name}_INVALID")
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise MLBHitsFeatureError(f"{name}_INVALID") from exc
    if out <= 0:
        raise MLBHitsFeatureError(f"{name}_INVALID")
    return out


def _game_logs(player_id: int, group: str, *, through: date, opener: Callable, cache: JsonHistoryCache | None) -> list[Mapping[str, Any]]:
    if group not in {"hitting", "pitching"}:
        raise MLBHitsFeatureError("HISTORY_GROUP_INVALID")
    rows: list[Mapping[str, Any]] = []
    for season in range(FIRST_SEASON, through.year + 1):
        payload = _get_json(
            _url(f"/people/{player_id}/stats", {"stats": "gameLog", "group": group, "season": season, "gameType": "R"}),
            opener=opener, cache=cache,
        )
        stats = payload.get("stats") if isinstance(payload, Mapping) else None
        splits = ((stats or [{}])[0].get("splits") or []) if isinstance(stats, list) and stats else []
        for raw in splits:
            if not isinstance(raw, Mapping):
                raise MLBHitsFeatureError("GAME_LOG_ROW_MALFORMED")
            d = raw.get("date")
            try:
                row_date = date.fromisoformat(str(d))
            except ValueError as exc:
                raise MLBHitsFeatureError("GAME_LOG_DATE_INVALID") from exc
            if row_date < through:
                rows.append(raw)
    rows.sort(key=lambda r: (str(r.get("date")), int((r.get("game") or {}).get("gamePk") or 0)))
    return rows


def _boxscore(game_pk: int, *, opener: Callable, cache: JsonHistoryCache | None) -> Mapping[str, Any]:
    value = _get_json(_url(f"/game/{game_pk}/boxscore"), opener=opener, cache=cache)
    if not isinstance(value, Mapping):
        raise MLBHitsFeatureError("BOXSCORE_MALFORMED")
    return value


def _started_game(boxscore: Mapping[str, Any], player_id: int) -> bool:
    found = False
    for side in ("away", "home"):
        players = ((((boxscore.get("teams") or {}).get(side) or {}).get("players")) or {})
        if not isinstance(players, Mapping):
            continue
        for row in players.values():
            if not isinstance(row, Mapping):
                continue
            person = row.get("person") or {}
            try:
                pid = int(person.get("id"))
            except (TypeError, ValueError):
                continue
            if pid != player_id:
                continue
            found = True
            order = row.get("battingOrder")
            if order in (None, ""):
                return False
            try:
                code = int(order)
            except (TypeError, ValueError) as exc:
                raise MLBHitsFeatureError("BATTING_ORDER_INVALID") from exc
            slot, sequence = divmod(code, 100)
            return 1 <= slot <= 9 and sequence == 0
    if not found:
        raise MLBHitsFeatureError("PLAYER_NOT_IN_PRIOR_BOXSCORE")
    return False


def _batter_state(player_id: int, *, through: date, opener: Callable, cache: JsonHistoryCache | None) -> tuple[dict[str, Any], str]:
    rows = _game_logs(player_id, "hitting", through=through, opener=opener, cache=cache)
    h = pa = n_start = 0
    pa_pool: list[int] = []
    latest = None
    for row in rows:
        stat = row.get("stat") or {}
        game = row.get("game") or {}
        try:
            hits = int(stat.get("hits", 0))
            plate_appearances = int(stat.get("plateAppearances", 0))
            game_pk = int(game.get("gamePk"))
        except (TypeError, ValueError) as exc:
            raise MLBHitsFeatureError("BATTING_GAME_LOG_INVALID") from exc
        if hits < 0 or plate_appearances < 0 or game_pk <= 0:
            raise MLBHitsFeatureError("BATTING_GAME_LOG_INVALID")
        h += hits
        pa += plate_appearances
        if _started_game(_boxscore(game_pk, opener=opener, cache=cache), player_id):
            n_start += 1
            pa_pool.append(plate_appearances)
        latest = str(row.get("date"))
    return {"h": h, "pa": pa, "n_start": n_start, "pa_pool": pa_pool[-PA_POOL_LIMIT:]}, latest or ""


def _starter_state(player_id: int, *, through: date, opener: Callable, cache: JsonHistoryCache | None) -> tuple[dict[str, int], str]:
    rows = _game_logs(player_id, "pitching", through=through, opener=opener, cache=cache)
    h = bfp = 0
    latest = None
    for row in rows:
        stat = row.get("stat") or {}
        try:
            started = int(stat.get("gamesStarted", 0))
            hits = int(stat.get("hits", 0))
            faced = int(stat.get("battersFaced", 0))
        except (TypeError, ValueError) as exc:
            raise MLBHitsFeatureError("PITCHING_GAME_LOG_INVALID") from exc
        if hits < 0 or faced < 0 or started not in {0, 1}:
            raise MLBHitsFeatureError("PITCHING_GAME_LOG_INVALID")
        if started == 1:
            h += hits
            bfp += faced
            latest = str(row.get("date"))
    return {"h": h, "bfp": bfp}, latest or ""


def build_live_hits_features(*, game_date: str | date, batter_id: Any, starter_id: Any, opener: Callable = urlopen, cache: JsonHistoryCache | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    target = _target_date(game_date)
    batter = _positive_id("BATTER_ID", batter_id)
    starter = _positive_id("STARTER_ID", starter_id)
    bst, b_latest = _batter_state(batter, through=target, opener=opener, cache=cache)
    pst, p_latest = _starter_state(starter, through=target, opener=opener, cache=cache)
    if bst["n_start"] < MIN_STARTS:
        raise MLBHitsFeatureError("BATTER_PRIOR_STARTS_INSUFFICIENT")
    if pst["bfp"] <= 0:
        raise MLBHitsFeatureError("STARTER_PRIOR_BFP_MISSING")
    b_rate = (bst["h"] + LEAGUE_HIT * SH_B) / (bst["pa"] + SH_B)
    p_rate = (pst["h"] + LEAGUE_PH * SH_P) / (pst["bfp"] + SH_P)
    features = {"b_rate": b_rate, "p_rate": p_rate, "pa_pool": list(bst["pa_pool"])}
    provenance = {
        "game_date": target.isoformat(), "batter_id": batter, "starter_id": starter,
        "latest_batter_event_date": b_latest, "latest_starter_event_date": p_latest,
        "formula_version": "hits_batter_pitcher_pa_v1",
    }
    return features, provenance


def build_hits_feature_envelope(*, game_pk: Any, game_date: str | date, batter_id: Any, starter_id: Any, team_id: Any, retrieved_at: datetime, opener: Callable = urlopen, cache: JsonHistoryCache | None = None) -> dict[str, Any]:
    game_pk_i = _positive_id("GAME_PK", game_pk)
    team_id_i = _positive_id("TEAM_ID", team_id)
    if not isinstance(retrieved_at, datetime) or retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise MLBHitsFeatureError("RETRIEVED_AT_TIMEZONE_REQUIRED")
    current = retrieved_at.astimezone(timezone.utc)
    features, prov = build_live_hits_features(game_date=game_date, batter_id=batter_id, starter_id=starter_id, opener=opener, cache=cache)
    dates = [x for x in (prov["latest_batter_event_date"], prov["latest_starter_event_date"]) if x]
    if not dates:
        raise MLBHitsFeatureError("HISTORY_EVENT_TIME_MISSING")
    latest_date = max(date.fromisoformat(x) for x in dates)
    event_dt = datetime.combine(latest_date, time.min, tzinfo=timezone.utc)
    facts = []
    keys = {"b_rate": "hits.history.b_rate", "p_rate": "hits.history.p_rate", "pa_pool": "hits.history.pa_pool"}
    for feature in ("b_rate", "p_rate", "pa_pool"):
        facts.append({
            "source_id": f"mlb-history:{feature}:{int(batter_id)}:{int(starter_id)}:{_target_date(game_date).isoformat()}",
            "fact_key": keys[feature], "value": features[feature], "provider": PROVIDER,
            "event_time": event_dt.isoformat(), "retrieved_at": current.isoformat(),
        })
    return {
        "game_pk": game_pk_i, "player_id": _positive_id("BATTER_ID", batter_id), "team_id": team_id_i,
        "market": "HITS", "feature_fact_keys": keys,
        "ttl_by_feature": {"b_rate": FEATURE_TTL_SECONDS, "p_rate": FEATURE_TTL_SECONDS, "pa_pool": FEATURE_TTL_SECONDS},
        "sources": facts,
    }
