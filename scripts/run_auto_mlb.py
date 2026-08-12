#!/usr/bin/env python3
"""Run SportsEdge's automated MLB card from configured live providers."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from sportsedge.auto_native_odds import run_auto_mlb_native_odds
from sportsedge.auto_runner import AutoRunnerError, AutoRunReport, report_to_dict, run_auto_mlb
from sportsedge.bettor_card import build_bettor_card
from sportsedge.game_artifacts import load_frozen_game_artifacts
from sportsedge.game_history_live import build_live_game_feature_rows
from sportsedge.mlb_context import context_to_dict, fetch_slate_context
from sportsedge.mlb_source import fetch_schedule

CHICAGO_TZ=ZoneInfo("America/Chicago")


def _external_report(*, quote_url, feature_url, projected, token, now, min_edge, kelly_multiplier, require_confirmed_lineup, history_cache_dir, game_score_artifact, nrfi_artifact):
    """Run configured quote feed while preserving canonical native game features.

    The external feed supplies prices only.  Game Model_P still comes from the
    exact frozen v4 artifacts and prior-day MLB history; sportsbook values never
    enter the feature builder.
    """
    if not quote_url: raise AutoRunnerError("QUOTE_PROVIDER_CONFIG_MISSING")
    if not feature_url: raise AutoRunnerError("FEATURE_PROVIDER_CONFIG_MISSING")
    slate_date=now.astimezone(CHICAGO_TZ).date()
    schedule=fetch_schedule(slate_date.isoformat(),now=now)
    game_rows=None; game_failures=[]
    if game_score_artifact is not None and nrfi_artifact is not None:
        try:
            game_rows,excluded=build_live_game_feature_rows(slate_date=slate_date,schedule=schedule,cache_dir=Path(history_cache_dir or ".cache/sportsedge/mlb-history")/"game-core")
            game_failures=[{"stage":"GAME_HISTORY_EXCLUSION",**dict(x)} for x in excluded]
        except Exception as exc:
            game_failures=[{"stage":"GAME_LIVE_FEATURES","reason":f"{type(exc).__name__}: {exc}"}]
            game_rows=None
    report=run_auto_mlb(quote_url=quote_url,feature_url=feature_url,projected_lineups_url=projected,provider_token=token,now=now,require_confirmed_lineup=require_confirmed_lineup,min_edge=min_edge,kelly_multiplier=kelly_multiplier,game_feature_rows=game_rows,game_score_artifact=game_score_artifact,nrfi_artifact=nrfi_artifact)
    if not game_failures: return report
    return AutoRunReport(report.slate_date_ct,report.generated_at_utc,report.run_status,report.results,tuple(game_failures)+report.source_failures)


def _capture_context(now: datetime) -> tuple[list[dict], list[dict]]:
    """Context is presentation evidence only; failures never alter a bet verdict."""
    try:
        slate_date=now.astimezone(CHICAGO_TZ).date().isoformat()
        schedule=fetch_schedule(slate_date,now=now)
        rows=fetch_slate_context(schedule)
        failures=[{"stage":"MLB_CONTEXT","game_id":row.game_id,"reason":row.error} for row in rows if row.error]
        return [context_to_dict(row) for row in rows],failures
    except Exception as exc:
        return [],[{"stage":"MLB_CONTEXT","reason":f"{type(exc).__name__}: {exc}"}]


def _native_provider_notes(report: AutoRunReport) -> list[dict]:
    """Describe the actual price transport used by the native acquisition path."""
    fallback=any(x.get("stage")=="ESPN_DK_GAME_FALLBACK" for x in report.source_failures)
    exhausted=any(x.get("stage")=="ODDS_API_KEYRING_EXHAUSTED" for x in report.source_failures)
    if fallback:
        return [
            {"stage":"QUOTE_PROVIDER","provider":"ODDS_API_NATIVE","status":"EXHAUSTED" if exhausted else "FAILED_OVER"},
            {"stage":"QUOTE_PROVIDER","provider":"ESPN_WEB_HEADER_DRAFTKINGS","status":"PASS","markets":["MONEYLINE","RUN_LINE","TOTALS"],"freshness_basis":"SPORTSEDGE_HTTP_RETRIEVAL_TIME","ttl_seconds":60},
        ]
    return [{"stage":"QUOTE_PROVIDER","provider":"ODDS_API_NATIVE","status":"PASS"}]


def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--output",default="artifacts/live_mlb_card.json"); p.add_argument("--require-confirmed-lineup",action="store_true"); p.add_argument("--min-edge",type=float,default=0.0); p.add_argument("--kelly-multiplier",type=float,default=0.25); args=p.parse_args()
    quotes=os.environ.get("SPORTSEDGE_QUOTES_URL","").strip()
    odds_api_keys=tuple(value for value in (os.environ.get("SPORTSEDGE_ODDS_API_KEY","").strip(),os.environ.get("SPORTSEDGE_ODDS_API_KEY_2","").strip(),os.environ.get("SPORTSEDGE_ODDS_API_KEY_3","").strip(),os.environ.get("SPORTSEDGE_ODDS_API_KEY_4","").strip()) if value)
    odds_books=tuple(x.strip() for x in os.environ.get("SPORTSEDGE_ODDS_BOOKMAKERS","draftkings").split(",") if x.strip())
    features=os.environ.get("SPORTSEDGE_FEATURES_URL","").strip(); projected=os.environ.get("SPORTSEDGE_PROJECTED_LINEUPS_URL","").strip() or None; token=os.environ.get("SPORTSEDGE_PROVIDER_TOKEN","").strip() or None; history_cache_dir=os.environ.get("SPORTSEDGE_HISTORY_CACHE_DIR","").strip() or None
    game_score_path=os.environ.get("SPORTSEDGE_GAME_SCORE_ARTIFACT","").strip(); nrfi_path=os.environ.get("SPORTSEDGE_NRFI_ARTIFACT","").strip()
    now=datetime.now(timezone.utc); infrastructure_blocked=False; provider_notes=[]
    slate_context,context_failures=_capture_context(now)
    try:
        game_score_artifact=nrfi_artifact=None
        if game_score_path or nrfi_path:
            if not (game_score_path and nrfi_path): raise AutoRunnerError("GAME_ARTIFACT_CONFIG_INCOMPLETE")
            game_score_artifact,nrfi_artifact=load_frozen_game_artifacts(game_score_path=game_score_path,nrfi_path=nrfi_path)
        common=dict(projected_lineups_url=projected,provider_token=token,now=now,require_confirmed_lineup=args.require_confirmed_lineup,min_edge=args.min_edge,kelly_multiplier=args.kelly_multiplier)
        report=None
        if odds_api_keys:
            try:
                if game_score_artifact is None or nrfi_artifact is None: raise AutoRunnerError("GAME_ARTIFACT_CONFIG_MISSING")
                report=run_auto_mlb_native_odds(odds_api_key=odds_api_keys[0],odds_api_keys=odds_api_keys[1:],feature_url=features or None,bookmakers=odds_books,history_cache_dir=history_cache_dir,game_score_artifact=game_score_artifact,nrfi_artifact=nrfi_artifact,**common)
                provider_notes.extend(_native_provider_notes(report))
            except Exception as native_exc:
                provider_notes.append({"stage":"QUOTE_PROVIDER","provider":"ODDS_API_NATIVE","status":"FAILED_OVER","reason":f"{type(native_exc).__name__}: {native_exc}"})
                if not quotes:
                    raise
        if report is None:
            report=_external_report(quote_url=quotes,feature_url=features,projected=projected,token=token,now=now,min_edge=args.min_edge,kelly_multiplier=args.kelly_multiplier,require_confirmed_lineup=args.require_confirmed_lineup,history_cache_dir=history_cache_dir,game_score_artifact=game_score_artifact,nrfi_artifact=nrfi_artifact)
            provider_notes.append({"stage":"QUOTE_PROVIDER","provider":"CONFIGURED_QUOTES_URL","status":"PASS"})
        payload=report_to_dict(report); payload["provider_status"]=provider_notes; payload["bettor_card"]=build_bettor_card(report.results,min_edge=args.min_edge)
    except Exception as exc:
        infrastructure_blocked=True
        payload={"slate_date_ct":now.astimezone(CHICAGO_TZ).date().isoformat(),"generated_at_utc":now.isoformat(),"run_status":"BLOCKED","results":[],"source_failures":[{"reason":f"{type(exc).__name__}: {exc}"}],"provider_status":provider_notes,"bettor_card":build_bettor_card([],min_edge=args.min_edge)}
    payload["slate_context"]=slate_context
    payload["context_failures"]=context_failures
    out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n"); print(json.dumps(payload,indent=2,sort_keys=True)); return 2 if infrastructure_blocked else 0

if __name__=="__main__": raise SystemExit(main())
