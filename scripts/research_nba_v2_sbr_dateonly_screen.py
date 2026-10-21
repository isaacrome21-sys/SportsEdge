"""Reproduce NBA totals V2 on the historical SBR *date-only* archive.

This is NOT a valid PIT market replay: the archive has game calendar dates
but no event tipoff instants, result-available instants, provider-side quote
capture times or independent price-vintage authority. The screen uses
strictly EARLIER calendar dates for learning, never same-date outcomes.
Every market reference remains INDICATIVE and unadmitted. The source raw
file must match the pinned upstream Git blob before CLI execution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

SOURCE_COMMIT = "1a820e50c6fbd0276cde073c22bfffae78930868"
SOURCE_BLOB_SHA1 = "f5ba0d4f8f729236fdd8883a65189f2d6443338c"
SOURCE_PATH = "data/nba_archive_10Y.json"
SCREEN = "NBA_TOTALS_V2_SBR_DATE_ONLY_SCREEN_V1"
ALIASES = {"Golden State": "Warriors", "NewJersey": "Nets",
           "Bobcats": "Hornets", "NewOrleans": "Pelicans"}
BEGIN_HOLDOUT = 2015
END_HOLDOUT = 2021


def verify_archive_blob(raw_bytes: bytes) -> str:
    prefix = ("blob " + str(len(raw_bytes)) + "\0").encode("ascii")
    actual = hashlib.sha1(prefix + raw_bytes).hexdigest()
    if actual != SOURCE_BLOB_SHA1:
        raise ValueError("NBA_DATE_ONLY_ARCHIVE_BLOB_PIN_MISMATCH")
    return actual


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize(raw):
    """Replicate the pinned V1 reference archive normalization, without
    inventing fields missing from the raw archive.
    """
    events = []
    seen = set()
    for x in raw:
        home,away = str(x.get("home_team") or ""),str(x.get("away_team") or "")
        home,away = ALIASES.get(home,home),ALIASES.get(away,away)
        hp,ap = _number(x.get("home_final")),_number(x.get("away_final"))
        if not home or not away or home == away or hp is None or ap is None or hp + ap < 120:
            continue
        try:
            season,day = int(x["season"]),int(float(x["date"]))
        except (TypeError,ValueError,KeyError) as e:
            raise ValueError("NBA_DATE_ONLY_SEASON_OR_DATE_INVALID") from e
        try:
            datetime.strptime(str(day), "%Y%m%d")
        except ValueError as e:
            raise ValueError("NBA_DATE_ONLY_CALENDAR_DATE_INVALID") from e
        key=(day,home,away)
        if key in seen:
            raise ValueError("NBA_DATE_ONLY_DUPLICATE_FIXTURE")
        seen.add(key)
        events.append({"season":season,"day":day,"home":home,"away":away,
                       "hp":hp,"ap":ap,"market":_number(x.get("close_over_under"))})
    return sorted(events,key=lambda x:(x["day"],x["home"]))


def evaluate_calendar_archive(raw, *, begin=BEGIN_HOLDOUT, end=END_HOLDOUT):
    """Strict calendar-day-only accuracy diagnostic; no forward-clock authority.

    Parameters are exactly the unfitted V2 research construction:
    last 450 prior-DATE fixtures; >=30 league games, >=5 both teams;
    offensive/defensive strength shrunk by n/(n+20).
    """
    rows=normalize(raw)
    totals={"scored":0,"paired":0,"candidate_ss":0.0,"climatology_ss":0.0,
            "paired_candidate_ss":0.0,"paired_climatology_ss":0.0,
            "paired_market_ss":0.0,"under":0,"over":0,"tie":0}
    dates=set()
    for i,game in enumerate(rows):
        if not begin<=game["season"]<=end:
            continue
        past=[]
        for j in range(i-1,-1,-1):
            if rows[j]["day"] < game["day"]:
                past.append(rows[j])
                if len(past)==450:
                    break
        if len(past)<30:
            continue
        league=sum((g["hp"]+g["ap"])/2.0 for g in past)/len(past)
        home,away=game["home"],game["away"]
        teams={home:{"sc":[],"co":[]},away:{"sc":[],"co":[]}}
        for prior in past:
            ht,at=prior["home"],prior["away"]
            if ht in teams:
                teams[ht]["sc"].append(prior["hp"])
                teams[ht]["co"].append(prior["ap"])
            if at in teams:
                teams[at]["sc"].append(prior["ap"])
                teams[at]["co"].append(prior["hp"])
        if min(len(teams[home]["sc"]),len(teams[away]["sc"]))<5:
            continue
        def shrunk(vals):
            return ((sum(vals)/len(vals))-league)*len(vals)/(len(vals)+20.0)
        predicted=2*league+shrunk(teams[home]["sc"])+shrunk(teams[away]["co"])+shrunk(teams[away]["sc"])+shrunk(teams[home]["co"])
        baseline=2*league
        actual=game["hp"]+game["ap"]
        model_ss=(predicted-actual)**2
        base_ss=(baseline-actual)**2
        totals["scored"]+=1
        totals["candidate_ss"]+=model_ss
        totals["climatology_ss"]+=base_ss
        market=game["market"]
        if market is not None and 170<=market<=270:
            totals["paired"]+=1
            totals["paired_candidate_ss"]+=model_ss
            totals["paired_climatology_ss"]+=base_ss
            totals["paired_market_ss"]+=(market-actual)**2
            totals["under"]+=int(predicted<market)
            totals["over"]+=int(predicted>market)
            totals["tie"]+=int(predicted==market)
            dates.add(game["day"])
    def rmse(key,n):
        return math.sqrt(totals[key]/totals[n]) if totals[n] else None
    return {
        "screen":SCREEN,"source_commit":SOURCE_COMMIT,"source_blob_sha1":SOURCE_BLOB_SHA1,
        "source_path":SOURCE_PATH,
        "source_rows":len(raw),"normalized_rows":len(rows),
        "holdout_seasons":[begin,end],
        "game_clock_resolution":"CALENDAR_DATE_ONLY",
        "actual_result_available_time":"UNKNOWN",
        "historical_quote_capture_time":"UNKNOWN",
        "strict_prior_dates_only":True,
        "market_vintage":"UNKNOWN_NOT_ADMITTED",
        "market_baseline_authority":"INDICATIVE_NOT_VERIFIED",
        "promotion_authority":False,
        "model_status":"RESEARCH_ONLY",
        "model_scored_games":totals["scored"],
        "paired_games":totals["paired"],
        "paired_distinct_dates":len(dates),
        "candidate_rmse_all":rmse("candidate_ss","scored"),
        "climatology_rmse_all":rmse("climatology_ss","scored"),
        "candidate_rmse_paired":rmse("paired_candidate_ss","paired"),
        "climatology_rmse_paired":rmse("paired_climatology_ss","paired"),
        "indicative_market_rmse_paired":rmse("paired_market_ss","paired"),
        "candidate_minus_market_mse_paired":(
            (totals["paired_candidate_ss"]-totals["paired_market_ss"])/totals["paired"]
            if totals["paired"] else None),
        "model_under_reference":totals["under"],
        "model_over_reference":totals["over"],
        "model_equal_reference":totals["tie"],
        "indicative_reference_screen":_indicative_reference_verdict(
            rmse("paired_candidate_ss","paired"),rmse("paired_market_ss","paired")),
        "candidate_card_source_eligible":False,
        "market_admission":"NOT_VERIFIED",
        "screen_verdict_authority":"RESEARCH_DIAGNOSTIC_ONLY"}



def _indicative_reference_verdict(candidate_rmse, reference_rmse):
    """Report the *diagnostic* screen, never confer admission or PLAY.

    Equality is not outperformance. Even a better score would remain
    unadmitted until the source's quote-vintage/book requirements are met.
    """
    if candidate_rmse is None or reference_rmse is None:
        return "REFERENCE_UNMEASURED"
    if candidate_rmse >= reference_rmse:
        return "FAILED_INDICATIVE_REFERENCE_NOT_A_CARD_SOURCE"
    return "BETTER_INDICATIVE_ONLY_SOURCE_NOT_ADMITTED"


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",required=True,type=Path,
                        help="Unmodified pinned nba_archive_10Y.json")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args(argv)
    raw_bytes=args.source.read_bytes()
    verify_archive_blob(raw_bytes)
    result=evaluate_calendar_archive(json.loads(raw_bytes))
    text=json.dumps(result,sort_keys=True,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(text,encoding="utf-8")
    else:
        print(text,end="")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
