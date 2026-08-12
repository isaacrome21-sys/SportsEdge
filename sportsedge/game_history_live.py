"""Source-bounded prior-day MLB history for canonical game-market live features."""
from __future__ import annotations

import calendar, json
from datetime import date
from pathlib import Path
from typing import Callable, Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .historical_cutoff import suspended_or_resumed_reason
from .source_range import partition_schedule_games

BASE = "https://statsapi.mlb.com"

class GameHistoryLiveError(ValueError):
    pass

def _get_json(path: str, params: dict[str, Any], opener: Callable = urlopen):
    url=f"{BASE}{path}?{urlencode(params)}"
    with opener(Request(url, headers={"Accept":"application/json"}), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))

def _ranges(start_year: int, end: date):
    for year in range(start_year, end.year+1):
        first_month=3
        last_month=end.month if year==end.year else 10
        for month in range(first_month,last_month+1):
            start=date(year,month,1)
            finish=date(year,month,calendar.monthrange(year,month)[1])
            if year==end.year and finish>end: finish=end
            if start>end: continue
            yield start.isoformat(), finish.isoformat()

def fetch_prior_finals(*, through_date: date, cache_dir: str|Path, opener: Callable=urlopen, start_year: int=2021):
    cache=Path(cache_dir); cache.mkdir(parents=True,exist_ok=True)
    by_pk={}; exclusions=[]
    for start,end in _ranges(start_year,through_date):
        p=cache/f"schedule_{start}_{end}.json"
        if p.exists(): data=json.loads(p.read_text(encoding="utf-8"))
        else:
            data=_get_json("/api/v1/schedule", {"sportId":1,"startDate":start,"endDate":end,"hydrate":"linescore,team"}, opener=opener)
            p.write_text(json.dumps(data), encoding="utf-8")
        accepted,violations=partition_schedule_games(data,start=start,end=end)
        exclusions.extend(violations)
        for game in accepted:
            if str(game.get("gameType"))!="R": continue
            if (game.get("status") or {}).get("abstractGameState")!="Final": continue
            pk=int(game.get("gamePk") or 0)
            reason=suspended_or_resumed_reason(game)
            if reason:
                exclusions.append({"game_pk":pk,"official_date":game.get("officialDate"),"reason_code":reason}); continue
            official=game.get("officialDate")
            try:
                d=date.fromisoformat(official)
            except Exception:
                exclusions.append({"game_pk":pk,"official_date":official,"reason_code":"OFFICIAL_DATE_INVALID_OR_MISSING"}); continue
            if d>through_date:
                raise GameHistoryLiveError("SOURCE_RANGE_VIOLATION_AFTER_PARTITION")
            ls=game.get("linescore") or {}; teams=game.get("teams") or {}
            try:
                hr=int(((ls.get("teams") or {}).get("home") or {})["runs"]); ar=int(((ls.get("teams") or {}).get("away") or {})["runs"])
                hid=int(((teams.get("home") or {}).get("team") or {})["id"]); aid=int(((teams.get("away") or {}).get("team") or {})["id"])
            except Exception:
                exclusions.append({"game_pk":pk,"official_date":official,"reason_code":"FINAL_GAME_FIELDS_INVALID"}); continue
            first=next((x for x in (ls.get("innings") or []) if int(x.get("num") or 0)==1),None)
            if not first:
                exclusions.append({"game_pk":pk,"official_date":official,"reason_code":"FIRST_INNING_RESULT_MISSING"}); continue
            try:
                afi=int((first.get("away") or {}).get("runs",0)); hfi=int((first.get("home") or {}).get("runs",0))
            except Exception:
                exclusions.append({"game_pk":pk,"official_date":official,"reason_code":"FIRST_INNING_RESULT_INVALID"}); continue
            by_pk[pk]={"game_pk":pk,"officialDate":official,"date":official,"away_id":aid,"home_id":hid,"away_runs":ar,"home_runs":hr,"away_fi":afi,"home_fi":hfi}
    return sorted(by_pk.values(),key=lambda g:(g["officialDate"],g["game_pk"])), exclusions
