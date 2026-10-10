#!/usr/bin/env python3
"""Research-only CFB same-line cross-book arbitrage screen.

Input: saved TheOddsAPI-style events with bookmaker-market two-way quotes and
market.last_update UTC. One leg must be at DraftKings and the other at another
independent sportsbook. This never fetches a stale historical quote or creates
model probabilities. A positive mathematical *two-price* return is conditional
on actually securing BOTH prices, legal book availability, settlement matching,
and stakes accepted. No execution, automatic staking or promotion authority.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = "CFB_EXACT_LINE_CROSSBOOK_ARB_RESEARCH_V1"
MAX_AGE_SECONDS = 120
MIN_LOCKED_RETURN = 0.005  # 0.5% theoretical return at unchanged two-sided prices
PRICE_CAP = -165

# User's Illinois collegiate sports restriction. Exclude any listed participant.
IL_SCHOOLS = {
    "illinois","northern illinois","eastern illinois","western illinois",
    "southern illinois","illinois state","northwestern","chicago state",
    "uic","loyola chicago","loyola (il)","depaul","bradley",
    "siu edwardsville","illinois chicago","roosevelt",
}


def _normalize_team(name):
    clean=re.sub(r"[^a-z0-9 ]", " ",str(name or "").lower())
    return " ".join(clean.split())


def excluded_illinois(away,home):
    for name in (away,home):
        school=_normalize_team(name)
        if "illinois" in school or school in IL_SCHOOLS:
            return True
    return False


def _utc(raw):
    try:
        dt=datetime.fromisoformat(str(raw).replace("Z","+00:00"))
    except (ValueError,TypeError,OverflowError) as exc:
        raise ValueError("CFB_ARB_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("CFB_ARB_TIMESTAMP_TZ_REQUIRED")
    return dt.astimezone(timezone.utc)


def _odds(raw):
    try:
        val=float(raw)
    except (TypeError,ValueError) as exc:
        raise ValueError("CFB_ARB_AMERICAN_ODDS_INVALID") from exc
    if not math.isfinite(val) or val==0 or (-100<val<100):
        raise ValueError("CFB_ARB_AMERICAN_ODDS_INVALID")
    if val < PRICE_CAP:
        return None
    decimal = 1 + (100 / abs(val) if val < 0 else val / 100)
    return val,decimal,1/decimal


def _market_pair(market, outcomes, home, away):
    """Produce exact opposing, named selections; mixed line identities fail."""
    if not isinstance(outcomes,list) or len(outcomes)!=2:
        return None
    pairs={}
    for item in outcomes:
        try:
            price=_odds(item["price"])
            if price is None:return None
            name=str(item["name"]).strip()
            point=item.get("point")
            if market in {"h2h","spreads"}:
                if name not in {home,away}: return None
                key="HOME" if name==home else "AWAY"
            elif market=="totals":
                key=name.upper()
                if key not in {"OVER","UNDER"}:return None
            else:return None
            if key in pairs:return None
            p=float(point) if point is not None else None
            if market!="h2h" and (p is None or not math.isfinite(p)):return None
            pairs[key]={"odds":price[0],"decimal":price[1],"implied":price[2],"point":p}
        except (KeyError,ValueError,TypeError):
            return None
    need={"HOME","AWAY"} if market in {"h2h","spreads"} else {"OVER","UNDER"}
    if set(pairs)!=need:return None
    if market=="spreads" and abs(pairs["HOME"]["point"]+pairs["AWAY"]["point"])>1e-8:return None
    if market=="totals" and abs(pairs["OVER"]["point"]-pairs["UNDER"]["point"])>1e-8:return None
    return pairs


def _identity(market,side,record):
    if market=="h2h":return ("MONEYLINE",None)
    if market=="totals":return ("TOTAL",record["point"])
    if market=="spreads":
        # Normalize all spread thresholds to HOME handicap identity.
        p=record["point"] if side=="HOME" else -record["point"]
        return ("SPREAD",round(p,6))
    raise ValueError("CFB_ARB_MARKET_UNSUPPORTED")


def screen(events,*,asof,stale_seconds=MAX_AGE_SECONDS,min_return=MIN_LOCKED_RETURN):
    now=_utc(asof) if isinstance(asof,str) else _utc(asof.isoformat())
    if not 0<stale_seconds<=600:raise ValueError("CFB_ARB_STALENESS_INVALID")
    if not 0<min_return<0.2:raise ValueError("CFB_ARB_RETURN_THRESHOLD_INVALID")
    if not isinstance(events,list):raise ValueError("CFB_ARB_EVENTS_ARRAY_REQUIRED")
    matches=[]
    excluded_count=0
    stale_count=0
    pushable_contracts_skipped=0
    for event in events:
        if not isinstance(event,dict):continue
        home=str(event.get("home_team") or "")
        away=str(event.get("away_team") or "")
        if not home or not away or home==away:continue
        if excluded_illinois(away,home):
            excluded_count+=1
            continue
        try: kickoff=_utc(event["commence_time"])
        except (ValueError,KeyError):continue
        if kickoff<=now:continue
        offers={}
        for book in event.get("bookmakers") or []:
            if not isinstance(book,dict):continue
            key=str(book.get("key") or "").lower().strip()
            if not key:continue
            for market in book.get("markets") or []:
                if not isinstance(market,dict):continue
                kind=str(market.get("key") or "").lower()
                if kind not in {"h2h","spreads","totals"}:continue
                try: updated=_utc(market.get("last_update") or book.get("last_update"))
                except ValueError:continue
                age=(now-updated).total_seconds()
                if age<0 or age>stale_seconds:
                    stale_count+=1
                    continue
                paired=_market_pair(kind,market.get("outcomes"),home,away)
                if paired is None:continue
                for side,rec in paired.items():
                    ident=_identity(kind,side,rec)
                    ix=(key,ident,side)
                    if ix in offers:
                        # Multiple different offers for same market/book are ambiguous.
                        offers[ix]=None
                    else:
                        offers[ix]={**rec,"book":key,"side":side,
                                    "quote_updated_at":updated.isoformat()}
        for ident in sorted({entry[1] for entry in offers},key=str):
            # Whole-number CFB spreads/totals push when the exact score lands
            # on the threshold. Both opposing bets then refund stakes, so an
            # advertised positive LOCKED return would be false in that state.
            # Restrict guaranteed-return candidates to non-pushable contracts.
            if ident[0] in {"SPREAD", "TOTAL"} and float(ident[1]).is_integer():
                pushable_contracts_skipped+=1
                continue
            dk_side=[x for (bk,k,_),x in offers.items()
                     if bk=="draftkings" and k==ident and x is not None]
            peers=[x for (bk,k,_),x in offers.items()
                   if bk!="draftkings" and k==ident and x is not None]
            candidates=[]
            for dk in dk_side:
                for peer in peers:
                    if dk["side"]==peer["side"]:continue
                    total=dk["implied"]+peer["implied"]
                    if not total<1:continue
                    locked_return=1/total-1
                    if locked_return < min_return:continue
                    # Equal gross payout split of $100, before rounding.
                    leg_1=100*dk["implied"]/total
                    leg_2=100*peer["implied"]/total
                    candidates.append({
                        "game_id":str(event.get("id") or ""),
                        "matchup":f"{away} @ {home}",
                        "commence_time":kickoff.isoformat(),
                        "market":ident[0],"home_handicap_or_total":ident[1],
                        "draftkings_leg":{**dk,"suggested_stake_per_100":round(leg_1,2)},
                        "other_book_leg":{**peer,"suggested_stake_per_100":round(leg_2,2)},
                        "implied_sum":round(total,6),
                        "theoretical_locked_return_pct":round(100*locked_return,3),
                        "outcome":"RESEARCH_ONLY_VERIFY_BOTH_PRICES",
                        "executable_confirmed":False,
                    })
            if candidates:
                best=max(candidates,key=lambda v:v["theoretical_locked_return_pct"])
                matches.append(best)
    return {
        "schema":SCHEMA,"asof":now.isoformat(),"input_event_count":len(events),
        "excluded_illinois_events":excluded_count,
        "stale_offer_count":stale_count,
        "whole_point_push_contracts_skipped":pushable_contracts_skipped,
        "theoretical_pair_count":len(matches),
        "status":"POTENTIAL_CROSSBOOK_PRICING" if matches else "NO_FRESH_ARBITRAGE_IDENTIFIED",
        "candidates":sorted(matches,key=lambda x:-x["theoretical_locked_return_pct"]),
        "authority":{"model_p":False,"validated_positive_ev_wagers":False,
                     "bets_placed":False,"staking_authority":False,
                     "execution_confirmed":False,"source_quotes_only":True},
        "warning":"Both book offers, opposing outcome settlement, stake limits, availability and acceptance must be independently confirmed at time of placement."
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input-json",type=Path,required=True)
    ap.add_argument("--asof",required=True,help="UTC with timezone, e.g. 2026-10-09T23:00:00Z")
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    payload=screen(json.loads(args.input_json.read_text(encoding="utf-8")),asof=args.asof)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(f"CFB_CROSSBOOK_ARBITRAGE_SCREEN status={payload['status']} candidates={payload['theoretical_pair_count']}")


if __name__=="__main__":
    main()
