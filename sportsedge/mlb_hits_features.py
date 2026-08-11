"""Native pregame Hits feature construction from official MLB game logs.

This module reproduces the validated historical Hits feature contract using only
regular-season games strictly before the target official date. Sportsbook data,
public projections, weather, BvP and outcome/future facts are never inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from math import isfinite
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen

from .hits_engine import FEATURE_CONTRACT_VERSION

BASE = "https://statsapi.mlb.com/api/v1"
HISTORY_START_YEAR = 2021
LEAGUE_HIT = 0.2258248698094686
LEAGUE_P_H = 0.2258
BATTER_SHRINK = 100
PITCHER_SHRINK = 200
MIN_STARTS = 5
PA_POOL_LIMIT = 30
DEFAULT_FEATURE_TTL_SECONDS = 3600


class MLBHitsFeatureError(RuntimeError):
    def __init__(self, reason: str, detail: Mapping[str, Any] | None = None):
        self.reason = reason
        self.detail = dict(detail or {})
        super().__init__(f"{reason}: {self.detail}")


@dataclass(frozen=True)
class GameLine:
    game_pk: int
    game_date: date
    hits: int
    pa: int


@dataclass(frozen=True)
class PitchLine:
    game_pk: int
    game_date: date
    hits: int
    bfp: int


def _positive_int(name: str, value: Any, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool):
        raise MLBHitsFeatureError("MLB_FEATURE_MALFORMED", {"field": name})
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise MLBHitsFeatureError("MLB_FEATURE_MALFORMED", {"field": name}) from exc
    if out < 0 or (out == 0 and not allow_zero):
        raise MLBHitsFeatureError("MLB_FEATURE_MALFORMED", {"field": name})
    return out


def _date(value: Any, field: str = "date") -> date:
    if not isinstance(value, str):
        raise MLBHitsFeatureError("MLB_FEATURE_MALFORMED", {"field": field})
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MLBHitsFeatureError("MLB_FEATURE_MALFORMED", {"field": field}) from exc


def _game_pk(split: Mapping[str, Any]) -> int:
    return _positive_int("gamePk", (split.get("game") or {}).get("gamePk"))


def _splits(payload: Any, *, group: str, player_id: int, season: int) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise MLBHitsFeatureError("MLB_FEATURE_RESPONSE_MALFORMED", {"group": group, "player_id": player_id, "season": season})
    stats = payload.get("stats")
    if not isinstance(stats, list) or not stats or not isinstance(stats[0], Mapping):
        return []
    rows = stats[0].get("splits") or []
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise MLBHitsFeatureError("MLB_FEATURE_RESPONSE_MALFORMED", {"group": group, "player_id": player_id, "season": season})
    return rows


class MLBHitsHistorySource:
    """Run-scoped cached StatsAPI history source."""

    def __init__(self, *, opener: Callable = urlopen, retrieved_at: datetime | None = None):
        current = retrieved_at or datetime.now(timezone.utc)
        if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
            raise MLBHitsFeatureError("MLB_FEATURE_TIMEZONE_REQUIRED")
        self.opener = opener
        self.retrieved_at = current.astimezone(timezone.utc)
        self._cache: dict[tuple[int, str, int], list[Mapping[str, Any]]] = {}

    def _fetch(self, player_id: int, group: str, season: int) -> list[Mapping[str, Any]]:
        key = (int(player_id), group, int(season))
        if key in self._cache:
            return self._cache[key]
        if group not in {"hitting", "fielding", "pitching"}:
            raise MLBHitsFeatureError("MLB_FEATURE_GROUP_UNSUPPORTED", {"group": group})
        params = urlencode({"stats": "gameLog", "group": group, "season": season, "gameType": "R"})
        url = f"{BASE}/people/{int(player_id)}/stats?{params}"
        try:
            with self.opener(url, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise MLBHitsFeatureError("MLB_FEATURE_FETCH_FAILED", {"group": group, "player_id": int(player_id), "season": season}) from exc
        rows = _splits(payload, group=group, player_id=int(player_id), season=season)
        self._cache[key] = rows
        return rows

    def _years(self, target_date: date):
        if target_date.year < HISTORY_START_YEAR:
            raise MLBHitsFeatureError("MLB_FEATURE_DATE_BEFORE_CONTRACT", {"target_date": target_date.isoformat()})
        return range(HISTORY_START_YEAR, target_date.year + 1)

    def hitting_history(self, player_id: int, target_date: date) -> list[GameLine]:
        out: list[GameLine] = []
        seen: set[int] = set()
        for year in self._years(target_date):
            for split in self._fetch(player_id, "hitting", year):
                d = _date(split.get("date"))
                if d >= target_date:
                    continue
                pk = _game_pk(split)
                if pk in seen:
                    raise MLBHitsFeatureError("MLB_FEATURE_DUPLICATE_GAME", {"player_id": int(player_id), "game_pk": pk, "group": "hitting"})
                stat = split.get("stat") or {}
                if not isinstance(stat, Mapping):
                    raise MLBHitsFeatureError("MLB_FEATURE_RESPONSE_MALFORMED", {"group": "hitting", "game_pk": pk})
                hits = _positive_int("hits", stat.get("hits"), allow_zero=True)
                pa = _positive_int("plateAppearances", stat.get("plateAppearances"), allow_zero=True)
                if hits > pa:
                    raise MLBHitsFeatureError("MLB_FEATURE_MALFORMED", {"game_pk": pk, "detail": "hits exceed PA"})
                seen.add(pk)
                out.append(GameLine(pk, d, hits, pa))
        out.sort(key=lambda x: (x.game_date, x.game_pk))
        return out

    def started_games(self, player_id: int, target_date: date) -> set[int]:
        started: set[int] = set()
        observed: set[int] = set()
        for year in self._years(target_date):
            for split in self._fetch(player_id, "fielding", year):
                d = _date(split.get("date"))
                if d >= target_date:
                    continue
                pk = _game_pk(split)
                stat = split.get("stat") or {}
                if not isinstance(stat, Mapping) or "gamesStarted" not in stat:
                    raise MLBHitsFeatureError("MLB_START_STATUS_MISSING", {"player_id": int(player_id), "game_pk": pk})
                gs = _positive_int("gamesStarted", stat.get("gamesStarted"), allow_zero=True)
                observed.add(pk)
                if gs > 0:
                    started.add(pk)
        if not observed:
            raise MLBHitsFeatureError("MLB_START_HISTORY_MISSING", {"player_id": int(player_id)})
        return started

    def pitching_history(self, player_id: int, target_date: date) -> list[PitchLine]:
        out: list[PitchLine] = []
        seen: set[int] = set()
        for year in self._years(target_date):
            for split in self._fetch(player_id, "pitching", year):
                d = _date(split.get("date"))
                if d >= target_date:
                    continue
                pk = _game_pk(split)
                stat = split.get("stat") or {}
                if not isinstance(stat, Mapping) or "gamesStarted" not in stat:
                    raise MLBHitsFeatureError("MLB_START_STATUS_MISSING", {"player_id": int(player_id), "game_pk": pk})
                if _positive_int("gamesStarted", stat.get("gamesStarted"), allow_zero=True) <= 0:
                    continue
                if pk in seen:
                    raise MLBHitsFeatureError("MLB_FEATURE_DUPLICATE_GAME", {"player_id": int(player_id), "game_pk": pk, "group": "pitching"})
                hits = _positive_int("hits", stat.get("hits"), allow_zero=True)
                bfp = _positive_int("battersFaced", stat.get("battersFaced"), allow_zero=True)
                if hits > bfp:
                    raise MLBHitsFeatureError("MLB_FEATURE_MALFORMED", {"game_pk": pk, "detail": "hits exceed BFP"})
                seen.add(pk)
                out.append(PitchLine(pk, d, hits, bfp))
        out.sort(key=lambda x: (x.game_date, x.game_pk))
        return out

    def build_values(self, *, target_date: date, batter_id: int, starter_id: int) -> tuple[float, float, list[int], date]:
        hitting = self.hitting_history(batter_id, target_date)
        if not hitting:
            raise MLBHitsFeatureError("MLB_BATTER_HISTORY_MISSING", {"player_id": int(batter_id)})
        started = self.started_games(batter_id, target_date)
        pa_pool = [row.pa for row in hitting if row.game_pk in started][-PA_POOL_LIMIT:]
        if len(pa_pool) < MIN_STARTS:
            raise MLBHitsFeatureError("MLB_BATTER_START_SAMPLE_TOO_SMALL", {"player_id": int(batter_id), "starts": len(pa_pool), "required": MIN_STARTS})
        bh = sum(row.hits for row in hitting)
        bpa = sum(row.pa for row in hitting)
        b_rate = (bh + LEAGUE_HIT * BATTER_SHRINK) / (bpa + BATTER_SHRINK)

        pitching = self.pitching_history(starter_id, target_date)
        ph = sum(row.hits for row in pitching)
        pbfp = sum(row.bfp for row in pitching)
        if pbfp <= 0:
            raise MLBHitsFeatureError("MLB_STARTER_BFP_HISTORY_MISSING", {"player_id": int(starter_id)})
        p_rate = (ph + LEAGUE_P_H * PITCHER_SHRINK) / (pbfp + PITCHER_SHRINK)
        if not all(isfinite(v) and 0 <= v <= 1 for v in (b_rate, p_rate)):
            raise MLBHitsFeatureError("MLB_FEATURE_NONFINITE")
        latest = max([row.game_date for row in hitting] + [row.game_date for row in pitching])
        return float(b_rate), float(p_rate), list(pa_pool), latest

    def feature_envelope(self, *, game_pk: int, team_id: int, target_date: date, batter_id: int, starter_id: int, ttl_seconds: int = DEFAULT_FEATURE_TTL_SECONDS) -> dict[str, Any]:
        b_rate, p_rate, pa_pool, latest = self.build_values(target_date=target_date, batter_id=batter_id, starter_id=starter_id)
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise MLBHitsFeatureError("MLB_FEATURE_TTL_INVALID")
        retrieved = self.retrieved_at.isoformat()
        # A historical game date is represented at UTC midnight. It is strictly
        # before target_date, so it cannot be future relative to a same-day wager.
        event_time = datetime.combine(latest, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        prefix = f"mlb:gamelog:{target_date.isoformat()}:{int(batter_id)}:{int(starter_id)}"
        facts = [
            {"source_id": prefix + ":b_rate", "fact_key": prefix + ":b_rate", "value": b_rate, "provider": "MLB_STATSAPI_GAMELOG", "event_time": event_time, "retrieved_at": retrieved},
            {"source_id": prefix + ":p_rate", "fact_key": prefix + ":p_rate", "value": p_rate, "provider": "MLB_STATSAPI_GAMELOG", "event_time": event_time, "retrieved_at": retrieved},
            {"source_id": prefix + ":pa_pool", "fact_key": prefix + ":pa_pool", "value": pa_pool, "provider": "MLB_STATSAPI_GAMELOG", "event_time": event_time, "retrieved_at": retrieved},
        ]
        return {
            "game_pk": int(game_pk), "player_id": int(batter_id), "team_id": int(team_id), "market": "HITS",
            "feature_version": FEATURE_CONTRACT_VERSION,
            "feature_fact_keys": {"b_rate": facts[0]["fact_key"], "p_rate": facts[1]["fact_key"], "pa_pool": facts[2]["fact_key"]},
            "ttl_by_feature": {"b_rate": ttl_seconds, "p_rate": ttl_seconds, "pa_pool": ttl_seconds},
            "sources": facts,
        }
