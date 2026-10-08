#!/usr/bin/env python3
"""Strictly-prior, descriptive MLB postseason starter workload audit.

The cohort is *every completed official postseason game* in frozen seasons
2023, 2024 and 2025, not pitchers selected by how long they pitched. The
official game boxscore's first listed pitcher is the actual starter. Compare
observed postseason starter outs and Ks against point-in-time regular-season
10-start marginals and a non-overlapping older-20-start candidate.

This is a retrospective workload audit, not live postseason prop pricing or
evidence authorizing deployment. No market odds, scores or postseason results
are used to fit predictions. Each official game/pitcher appears only once.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import urlopen

from scripts.eval_mlb_pitcher_window_blend import marginal, summarize
from sportsedge.mlb_generic_features import _outs_from_ip, _number, _read_json, _splits
from sportsedge.mlb_joint_features import _pitcher_pool
from sportsedge.source_lineage import canonical_json_sha256

VERSION = "mlb_postseason_starter_workload_audit_2023_2025_v1"
FROZEN_SEASONS = (2023, 2024, 2025)
POSTSEASON_GAME_TYPES = frozenset({"F", "D", "L", "W"})
LINES = {"PITCHER_OUTS": (12.5, 15.5, 17.5), "PITCHER_K": (2.5, 4.5)}
MIN_RECENT_STARTS = 5
MIN_COVERAGE_GAMES = 70
MIN_EVALUABLE_STARTS = 70


def completed_postseason_games(schedule: Mapping[str, Any], year: int) -> list[dict[str, Any]]:
    dates = schedule.get("dates")
    if not isinstance(dates, list):
        raise ValueError("Missing MLB schedule dates")
    out = []
    seen = set()
    for day in dates:
        for game in day.get("games") or []:
            if str(game.get("gameType")) not in POSTSEASON_GAME_TYPES:
                continue
            status = game.get("status") or {}
            if str(status.get("abstractGameState") or "").lower() != "final":
                continue
            pk = game.get("gamePk")
            official = str(game.get("officialDate") or day.get("date") or "")[:10]
            if not isinstance(pk, int) or pk in seen or not official.startswith(str(year)):
                raise ValueError("Invalid or duplicate completed postseason game")
            seen.add(pk)
            out.append({"game_pk": pk, "date": official, "game_type": str(game["gameType"])})
    return sorted(out, key=lambda row: (row["date"], row["game_pk"]))


def extract_actual_starters(feed: Mapping[str, Any], game: Mapping[str, Any]) -> list[dict[str, Any]]:
    live = feed.get("liveData") or {}
    box = live.get("boxscore") or {}
    teams = box.get("teams") or {}
    result = []
    for side in ("away", "home"):
        team = teams.get(side) or {}
        pitchers = team.get("pitchers") or []
        players = team.get("players") or {}
        if not isinstance(pitchers, list) or not pitchers:
            raise ValueError(f"Missing actual {side} boxscore pitcher order")
        pid = pitchers[0]
        if not isinstance(pid, int) or pid <= 0:
            raise ValueError("Invalid actual starter ID")
        player = players.get(f"ID{pid}") or {}
        stats = (player.get("stats") or {}).get("pitching") or {}
        if not isinstance(stats, Mapping) or not stats.get("inningsPitched"):
            raise ValueError(f"Missing actual {side} starter innings")
        outs = int(_outs_from_ip(stats["inningsPitched"]))
        k = _number(stats.get("strikeOuts"), "strikeOuts")
        if not 0 <= outs <= 27 or k < 0 or not float(k).is_integer():
            raise ValueError("Invalid actual starter pitch stats")
        result.append({
            "game_pk": int(game["game_pk"]), "date": str(game["date"]),
            "game_type": str(game["game_type"]), "team_side": side,
            "player_id": pid, "outs": outs, "strikeouts": int(k),
        })
    if len(result) != 2 or result[0]["player_id"] == result[1]["player_id"]:
        raise ValueError("Actual boxscore starters are missing or duplicated")
    return result


def season_regular_starts(payload: Mapping[str, Any], target_date: str) -> list[dict[str, Any]]:
    rows = _splits(payload, target_date=date.fromisoformat(target_date))
    starts = [r for r in rows if _number(r["stat"].get("gamesStarted", 0), "gamesStarted") >= 1]
    pool = _pitcher_pool(starts)
    if len(pool) != len(starts):
        raise ValueError("Misaligned regular-season starter game log")
    return [{"date":r["date"].isoformat(), "row":v} for r,v in zip(starts,pool)]


def grade_starter(starter: Mapping[str, Any], regular: list[dict[str, Any]]) -> dict[str, Any]:
    date_of_game = str(starter["date"])
    if any(row["date"] >= date_of_game for row in regular):
        raise ValueError("Non-point-in-time regular-season history")
    recent = [r["row"] for r in regular[-10:]]
    older = [r["row"] for r in regular[-30:-10]]
    if len(recent) < MIN_RECENT_STARTS:
        return {"status":"INSUFFICIENT_PRIOR_REGULAR_STARTS",
                "regular_starts":len(regular), "records":[]}
    if len(older) < 5:
        older = []
    records=[]
    for market, thresholds in LINES.items():
        actual = int(starter["outs"] if market == "PITCHER_OUTS" else starter["strikeouts"])
        for line in thresholds:
            b = marginal(recent, market, line)
            c = marginal(recent, market, line, older=older) if older else b
            records.append({
                "game_pk":int(starter["game_pk"]),
                "date":date_of_game, "game_type":starter["game_type"],
                "pitcher_id":int(starter["player_id"]), "team_side":starter["team_side"],
                "market":market,"line":line,"actual_value":actual,
                "actual_over":float(actual > line),
                "p_recent_only":float(b),"p_recent_plus_capped_prior":float(c),
                "prior_regular_starts":len(regular),
                "prior_recent_starts":len(recent),
                "prior_older_starts":len(older),
            })
    return {"status":"EVALUATED","regular_starts":len(regular),
            "recent_mean_outs":sum(r["outs"] for r in recent)/len(recent),
            "recent_mean_k":sum(r["strikeouts"] for r in recent)/len(recent),
            "records":records}


def _get(url: str) -> Mapping[str, Any]:
    return _read_json(url, opener=urlopen)


def run(*, seasons: tuple[int, ...] = FROZEN_SEASONS, workers: int = 8) -> dict[str, Any]:
    if tuple(seasons) != FROZEN_SEASONS:
        raise ValueError("Frozen postseason seasons cannot be changed in this attempt")
    games = []
    for year in seasons:
        q=urlencode({"sportId":1,"startDate":f"{year}-09-20",
                     "endDate":f"{year}-11-15"})
        schedule=_get(f"https://statsapi.mlb.com/api/v1/schedule?{q}")
        season_games=completed_postseason_games(schedule,year)
        if len(season_games) < 25:
            raise ValueError(f"Incomplete postseason game schedule for {year}: {len(season_games)}")
        games.extend(season_games)
    if len(games) < MIN_COVERAGE_GAMES:
        raise ValueError("Not enough completed postseason games")

    starters=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(_get, f"https://statsapi.mlb.com/api/v1.1/game/{g['game_pk']}/feed/live"):g for g in games}
        for future in as_completed(futures):
            game=futures[future]
            starters.extend(extract_actual_starters(future.result(),game))
    starters.sort(key=lambda r:(r["date"],r["game_pk"],r["team_side"]))
    if len(starters) != 2*len(games):
        raise ValueError("Incomplete actual postseason starter inventory")

    jobs=sorted(set((r["player_id"],int(r["date"][:4])) for r in starters))
    history={}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={}
        for pid,year in jobs:
            q=urlencode({"stats":"gameLog","group":"pitching","season":year,"gameType":"R"})
            url=f"https://statsapi.mlb.com/api/v1/people/{pid}/stats?{q}"
            futures[pool.submit(_get,url)]=(pid,year)
        for future in as_completed(futures):
            history[futures[future]]=future.result()
    if len(history)!=len(jobs):
        raise ValueError("Incomplete postseason pitcher regular-season history")

    per_start=[]
    evaluated=[]
    for starter in starters:
        regular=season_regular_starts(history[(starter["player_id"],int(starter["date"][:4]))],
                                      starter["date"])
        scored=grade_starter(starter,regular)
        base={**starter,"history_status":scored["status"],"regular_starts":scored["regular_starts"]}
        if scored["status"]=="EVALUATED":
            base["recent_mean_outs"]=scored["recent_mean_outs"]
            base["recent_mean_k"]=scored["recent_mean_k"]
            base["outs_minus_recent_mean"]=starter["outs"]-scored["recent_mean_outs"]
            evaluated.append(base)
        per_start.append(base)
        per_start[-1]["records"]=scored["records"]
    if len(evaluated)<MIN_EVALUABLE_STARTS:
        raise ValueError(f"Insufficient regular-season-backed postseason starters: {len(evaluated)}")
    records=[r for s in per_start for r in s["records"]]
    scored=summarize(records)

    by_year={}
    for year in seasons:
        year_starts=[s for s in evaluated if s["date"].startswith(str(year))]
        year_rows=[r for r in records if r["date"].startswith(str(year))]
        if not year_starts or not year_rows: raise ValueError(f"No evaluable starts for {year}")
        by_year[str(year)]={
            "evaluated_starters":len(year_starts),
            "mean_postseason_outs":sum(s["outs"] for s in year_starts)/len(year_starts),
            "mean_regular_recent_outs":sum(s["recent_mean_outs"] for s in year_starts)/len(year_starts),
            "actual_over_12_5_outs":sum(s["outs"]>=13 for s in year_starts)/len(year_starts),
            "pred_recent_over_12_5_outs":sum(r["p_recent_only"] for r in year_rows
                if r["market"]=="PITCHER_OUTS" and r["line"]==12.5)/len(year_starts),
            "overall":summarize(year_rows)["overall"],
        }

    n=len(evaluated)
    results={
        "version":VERSION,
        "frozen_seasons":list(seasons),
        "cohort":"ALL_OFFICIAL_COMPLETED_POSTSEASON_GAMES_ACTUAL_BOX_SCORE_FIRST_PITCHER",
        "selection_depends_on_result_length":False,
        "official_postseason_game_count":len(games),
        "actual_starter_inventory":len(starters),
        "evaluable_starters":n,
        "unique_pitchers":len({s["player_id"] for s in evaluated}),
        "mean_postseason_outs":sum(s["outs"] for s in evaluated)/n,
        "mean_prior_regular_recent_outs":sum(s["recent_mean_outs"] for s in evaluated)/n,
        "mean_outs_shift":sum(s["outs_minus_recent_mean"] for s in evaluated)/n,
        "actual_over_12_5_outs":sum(s["outs"]>=13 for s in evaluated)/n,
        "baseline_pred_over_12_5_outs":sum(r["p_recent_only"] for r in records
            if r["market"]=="PITCHER_OUTS" and r["line"]==12.5)/n,
        "market_summary":scored["markets"],
        "overall_scoring":scored["overall"],
        "by_year":by_year,
        "game_inventory_hash":canonical_json_sha256(games),
        "model_probabilities_changed":False,"promotable":False,
        "price_blind":True,"postseason_fit_performed":False,
        "source":"MLB_STATSAPI_OFFICIAL_SCHEDULE_GAME_FEEDS_AND_STRICTLY_PRIOR_REGULAR_GAMELOGS",
        "caveats":"Regular-season baseline is context-blind and excludes opponent, lineup, rest and exact bullpen availability; repeated threshold rows are correlated; postseason observed samples are not prospective validation. No deployment or betting card release.",
        "starts":per_start,
    }
    return results


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",required=True)
    parser.add_argument("--workers",type=int,default=8)
    args=parser.parse_args()
    payload=run(workers=args.workers)
    out=Path(args.output)
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("POSTSEASON_STARTER_WORKLOAD_RESEARCH",json.dumps({
        k:payload[k] for k in ("official_postseason_game_count","evaluable_starters",
           "mean_postseason_outs","mean_prior_regular_recent_outs","mean_outs_shift",
           "actual_over_12_5_outs","baseline_pred_over_12_5_outs")},
        sort_keys=True))
    print("RESEARCH_ONLY_POSTSEASON_NOT_PROMOTED")


if __name__ == "__main__":
    main()
