#!/usr/bin/env python3
"""Attest today's canonical game-model runtime independently of sportsbook prices."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib, json, os
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.game_artifacts import load_frozen_game_artifacts, GAME_SCORE_SHA256, NRFI_SHA256
from sportsedge.game_history_live import build_live_game_feature_rows
from sportsedge.game_score_live import simulate_game
from sportsedge.mlb_source import fetch_schedule
from sportsedge.nrfi_live import first_inning_model_p

CHICAGO=ZoneInfo("America/Chicago")


def main()->int:
    now=datetime.now(timezone.utc); slate=now.astimezone(CHICAGO).date()
    game_path=os.environ.get("SPORTSEDGE_GAME_SCORE_ARTIFACT","").strip(); nrfi_path=os.environ.get("SPORTSEDGE_NRFI_ARTIFACT","").strip()
    if not game_path or not nrfi_path: raise RuntimeError("GAME_ARTIFACT_CONFIG_MISSING")
    game_art,nrfi_art=load_frozen_game_artifacts(game_score_path=game_path,nrfi_path=nrfi_path)
    schedule=fetch_schedule(slate.isoformat(),now=now)
    rows,exclusions=build_live_game_feature_rows(slate_date=slate,schedule=schedule,cache_dir=os.environ.get("SPORTSEDGE_GAME_HISTORY_CACHE_DIR",".cache/sportsedge/mlb-history/game-core"))
    by_id={str(r["game_id"]):r for r in rows}
    if len(schedule)!=len(rows): raise RuntimeError(f"LIVE_FEATURE_CARDINALITY_MISMATCH schedule={len(schedule)} rows={len(rows)}")
    games=[]
    for g in schedule:
        gid=str(g.game_pk); row=by_id.get(gid)
        if row is None: raise RuntimeError(f"LIVE_FEATURE_GAME_MISSING:{gid}")
        sim=simulate_game(game_art,row["run_rows"],game_id=int(g.game_pk),n_sims=7000)
        fi=first_inning_model_p(nrfi_art,row["fi_row"])
        if abs((fi["YRFI"]+fi["NRFI"])-1.0)>1e-12: raise RuntimeError("FIRST_INNING_COMPLEMENT_FAILED")
        games.append({
            "game_id":gid,"official_date":g.official_date,"away_id":g.away_id,"home_id":g.home_id,
            "history_cutoff":row["history_cutoff"],"n_sims":sim["n_sims"],
            "away_mu":sim["away_mu"],"home_mu":sim["home_mu"],
            "home_ml_p":sim["home_ml_p"],"away_ml_p":sim["away_ml_p"],
            "yrfi_p":fi["YRFI"],"nrfi_p":fi["NRFI"],
        })
    payload={
        "schema_version":"live_game_runtime_attestation_v1",
        "generated_at_utc":now.isoformat(),"slate_date_ct":slate.isoformat(),
        "scheduled_games":len(schedule),"attested_games":len(games),"verdict":"PASS",
        "game_score_artifact_sha256":GAME_SCORE_SHA256,"nrfi_artifact_sha256":NRFI_SHA256,
        "game_score_version":game_art.get("version"),"nrfi_version":nrfi_art.get("version"),
        "monte_carlo_paths_per_game":7000,"source":"MLB_STATSAPI_ONLY_NO_SPORTSBOOK_FEATURES",
        "history_cutoff": (games[0]["history_cutoff"] if games else None),
        "history_exclusions_count":len(exclusions),"games":games,
    }
    raw=(json.dumps(payload,indent=2,sort_keys=True)+"\n").encode(); payload["payload_sha256_pre_field"]=hashlib.sha256(raw).hexdigest()
    out=Path("artifacts/live_game_runtime_attestation.json"); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(json.dumps(payload,indent=2,sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
