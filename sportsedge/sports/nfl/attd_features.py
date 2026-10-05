"""PIT-safe ATTD research features for NFL G1.

Research only: features do not create Model_P, promotion, staking or OFFICIAL authority.
"""
from __future__ import annotations
from statistics import mean
from typing import Any, Iterable

_ZONES=("goal_line","red_zone","fringe","open_field")

def _f(row:dict[str,Any], key:str)->float:
    v=row.get(key)
    return 0.0 if v in (None,"") else float(v)

def build_attd_feature_rows(rows:Iterable[dict[str,Any]], *, min_prior_games:int=3, window:int=5)->list[dict[str,Any]]:
    data=[dict(r) for r in rows]
    data.sort(key=lambda r:(int(r["season"]),int(r["week"]),str(r.get("player_id") or "")))
    out=[]
    for i,row in enumerate(data):
        pid=str(row.get("player_id") or "").strip()
        if not pid: raise ValueError("NFL_ATTD_PLAYER_ID_REQUIRED")
        season,week=int(row["season"]),int(row["week"])
        prior=[r for r in data[:i] if str(r.get("player_id") or "")==pid]
        if any((int(r["season"]),int(r["week"])) >= (season,week) for r in prior):
            raise ValueError("NFL_ATTD_NON_PIT_PRIOR_ROW")
        if len(prior)<min_prior_games: continue
        hist=prior[-window:]
        def avg(k): return mean([_f(r,k) for r in hist])
        rush_td=sum(_f(r,"rushing_tds") for r in hist)
        rec_td=sum(_f(r,"receiving_tds") for r in hist)
        actual_td=rush_td+rec_td
        xtd=sum(_f(r,"expected_tds") for r in hist)
        item={
          "player_id":pid,"season":season,"week":week,"position":row.get("position"),
          "team":row.get("team"),"opponent_team":row.get("opponent_team"),
          "prior_game_count":len(prior),"window_game_count":len(hist),
          "snap_share_l5":avg("snap_share"),"route_share_l5":avg("route_share"),
          "target_share_l5":avg("target_share"),"rush_share_l5":avg("rush_share"),
          "touches_l5":avg("touches"),"expected_tds_l5":xtd/len(hist),
          "actual_tds_l5":actual_td/len(hist),"td_debt_l5":xtd-actual_td,
          "team_expected_points_l5":avg("team_expected_points"),
          "opponent_td_rate_allowed_l5":avg("opponent_td_rate_allowed"),
          "single_high_rate_l5":avg("single_high_rate"),"two_high_rate_l5":avg("two_high_rate"),
          "zero_shell_rate_l5":avg("zero_shell_rate"),"light_box_rate_l5":avg("light_box_rate"),
          "stacked_box_rate_l5":avg("stacked_box_rate"),
          "label_any_td": int((_f(row,"rushing_tds")+_f(row,"receiving_tds"))>=1),
        }
        for z in _ZONES:
            item[f"{z}_carries_l5"]=avg(f"{z}_carries")
            item[f"{z}_targets_l5"]=avg(f"{z}_targets")
            item[f"{z}_xtd_l5"]=avg(f"{z}_expected_tds")
        out.append(item)
    return out

def attd_research_score(features:dict[str,Any])->float:
    """Transparent 0-100 board rank only; explicitly NOT Model_P."""
    role=min(1.0,max(0.0,0.30*_f(features,"snap_share_l5")+0.25*_f(features,"rush_share_l5")+0.25*_f(features,"target_share_l5")+0.20*_f(features,"route_share_l5")))
    scoring=min(1.0,max(0.0,_f(features,"expected_tds_l5")))
    goal=min(1.0,max(0.0,_f(features,"goal_line_xtd_l5")+0.5*_f(features,"red_zone_xtd_l5")))
    return round(100.0*(0.40*role+0.35*scoring+0.25*goal),2)
