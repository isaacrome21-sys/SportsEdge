#!/usr/bin/env python3
"""AUTO NFL player-prop quote capture. Independent from model probabilities.

Uses The Odds API event endpoint with one capped four-market group per event,
at most two upcoming games, and a fresh zero-credit quota preflight before each
call. A one-sided, mismatched, duplicated, stale, or unidentified offer cannot
become a research quote. Does not alter the game-card pipeline.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen,Request
from urllib.error import HTTPError
from scripts.collect_auto_dk_four_sports import good_price,iso_time,nfl_tickets
from scripts.odds_api_quota_guard import configured_keys,probe_quota

MARKETS={"player_pass_yds":"passing_yards","player_rush_yds":"rushing_yards",
         "player_reception_yds":"receiving_yards","player_receptions":"receptions"}
COST=len(MARKETS)
MAX_GAMES=2
RESERVE=76
TTL=600
ENDPOINT="https://api.the-odds-api.com/v4/sports/americanfootball_nfl/events"


def parse_pairs(event,asof):
    books=[b for b in event.get("bookmakers") or [] if isinstance(b,dict) and b.get("key")=="draftkings"]
    if len(books)!=1:return [],["DRAFTKINGS_BOOK_REQUIRED"]
    pairs=[]; rejected=[]
    for market in books[0].get("markets") or []:
        market_key=market.get("key")
        if market_key not in MARKETS:continue
        last=iso_time(market.get("last_update") or books[0].get("last_update"))
        if last is None or not 0<=(asof-last).total_seconds()<=TTL:
            rejected.append("QUOTE_TIMESTAMP_INVALID:"+str(market_key));continue
        grouped={}
        for x in market.get("outcomes") or []:
            if not isinstance(x,dict):continue
            side=str(x.get("name") or "").strip().upper()
            player=str(x.get("description") or "").strip()
            price=good_price(x.get("price"))
            try:line=float(x.get("point"))
            except (ValueError,TypeError,OverflowError):continue
            if side not in {"OVER","UNDER"} or not player or price is None or not 0<line<2000:
                continue
            grouped.setdefault((player.casefold(),line),[]).append((side,price,player))
        for (key,line),offers in sorted(grouped.items()):
            if len(offers)!=2 or {x[0] for x in offers}!={"OVER","UNDER"}:
                rejected.append("UNPAIRED_OR_DUPLICATE:"+str(market_key)+":"+key)
                continue
            o={which:(price,name) for which,price,name in offers}
            pairs.append({"market":MARKETS[market_key],"player":o["OVER"][1],
                          "line":line,"away_or_over_price":o["OVER"][0],
                          "home_or_under_price":o["UNDER"][0],
                          "quote_retrieved_at":last.isoformat(),
                          "raw":"ODDS_API_DK_EXACT_TWO_SIDE_"+str(market_key),
                          "provider_market":market_key})
    return pairs,rejected


def request_event(event_id,key,opener=urlopen):
    event_id=str(event_id or "")
    if not event_id or "/" in event_id:raise ValueError("INVALID_EVENT_ID")
    query=urlencode({"apiKey":key,"bookmakers":"draftkings",
                     "markets":",".join(MARKETS),"oddsFormat":"american"})
    url=ENDPOINT+"/"+event_id+"/odds?"+query
    with opener(Request(url,headers={"Accept":"application/json",
                 "User-Agent":"SportsEdge-AUTO-NFL-Props/1"}),timeout=30) as res:
        body=json.loads(res.read().decode("utf-8"))
    if not isinstance(body,dict):raise ValueError("INVALID_EVENT_RESPONSE")
    return body


def same_event(source,target):
    a=iso_time(source.get("commence_time"))
    b=iso_time(target.get("commence_time"))
    return bool(a and b and abs((a-b).total_seconds())<=900
        and str(source.get("provider_event_id"))==str(target.get("id"))
        and source.get("away")==target.get("away_team")
        and source.get("home")==target.get("home_team")
        and target.get("sport_key")=="americanfootball_nfl")


def collect(board,now,*,key_slots=None,preflight=probe_quota,fetch=request_event,max_games=MAX_GAMES):
    if not 0<=max_games<=MAX_GAMES:raise ValueError("MAX_PROP_GAMES_OUT_OF_RANGE")
    # Direct DK IDs are NOT Odds API event IDs. Never spend paid API credits
    # requesting a provider event using a different source's identifier.
    if board.get("source")=="DRAFTKINGS_DIRECT_WEB_V1":
        return {"schema":"SPORTSEDGE_NFL_AUTO_PROP_CAPTURE_V1",
                "status":"SKIPPED_DIRECT_DK_EVENT_IDS",
                "model_p":None,"estimate_p":None,
                "captured_at":now.isoformat(),"max_paid_credits":0,"events":[]}
    eligible=[]
    for game in board.get("games") or []:
        start=iso_time(game.get("commence_time"))
        if start and now<start<=now+timedelta(hours=26) and game.get("provider_event_id"):
            eligible.append(game)
    eligible=sorted(eligible,key=lambda x:x["commence_time"])[:max_games]
    slots=configured_keys() if key_slots is None else key_slots
    out={"schema":"SPORTSEDGE_NFL_AUTO_PROP_CAPTURE_V1","status":"NO_UPCOMING_EVENTS",
         "model_p":None,"estimate_p":None,"captured_at":now.isoformat(),
         "max_paid_credits":max_games*COST,"events":[]}
    for game in eligible:
        item={"event_id":game["provider_event_id"],"away":game["away"],
              "home":game["home"],"commence_time":game["commence_time"],
              "status":"BLOCKED","pairs":[],"reason":"UNAVAILABLE"}
        quota=preflight(slots,minimum_remaining=RESERVE+COST)
        if quota.get("state")!="READY":
            item["reason"]="QUOTA_"+str(quota.get("reason") or "UNKNOWN")
            out["events"].append(item)
            break
        allowed=set(quota.get("ready_key_slots") or [])
        for label,key in slots:
            if label not in allowed:continue
            try:
                response=fetch(game["provider_event_id"],key)
                if not same_event(game,response):
                    item["reason"]="WRONG_EVENT_TEAM_OR_KICKOFF"
                    break
                item["pairs"],errors=parse_pairs(response,now)
                item["rejections"]=errors[:50]
                item["status"]="QUOTES_READY" if item["pairs"] else "NO_PAIRED_MARKETS"
                item["reason"]=None if item["pairs"] else "NO_FRESH_TWO_SIDED_DK_PROPS"
                break
            except HTTPError as e:
                item["reason"]="PROVIDER_HTTP_"+str(e.code)
                break
            except (ValueError,TypeError,OSError,TimeoutError) as e:
                item["reason"]="PROVIDER_"+type(e).__name__
                break
        out["events"].append(item)
    if any(e["status"]=="QUOTES_READY" for e in out["events"]):
        out["status"]="QUOTE_PAIRS_READY"
    elif out["events"]:
        out["status"]="NO_PRICED_PROP_MARKETS"
    return out


def ticket_with_props(board,report,now):
    tickets=nfl_tickets(board.get("games") or [],now)
    from sportsedge.nfl_team_aliases import resolve_team,NflTeamAliasError
    accepted={str(row["event_id"]):row for row in report.get("events") or [] if row.get("status")=="QUOTES_READY"}
    for ticket in tickets.values():
        for game in ticket.get("games") or []:
            matches=[]
            for source in board.get("games") or []:
                if source.get("commence_time")!=game.get("commence_time"):
                    continue
                try:
                    if resolve_team(source["away"])==game["away"] and resolve_team(source["home"])==game["home"]:
                        matches.append(source)
                except NflTeamAliasError:
                    continue
            if len(matches)!=1:continue
            row=accepted.get(str(matches[0].get("provider_event_id")))
            # The source event key alone is never identity: the current ticket
            # must match BOTH teams and kickoff from the admission receipt.
            if (row and row.get("away")==matches[0].get("away")
                    and row.get("home")==matches[0].get("home")
                    and row.get("commence_time")==matches[0].get("commence_time")):
                game["markets"].extend(dict(p) for p in row["pairs"])
        ticket["source"]="ODDS_API_DK_BASE_PLUS_OPTIONAL_PAIRED_PROPS"
    return tickets


def nfl_season_for(start):
    return start.year if start.month>=3 else start.year-1


def write_injury_snapshot(board,out_dir,*,fetch=None):
    from sportsedge.sports.nfl.injury_report_source import fetch_nflverse_injury_snapshot
    from sportsedge.sports.nfl.context_autopull import NFLContextError
    fetch=fetch or fetch_nflverse_injury_snapshot
    seasons=sorted({nfl_season_for(t) for t in (iso_time(g.get("commence_time")) for g in board.get("games") or []) if t})
    if len(seasons)!=1:
        return {"status":"BLOCKED","reason":"INJURY_SNAPSHOT_SEASON_AMBIGUOUS"}
    target=Path(out_dir)/"nfl_injury_snapshot.json"
    try:
        snap=fetch(season=seasons[0])
    except NFLContextError as exc:
        return {"status":"BLOCKED","reason":"INJURY_SNAPSHOT_"+str(exc)}
    target.write_text(json.dumps(snap)+"\n",encoding="utf-8")
    return {"status":"READY","path":str(target)}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--game-odds",type=Path,default=Path("artifacts/auto_dk/nfl_odds.json"))
    ap.add_argument("--out-dir",type=Path,default=Path("artifacts/auto_dk_cards"))
    ap.add_argument("--max-games",type=int,default=MAX_GAMES)
    args=ap.parse_args()
    base=json.loads(args.game_odds.read_text(encoding="utf-8"))
    if base.get("sport")!="NFL" or base.get("status")!="READY":raise SystemExit("NFL_BASE_ODDS_REQUIRED")
    args.out_dir.mkdir(parents=True,exist_ok=True)
    # Free nflverse injury bytes are captured BEFORE the ticket observation
    # instant so their retrieval time is a valid PIT bound (nflverse dropped
    # per-row date_modified). Failure leaves props fail-closed downstream.
    write_injury_snapshot(base,args.out_dir)
    now=datetime.now(timezone.utc)
    report=collect(base,now,max_games=args.max_games)
    (args.out_dir/"nfl_prop_quote_report.json").write_text(json.dumps(report,indent=2)+"\n")
    for date,ticket in ticket_with_props(base,report,now).items():
        (args.out_dir/("nfl_prop_ticket_"+date+".json")).write_text(json.dumps(ticket,indent=2)+"\n")
    print(json.dumps({"status":report["status"],"pairs":sum(len(e["pairs"]) for e in report["events"]),
                      "max_paid_credits":report["max_paid_credits"]}))


if __name__=="__main__":
    main()
