#!/usr/bin/env python3
"""Audit MLB paired manual lines and calculated research EV.

This is an integrity and risk audit, not an EV haircut or bookmaker scrape:
* bind each simulation result to exactly one pregame manual quote;
* ensure timestamp/book/side/market/line/subject and both prices reconcile;
* recompute EV with the correct push return, using p(win)*profit-p(loss);
* make extreme, unverified, small-sample pitcher results visible, not playable.

An original screenshot is evidence of a historical quote, NOT independently
confirmed present betting availability. No claim of live sportsbook EV is made.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

ARCHIVED_CARD_SHA256 = "ab670cbb6da6c73e4e8b1a891eaa9d0bb9d5c837e20d2e9f47e5ce5cff550f04"
REPORT_VERSION = "mlb_manual_quote_extreme_research_ev_audit_v1"
PITCHER_PREFIX = "PITCHER_"
EXTREME_RESEARCH_EV = 0.50
HIGH_RESEARCH_EV = 0.25
MIN_INDEPENDENT_PITCHER_STARTS = 30
MAX_RECOMMENDED_JUICE = 165


def parse_timestamp(text: Any) -> datetime:
    if not isinstance(text,str): raise ValueError("Missing quote timestamp")
    stamp=datetime.fromisoformat(text.replace("Z","+00:00"))
    if stamp.tzinfo is None: raise ValueError("Timezone-free screenshot quote")
    return stamp.astimezone(timezone.utc)


def key(row: Mapping[str, Any], *, is_card: bool) -> tuple[Any, ...]:
    market = str(row["market_type"])
    if market.startswith(PITCHER_PREFIX):
        subject = row.get("pitcher_name" if is_card else "subject_name")
        if not subject: raise ValueError("Missing pitcher quote identity")
        label=("pitcher",str(subject).strip().lower())
    elif market=="TEAM_TOTALS":
        team=row.get("team_side")
        if team not in ("AWAY","HOME"): raise ValueError("Missing team-total quote identity")
        label=("team",team)
    else:
        label=("game",None)
    return (str(row["game_id"]),market,str(row["side"]),float(row["line"]),label)


def american_profit(price: int) -> float:
    if isinstance(price,bool) or not isinstance(price,int) or (abs(price)<100):
        raise ValueError("Invalid American moneyline")
    return price/100 if price>0 else 100/(-price)


def implied_break_even(price: int) -> float:
    profit=american_profit(price)
    return 1/(1+profit)


def _row_evaluation(result: Mapping[str, Any], quote: Mapping[str, Any], *,
                    pair: Mapping[str, Any], observed: datetime, first_pitch: datetime) -> dict[str, Any]:
    price=int(result["american_odds"])
    if price != int(quote["price"]):
        raise ValueError("Quote price differs from simulation: stale or mismatched")
    if str(result["book"]).lower() != str(quote["book"]).lower():
        raise ValueError("Bookmaker identity mismatch")
    if parse_timestamp(result["observed_at"]) != observed:
        raise ValueError("Simulation consumed a differently timestamped quote")
    p=float(result["research_p"]); push=float(result["push_p"]); loss=float(result["loss_p"])
    if any(not isfinite(v) or v < 0 or v > 1 for v in (p,push,loss)):
        raise ValueError("Nonprobability or invalid settlement")
    if abs(p+push+loss-1)>1e-6:
        raise ValueError("Settlement masses not normalized")
    computed_ev=p*american_profit(price)-loss
    if abs(computed_ev-float(result["ev_per_dollar"]))>2e-5:
        raise ValueError("Research EV not consistent with win/loss/push settlement")

    metadata=result.get("probability_meta") or {}
    eff=metadata.get("effective_history_starts")
    pitcher=str(result["market_type"]).startswith(PITCHER_PREFIX)
    flags=[]
    if pitcher:
        if result.get("probability_source")!="CANONICAL_PITCHER_MARGINAL":
            flags.append("NONCANONICAL_PITCHER_PROBABILITY")
        if result.get("postseason_workload_adjusted") is not True:
            flags.append("POSTSEASON_WORKLOAD_NOT_ESTIMATED")
        if eff is None or not isfinite(float(eff)) or float(eff)<MIN_INDEPENDENT_PITCHER_STARTS:
            flags.append("SMALL_INDEPENDENT_PITCHER_HISTORY")
    if computed_ev >= EXTREME_RESEARCH_EV:
        flags.append("EXTREME_RESEARCH_EV")
    elif computed_ev>=HIGH_RESEARCH_EV:
        flags.append("LARGE_RESEARCH_EV")
    if price < -MAX_RECOMMENDED_JUICE:
        flags.append("STRAIGHT_BET_PRICE_EXCEEDS_USER_CAP")
    flags.append("MANUAL_QUOTE_NOT_INDEPENDENTLY_VERIFIED")
    if first_pitch <= observed:
        raise ValueError("No valid pregame quote")
    return {
        "game_id":result["game_id"],"market_type":result["market_type"],
        "side":result["side"],"line":result["line"],
        "pitcher_name":result.get("pitcher_name"),
        "team_side":result.get("team_side"),
        "quoted_price":price,"paired_price":int(pair["price"]),
        "observed_at_utc":observed.isoformat(),
        "minutes_quote_before_pitch":round((first_pitch-observed).total_seconds()/60,1),
        "winning_research_probability":p,"push_probability":push,
        "break_even_probability":implied_break_even(price),
        "recomputed_research_ev":computed_ev,
        "independent_pitcher_starts":eff if pitcher else None,
        "flags":flags,
        "independently_confirmed_live_quote":False,
        "actionable_from_this_audit":False,
        "reason":"Pre-game historical manual screenshot plus unvalidated research probabilities; no independent current market confirmation",
    }


def audit(card: Mapping[str,Any], quotes: Mapping[str,Any]) -> dict[str,Any]:
    selections=card.get("results")
    paired_rows=quotes.get("rows")
    if not isinstance(selections,list) or not isinstance(paired_rows,list):
        raise ValueError("Missing card results or paired manual snapshots")
    if card.get("official") is not False: raise ValueError("Expected research-only simulation card")
    index={}
    for row in paired_rows:
        if row.get("source")!="MANUAL" or row.get("book")!="draftkings":
            raise ValueError("Not the original paired DraftKings manual snapshot")
        observed=parse_timestamp(row["observed_at"])
        pitch=parse_timestamp(row["first_pitch_at"])
        if observed>=pitch: raise ValueError("Not a pregame screenshot timestamp")
        for side,price,other_side,other_price in (
            (row["side"],row["price"],row["paired_side"],row["paired_price"]),
            (row["paired_side"],row["paired_price"],row["side"],row["price"]),
        ):
            american_profit(price);american_profit(other_price)
            side_line=float(row["line"])
            if str(row["market_type"])=="RUN_LINE" and side!=str(row["side"]):
                side_line=-side_line
            item={**row,"side":side,"price":price,"line":side_line}
            identity=key(item,is_card=False)
            if identity in index:raise ValueError("Duplicate paired quote")
            index[identity]=(item,{"side":other_side,"price":other_price},observed,pitch)
    if len(index)!=2*len(paired_rows) or len(selections)!=len(index):
        raise ValueError("Simulation and source quote coverage do not match")
    output=[]
    consumed=set()
    for result in selections:
        identity=key(result,is_card=True)
        if identity in consumed or identity not in index:
            raise ValueError("Missing, duplicate or unmatched quote result")
        consumed.add(identity)
        quote,pair,observed,pitch=index[identity]
        output.append(_row_evaluation(result,quote,pair=pair,observed=observed,first_pitch=pitch))
    if len(consumed)!=len(index):raise ValueError("Unpriced historical quote")
    positives=[x for x in output if x["recomputed_research_ev"]>0]
    extreme=[x for x in output if x["recomputed_research_ev"]>=EXTREME_RESEARCH_EV]
    return {
        "version":REPORT_VERSION,
        "research_only":True,
        "independently_confirmed_quotes":0,
        "priced_sides":len(output),
        "positive_research_ev_sides":len(positives),
        "extreme_research_ev_sides":len(extreme),
        "research_ev_arithmetic_checked":True,
        "pushes_return_stake":True,
        "no_actionable_bets_released":True,
        "card_release_changed":False,
        "scope":"Historical manual DK screenshot integrity, not a live quote or independent market scrape",
        "rows":output,
    }


def main()->None:
    p=argparse.ArgumentParser()
    p.add_argument("--card",required=True)
    p.add_argument("--quotes",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    raw=Path(a.card).read_bytes()
    if sha256(raw).hexdigest()!=ARCHIVED_CARD_SHA256:
        raise ValueError("Historical replay artifact bytes differ from original")
    report=audit(json.loads(raw),json.loads(Path(a.quotes).read_text()))
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n")
    print(f"QUOTE_EV_AUDIT rows={report['priced_sides']} positives={report['positive_research_ev_sides']} extreme={report['extreme_research_ev_sides']}")
    print("RESEARCH_ONLY_NO_ACTIONABLE_PRICE_CONFIRMATION")


if __name__=="__main__":
    main()
