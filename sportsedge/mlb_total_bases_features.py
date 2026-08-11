"""Native pregame Total Bases features from official MLB game logs.

Reproduces the validated TB feature contract with frozen train-period league and
park constants. Only regular-season games strictly before the target official
date are used. Unknown MLB venues fail closed; they never inherit a neutral
park factor merely because the frozen historical artifact lacks a mapping.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
import json
from math import isfinite
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen

from .total_bases_engine import FEATURE_CONTRACT_VERSION

BASE = "https://statsapi.mlb.com/api/v1"
HISTORY_START_YEAR = 2021
SH = 300
PITCHER_SHRINK = 400
LG_PH = 0.2258
LG = {
    "s": 0.14297797620547198,
    "d": 0.0454277344353317,
    "t": 0.0038446756473789995,
    "hr": 0.03357448352128595,
}
MIN_STARTER_BFP = 100
MIN_BATTER_STARTS = 10
MIN_BATTER_PA = 100
PA_POOL_LIMIT = 30
DEFAULT_FEATURE_TTL_SECONDS = 3600
PARK_ARTIFACT_SHA256 = "d741d7bed908c7f2866509625f854e02dfa76483c9730ce18f23af5fb1b4a6ea"

# Official 2026 MLB venue IDs, live-probed from /api/v1/teams, mapped to the
# Retrosheet site codes in the frozen train-period park artifact. Venue 2529
# (Sutter Health Park / SAC01) is intentionally absent because SAC01 has no
# frozen factor in the validated artifact.
VENUE_TO_SITE = {
    1: "ANA01", 15: "PHO01", 2: "BAL12", 3: "BOS07", 17: "CHI11",
    2602: "CIN09", 5: "CLE08", 19: "DEN02", 2394: "DET05", 2392: "HOU03",
    7: "KAN06", 22: "LOS03", 3309: "WAS11", 3289: "NYC20", 31: "PIT08",
    2680: "SAN02", 680: "SEA03", 2395: "SFO03", 2889: "STL10", 12: "STP01",
    5325: "ARL03", 14: "TOR02", 3312: "MIN04", 2681: "PHI13", 4705: "ATL03",
    4: "CHI12", 4169: "MIA02", 3313: "NYC21", 32: "MIL06",
}


class MLBTBFeatureError(RuntimeError):
    def __init__(self, reason: str, detail: Mapping[str, Any] | None = None):
        self.reason = reason
        self.detail = dict(detail or {})
        super().__init__(f"{reason}: {self.detail}")


def _load_park_factor() -> dict[str, float]:
    path = Path(__file__).with_name("tb_park_factor_frozen.json")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise MLBTBFeatureError("TB_PARK_ARTIFACT_MISSING", {"path": str(path)}) from exc
    if hashlib.sha256(raw).hexdigest() != PARK_ARTIFACT_SHA256:
        raise MLBTBFeatureError("TB_PARK_ARTIFACT_HASH_MISMATCH")
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MLBTBFeatureError("TB_PARK_ARTIFACT_MALFORMED") from exc
    if not isinstance(value, dict) or len(value) != 32:
        raise MLBTBFeatureError("TB_PARK_ARTIFACT_MALFORMED")
    clean: dict[str, float] = {}
    for k, v in value.items():
        try:
            x = float(v)
        except (TypeError, ValueError) as exc:
            raise MLBTBFeatureError("TB_PARK_ARTIFACT_MALFORMED", {"site": str(k)}) from exc
        if not isfinite(x) or x <= 0:
            raise MLBTBFeatureError("TB_PARK_ARTIFACT_MALFORMED", {"site": str(k)})
        clean[str(k)] = x
    return clean


PARK_FACTOR = _load_park_factor()


def park_factor_for_venue(venue_id: Any) -> tuple[str, float]:
    if isinstance(venue_id, bool):
        raise MLBTBFeatureError("VENUE_UNMAPPED", {"venue_id": venue_id})
    try:
        vid = int(venue_id)
    except (TypeError, ValueError) as exc:
        raise MLBTBFeatureError("VENUE_UNMAPPED", {"venue_id": venue_id}) from exc
    site = VENUE_TO_SITE.get(vid)
    if site is None:
        raise MLBTBFeatureError("VENUE_UNMAPPED", {"venue_id": vid})
    if site not in PARK_FACTOR:
        raise MLBTBFeatureError("PARK_FACTOR_UNAVAILABLE", {"venue_id": vid, "site": site})
    return site, PARK_FACTOR[site]


def _nonnegative_int(name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise MLBTBFeatureError("MLB_TB_FEATURE_MALFORMED", {"field": name})
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise MLBTBFeatureError("MLB_TB_FEATURE_MALFORMED", {"field": name}) from exc
    if out < 0:
        raise MLBTBFeatureError("MLB_TB_FEATURE_MALFORMED", {"field": name})
    return out


def _split_date(row: Mapping[str, Any]) -> date:
    value = row.get("date")
    if not isinstance(value, str):
        raise MLBTBFeatureError("MLB_TB_FEATURE_MALFORMED", {"field": "date"})
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise MLBTBFeatureError("MLB_TB_FEATURE_MALFORMED", {"field": "date"}) from exc


def _game_pk(row: Mapping[str, Any]) -> int:
    return _nonnegative_int("gamePk", (row.get("game") or {}).get("gamePk"))


def _splits(payload: Any) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise MLBTBFeatureError("MLB_TB_RESPONSE_MALFORMED")
    stats = payload.get("stats")
    if not isinstance(stats, list) or not stats or not isinstance(stats[0], Mapping):
        return []
    rows = stats[0].get("splits") or []
    if not isinstance(rows, list) or any(not isinstance(x, Mapping) for x in rows):
        raise MLBTBFeatureError("MLB_TB_RESPONSE_MALFORMED")
    return rows


class MLBTBHistorySource:
    """Run-scoped official MLB history source for the validated TB contract."""

    def __init__(self, *, opener: Callable = urlopen, retrieved_at: datetime | None = None):
        current = retrieved_at or datetime.now(timezone.utc)
        if not isinstance(current, datetime) or current.tzinfo is None or current.utcoffset() is None:
            raise MLBTBFeatureError("MLB_TB_TIMEZONE_REQUIRED")
        self.opener = opener
        self.retrieved_at = current.astimezone(timezone.utc)
        self._cache: dict[tuple[int, str, int], list[Mapping[str, Any]]] = {}

    def _fetch(self, player_id: int, group: str, season: int) -> list[Mapping[str, Any]]:
        key = (int(player_id), str(group), int(season))
        if key in self._cache:
            return self._cache[key]
        if group not in {"hitting", "fielding", "pitching"}:
            raise MLBTBFeatureError("MLB_TB_GROUP_UNSUPPORTED", {"group": group})
        params = urlencode({"stats": "gameLog", "group": group, "season": season, "gameType": "R"})
        url = f"{BASE}/people/{int(player_id)}/stats?{params}"
        try:
            with self.opener(url, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise MLBTBFeatureError("MLB_TB_FETCH_FAILED", {"player_id": int(player_id), "group": group, "season": int(season)}) from exc
        rows = _splits(payload)
        self._cache[key] = rows
        return rows

    @staticmethod
    def _years(target_date: date):
        if target_date.year < HISTORY_START_YEAR:
            raise MLBTBFeatureError("MLB_TB_DATE_BEFORE_CONTRACT")
        return range(HISTORY_START_YEAR, target_date.year + 1)

    def _started_games(self, player_id: int, target_date: date) -> set[int]:
        started: set[int] = set()
        observed = False
        for year in self._years(target_date):
            for row in self._fetch(player_id, "fielding", year):
                if _split_date(row) >= target_date:
                    continue
                stat = row.get("stat") or {}
                if not isinstance(stat, Mapping) or "gamesStarted" not in stat:
                    raise MLBTBFeatureError("MLB_TB_START_STATUS_MISSING", {"player_id": int(player_id)})
                observed = True
                if _nonnegative_int("gamesStarted", stat.get("gamesStarted")) > 0:
                    started.add(_game_pk(row))
        if not observed:
            raise MLBTBFeatureError("MLB_TB_START_HISTORY_MISSING", {"player_id": int(player_id)})
        return started

    def batter_prior_state(self, batter_id: int, target_date: date) -> tuple[dict[str, Any], date]:
        started = self._started_games(batter_id, target_date)
        rows: list[tuple[date, int, Mapping[str, Any]]] = []
        seen: set[int] = set()
        for year in self._years(target_date):
            for row in self._fetch(batter_id, "hitting", year):
                d = _split_date(row)
                if d >= target_date:
                    continue
                pk = _game_pk(row)
                if pk in seen:
                    raise MLBTBFeatureError("MLB_TB_DUPLICATE_GAME", {"player_id": int(batter_id), "game_pk": pk, "group": "hitting"})
                stat = row.get("stat") or {}
                if not isinstance(stat, Mapping):
                    raise MLBTBFeatureError("MLB_TB_RESPONSE_MALFORMED")
                seen.add(pk)
                rows.append((d, pk, stat))
        rows.sort(key=lambda x: (x[0], x[1]))
        if not rows:
            raise MLBTBFeatureError("MLB_TB_BATTER_HISTORY_MISSING", {"player_id": int(batter_id)})
        state = {"s": 0, "d": 0, "t": 0, "hr": 0, "pa": 0, "n_start": 0, "pa_pool": []}
        for _, pk, stat in rows:
            hits = _nonnegative_int("hits", stat.get("hits"))
            doubles = _nonnegative_int("doubles", stat.get("doubles"))
            triples = _nonnegative_int("triples", stat.get("triples"))
            homers = _nonnegative_int("homeRuns", stat.get("homeRuns"))
            pa = _nonnegative_int("plateAppearances", stat.get("plateAppearances"))
            singles = hits - doubles - triples - homers
            if singles < 0 or hits > pa:
                raise MLBTBFeatureError("MLB_TB_FEATURE_MALFORMED", {"game_pk": pk, "detail": "invalid batting event totals"})
            state["s"] += singles; state["d"] += doubles; state["t"] += triples; state["hr"] += homers; state["pa"] += pa
            if pk in started:
                state["n_start"] += 1
                state["pa_pool"].append(pa)
        state["pa_pool"] = state["pa_pool"][-PA_POOL_LIMIT:]
        return state, rows[-1][0]

    def starter_prior_state(self, starter_id: int, target_date: date) -> tuple[dict[str, int], date]:
        rows: list[tuple[date, int, Mapping[str, Any]]] = []
        seen: set[int] = set()
        for year in self._years(target_date):
            for row in self._fetch(starter_id, "pitching", year):
                d = _split_date(row)
                if d >= target_date:
                    continue
                stat = row.get("stat") or {}
                if not isinstance(stat, Mapping) or "gamesStarted" not in stat:
                    raise MLBTBFeatureError("MLB_TB_START_STATUS_MISSING", {"player_id": int(starter_id)})
                if _nonnegative_int("gamesStarted", stat.get("gamesStarted")) <= 0:
                    continue
                pk = _game_pk(row)
                if pk in seen:
                    raise MLBTBFeatureError("MLB_TB_DUPLICATE_GAME", {"player_id": int(starter_id), "game_pk": pk, "group": "pitching"})
                seen.add(pk); rows.append((d, pk, stat))
        rows.sort(key=lambda x: (x[0], x[1]))
        if not rows:
            raise MLBTBFeatureError("MLB_TB_STARTER_HISTORY_MISSING", {"player_id": int(starter_id)})
        state = {"h": 0, "hr": 0, "bfp": 0}
        for _, _, stat in rows:
            state["h"] += _nonnegative_int("hits", stat.get("hits"))
            state["hr"] += _nonnegative_int("homeRuns", stat.get("homeRuns"))
            state["bfp"] += _nonnegative_int("battersFaced", stat.get("battersFaced"))
        if state["h"] > state["bfp"] or state["hr"] > state["h"]:
            raise MLBTBFeatureError("MLB_TB_FEATURE_MALFORMED", {"player_id": int(starter_id)})
        return state, rows[-1][0]

    def build_values(self, *, target_date: date, batter_id: int, starter_id: int, venue_id: int) -> tuple[dict[str, Any], date, str]:
        bst, b_latest = self.batter_prior_state(batter_id, target_date)
        pst, p_latest = self.starter_prior_state(starter_id, target_date)
        if bst["n_start"] < MIN_BATTER_STARTS or bst["pa"] < MIN_BATTER_PA:
            raise MLBTBFeatureError("MLB_TB_BATTER_SAMPLE_TOO_SMALL", {"player_id": int(batter_id), "n_start": bst["n_start"], "pa": bst["pa"]})
        if pst["bfp"] < MIN_STARTER_BFP:
            raise MLBTBFeatureError("MLB_TB_STARTER_SAMPLE_TOO_SMALL", {"player_id": int(starter_id), "bfp": pst["bfp"]})
        rates = {k: (bst[k] + LG[k] * SH) / (bst["pa"] + SH) for k in ("s", "d", "t", "hr")}
        p_h = (pst["h"] + LG_PH * PITCHER_SHRINK) / (pst["bfp"] + PITCHER_SHRINK)
        p_hr = (pst["hr"] + LG["hr"] * PITCHER_SHRINK) / (pst["bfp"] + PITCHER_SHRINK)
        site, park = park_factor_for_venue(venue_id)
        values = {"rates": rates, "p_h": p_h, "p_hr": p_hr, "park": park, "pa_pool": list(bst["pa_pool"])}
        if not all(isfinite(float(x)) for x in [*rates.values(), p_h, p_hr, park]):
            raise MLBTBFeatureError("MLB_TB_FEATURE_NONFINITE")
        return values, max(b_latest, p_latest), site

    def feature_envelope(self, *, game_pk: int, team_id: int, target_date: date, batter_id: int, starter_id: int, venue_id: int, ttl_seconds: int = DEFAULT_FEATURE_TTL_SECONDS) -> dict[str, Any]:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise MLBTBFeatureError("MLB_TB_FEATURE_TTL_INVALID")
        values, latest, site = self.build_values(target_date=target_date, batter_id=batter_id, starter_id=starter_id, venue_id=venue_id)
        retrieved = self.retrieved_at.isoformat()
        event_time = datetime.combine(latest, datetime.min.time(), tzinfo=timezone.utc).isoformat()
        prefix = f"mlb:tb:{target_date.isoformat()}:{int(batter_id)}:{int(starter_id)}:{int(venue_id)}"
        flat = {
            "rates_s": values["rates"]["s"], "rates_d": values["rates"]["d"],
            "rates_t": values["rates"]["t"], "rates_hr": values["rates"]["hr"],
            "p_h": values["p_h"], "p_hr": values["p_hr"], "park": values["park"], "pa_pool": values["pa_pool"],
        }
        keys = {name: f"{prefix}:{name}" for name in flat}
        sources = []
        for name, value in flat.items():
            provider = "SPORTSEDGE_FROZEN_TB_PARK" if name == "park" else "MLB_STATSAPI_GAMELOG"
            sources.append({"source_id": keys[name], "fact_key": keys[name], "value": value, "provider": provider, "event_time": event_time, "retrieved_at": retrieved})
        return {
            "game_pk": int(game_pk), "player_id": int(batter_id), "team_id": int(team_id), "market": "TOTAL_BASES",
            "feature_version": FEATURE_CONTRACT_VERSION, "feature_fact_keys": keys,
            "ttl_by_feature": {name: ttl_seconds for name in flat}, "sources": sources,
            "native_tb_site": site, "native_tb_park_artifact_sha256": PARK_ARTIFACT_SHA256,
        }
