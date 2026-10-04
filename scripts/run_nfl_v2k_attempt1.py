#!/usr/bin/env python3
"""NFL V2K Attempt-1 development/validation runner.

Builds market-blind drive rows from frozen nflverse PBP and executes the
pre-registered expanding-season folds. This is a development-validation
surface only; it does not read sportsbook prices.
"""
from __future__ import annotations
import argparse, csv, gzip, json
from pathlib import Path
from sportsedge.sports.nfl.v2k_drive_source import build_drive_rows_from_pbp
from sportsedge.sports.nfl.v2k_drive_core import fit_hierarchical_strength, derive_path_seed, simulate_joint_game

ROOT_SEED=15264549103493747052
FOLDS=((range(2018,2021),2021),(range(2018,2022),2022),(range(2018,2023),2023),(range(2018,2024),2024),(range(2018,2025),2025))

def _read(path):
    op=gzip.open if path.suffix==".gz" else open
    with op(path,"rt",encoding="utf-8-sig",newline="") as h: return list(csv.DictReader(h))

def _records(rows):
    out=[]
    for i,r in enumerate(rows):
        gid=str(r.get("game_id") or "")
        drive=r.get("drive")
        posteam=r.get("posteam")
        defteam=r.get("defteam")
        if not gid or not drive or not posteam or not defteam: continue
        q=int(float(r.get("qtr") or 0))
        if q<1 or q>5: continue
        result=str(r.get("drive_result") or "").strip()
        if not result: continue
        out.append({
          "game_id":gid,"season":int(float(r["season"])),"week":int(float(r["week"])),
          "kickoff_utc":str(r.get("game_date") or r.get("start_time") or ""),
          "drive_id":drive,"play_index":int(float(r.get("play_id") or i)),
          "offense":posteam,"defense":defteam,
          "start_yardline_100":float(r.get("yardline_100") or 50),
          "drive_result":result,
          "offense_score_before":int(float(r.get("posteam_score") or 0)),
          "defense_score_before":int(float(r.get("defteam_score") or 0)),
          "offense_score_after":int(float(r.get("posteam_score_post") or r.get("posteam_score") or 0)),
          "defense_score_after":int(float(r.get("defteam_score_post") or r.get("defteam_score") or 0)),
          "period":q,"clock_seconds_remaining_period":int(float(r.get("quarter_seconds_remaining") or 0)),
          "conversion_points":int(float(r.get("extra_point_result")=="good")) if result.lower() in ("touchdown","td") else 0,
          "drive_order":int(float(drive)) if str(drive).replace(".","",1).isdigit() else i,
        })
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--pbp-dir",type=Path,required=True); p.add_argument("--source-manifest-sha",required=True)
    p.add_argument("--code-sha",required=True); p.add_argument("--paths",type=int,default=50000); p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    if a.paths<10000: raise SystemExit("V2K_PATH_FLOOR_10000")
    byseason={}
    for y in range(2018,2026):
        f=next(iter(sorted(a.pbp_dir.glob(f"play_by_play_{y}.*"))),None)
        if f is None: raise SystemExit(f"V2K_PBP_MISSING:{y}")
        byseason[y]=build_drive_rows_from_pbp(_records(_read(f)),source_manifest_sha256=a.source_manifest_sha,source_code_sha=a.code_sha)
    results=[]
    for train_years,test_year in FOLDS:
        train=[r for y in train_years for r in byseason[y]]
        model=fit_hierarchical_strength(train)
        games={}
        for r in byseason[test_year]: games.setdefault(r.game_id,[]).append(r)
        fold=[]
        for gid,rows in sorted(games.items()):
            teams=[]
            for r in rows:
                for t in (r.offense,r.defense):
                    if t not in teams: teams.append(t)
            if len(teams)!=2: continue
            home,away=teams[0],teams[1]
            margins=[]; totals=[]
            for idx in range(a.paths):
                seed=derive_path_seed(root_seed=ROOT_SEED,game_key=gid,path_index=idx)
                s=simulate_joint_game(model,home,away,season=test_year,seed=seed)
                margins.append(s.margin); totals.append(s.total)
            fold.append({"game_id":gid,"mean_margin":sum(margins)/len(margins),"mean_total":sum(totals)/len(totals),
                         "home_win_probability":sum(x>0 for x in margins)/len(margins)})
        results.append({"test_season":test_year,"train_seasons":list(train_years),"games":fold})
    payload={"schema":"NFL_V2K_ATTEMPT1_DEVELOPMENT_VALIDATION_V1","root_seed":ROOT_SEED,"paths_per_game":a.paths,
             "folds":results,"sportsbook_prices_consumed":False,"attempt_consumed":True}
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
if __name__=="__main__": main()
