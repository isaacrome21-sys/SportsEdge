#!/usr/bin/env python3
"""Four-sport automatic DK sportsbook intake, independently of model probabilities.

Uses the repo's existing Odds API keys and zero-cost quota probe. The provider
supplies DK prices; peer books are context only. Explicit timestamps and
same-market opposing quotes are mandatory. An outage is never a fake zero edge.
No live sportsbook network calls occur at import time.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sports.common.ev_math import EVError, american_to_decimal, devig
from scripts.odds_api_quota_guard import configured_keys, probe_quota

SPORTS = {
    "NFL": "americanfootball_nfl",
    "CFB": "americanfootball_ncaaf",
    "MLB": "baseball_mlb",
    "NBA": "basketball_nba",
}
BOOKMAKERS = (
    "draftkings", "pinnacle", "fanduel", "betmgm", "williamhill_us",
    "betrivers", "betonlineag", "bovada",
)
MARKETS = ("h2h", "spreads", "totals")
CHICAGO = ZoneInfo("America/Chicago")
API = "https://api.the-odds-api.com/v4/sports"
MAX_MARKET_AGE_SECONDS = 600
# Preserve the existing NFL-confirmation quota reservation on shared keys.
DEFAULT_RESERVE = 76
# Preserve at least one future NFL and CFB 3-market poll before optional MLB/NBA.
FOOTBALL_PRIORITY_BUFFER = 2 * len(MARKETS)
SPORT_PRIORITY = ("NFL", "CFB", "MLB", "NBA")
CREDIT_COST = len(MARKETS)  # One group of <=10 named bookmakers.
IL_TEAMS = (
    "illinois fighting", "illinois state", "southern illinois",
    "northern illinois", "western illinois", "eastern illinois",
    "northwestern wildcats", "loyola chicago", "uic flames",
)
# Account and bookmaker coverage are provider-dependent; do not assume a plan.


def iso_time(value):
    try:
        v = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return v.astimezone(timezone.utc) if v.utcoffset() is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def good_price(value):
    try:
        p = float(value)
        if p != p or p in (float("inf"), float("-inf")) or -100 < p < 100:
            return None
        if int(p) != p:
            return None
        return int(p)
    except (ValueError, TypeError, OverflowError):
        return None


def paired(event, book, market_key, now):
    """Return both DK/peer sides or None; NEVER infer an absent opposite."""
    away, home = str(event.get("away_team") or ""), str(event.get("home_team") or "")
    if not away or not home or away == home:
        return None
    for m in book.get("markets") or []:
        if m.get("key") != market_key:
            continue
        observed = iso_time(m.get("last_update") or book.get("last_update"))
        if observed is None or not 0 <= (now-observed).total_seconds() <= MAX_MARKET_AGE_SECONDS:
            return None
        outcomes = m.get("outcomes") or []
        if len(outcomes) != 2 or not all(isinstance(x,dict) for x in outcomes):
            return None
        names = [str(x.get("name") or "") for x in outcomes]
        prices = [good_price(x.get("price")) for x in outcomes]
        if any(x is None for x in prices):
            return None
        def point(x):
            try:
                v = float(x.get("point"))
                return v if abs(v) < 100000 and v == v else None
            except (TypeError, ValueError, OverflowError):
                return None
        if market_key == "h2h":
            if set(names) != {away, home}:
                return None
            out = {
                "line": None, "away": prices[names.index(away)],
                "home": prices[names.index(home)],
            }
        elif market_key == "spreads":
            if set(names) != {away, home}:
                return None
            a, h = outcomes[names.index(away)], outcomes[names.index(home)]
            ap, hp = point(a), point(h)
            if ap is None or hp is None or abs(ap+hp)>1e-9:
                return None
            out = {"line": ap, "away": prices[names.index(away)],
                   "home": prices[names.index(home)]}
        elif market_key == "totals":
            if {x.lower() for x in names} != {"over","under"}:
                return None
            o, u = outcomes[names.index(next(x for x in names if x.lower()=="over"))], outcomes[names.index(next(x for x in names if x.lower()=="under"))]
            op, up = point(o), point(u)
            if op is None or up is None or abs(op-up)>1e-9:
                return None
            out = {"line": op, "over": good_price(o["price"]), "under": good_price(u["price"])}
        else:
            return None
        out.update(book=book.get("key"), observed_at=observed.isoformat(),
                   provider="THE_ODDS_API_V4", sport=event.get("sport_key"))
        return out
    return None


def _pair_fair(market):
    """POWER_V1; sensitivity error is a missing peer fair price, not zero."""
    keys = ("away","home") if market.get("line") is None or ("away" in market) else ("over","under")
    try:
        return devig([american_to_decimal(market[k]) for k in keys],
                     trigger_american=400, max_spread_pp=1.0)
    except (EVError, ValueError, TypeError):
        return None


def _same_line(a,b,market_key):
    if market_key=="h2h":
        return a.get("line") is None and b.get("line") is None
    try:
        return abs(float(a["line"])-float(b["line"])) < 1e-9
    except (ValueError, TypeError, KeyError):
        return False


def _fair_context(target, peers, market_key):
    """Market-only no-vig, with exact per-peer receipt provenance retained."""
    eligible=[]
    price_pairs_by_book={}
    for p in peers:
        if not _same_line(target,p,market_key):
            continue
        fair=_pair_fair(p)
        if fair:
            eligible.append((p["book"],fair,p.get("observed_at"),p.get("line")))
            sides=("over","under") if market_key=="totals" else ("away","home")
            price_pairs_by_book[p["book"]]={"book":p["book"],
                                             "prices":{side:p[side] for side in sides}}
    def provenance(chosen):
        return [{"book":book,"observed_at":at,"line":line} for book,_,at,line in chosen]
    def price_receipts(chosen):
        return [price_pairs_by_book[book] for book,_,_,_ in chosen]
    for entry in eligible:
        book,vals,_,_=entry
        if book=="pinnacle":
            return {"method":"PINNACLE_POWER_V1","fair":vals,"books":[book],
                    "peer_evidence":provenance([entry]),
                    "peer_price_pairs":price_receipts([entry]),"model_probability":None}
    if len(eligible) < 2:
        return {"method":"MISSING","fair":None,"books":[],
                "peer_evidence":[],"peer_price_pairs":[],"model_probability":None}
    import statistics
    return {"method":"MULTIBOOK_MEDIAN_POWER_V1",
            "fair":[statistics.median([v[1][0] for v in eligible]),
                    statistics.median([v[1][1] for v in eligible])],
            "books":[v[0] for v in eligible],
            "peer_evidence":provenance(eligible),
            "peer_price_pairs":price_receipts(eligible),"model_probability":None}


def events_to_board(sport, events, now):
    """Return zero-filled-nothing, provenance-safe DK compact game markets."""
    games=[]
    for ev in events:
        if not isinstance(ev,dict) or ev.get("sport_key") != SPORTS[sport]:
            continue
        start=iso_time(ev.get("commence_time"))
        if start is None or start <= now or start > now+timedelta(days=7):
            continue
        away,home=ev.get("away_team"),ev.get("home_team")
        if not isinstance(away,str) or not isinstance(home,str) or away==home:
            continue
        if sport=="CFB" and any(str(t).lower().startswith(IL_TEAMS) for t in (away,home)):
            continue
        books={str(b.get("key") or ""):b for b in ev.get("bookmakers") or [] if isinstance(b,dict)}
        if "draftkings" not in books:
            continue
        markets={}
        peer_info={}
        peer_books={}
        for market in MARKETS:
            dk=paired(ev,books["draftkings"],market,now)
            if dk is None:
                continue
            markets[market]=dk
            peers=[p for bk,b in books.items() if bk!="draftkings"
                   for p in [paired(ev,b,market,now)] if p is not None]
            for peer in peers:
                target = peer_books.setdefault(peer["book"],{"book":peer["book"]})
                if market=="h2h":
                    target["ml"]=[peer["away"],peer["home"]]
                elif market=="spreads":
                    target["spread"]=[peer["line"],peer["away"],peer["home"]]
                elif market=="totals":
                    target["total"]=[peer["line"],peer["over"],peer["under"]]
                target["observed_at"]=peer["observed_at"]
            ref=_fair_context(dk,peers,market)
            ref.update(provider_event_id=ev.get("id"),market_key=market,
                       dk_observed_at=dk["observed_at"],dk_line=dk.get("line"))
            peer_info[market]=ref
        if not markets:
            continue
        games.append({
            "provider_event_id":ev.get("id"),
            "away":away,"home":home,
            "commence_time":start.isoformat(),
            "slate_ct":start.astimezone(CHICAGO).date().isoformat(),
            "markets":markets,"reference":peer_info,
            "peer_books":sorted(peer_books.values(),key=lambda x:x["book"]),
            "estimate_p":None,
        })
    games.sort(key=lambda x:(x["commence_time"],str(x["provider_event_id"])))
    return games


def nfl_tickets(games, captured_at, *, source="ODDS_API_DK_AUTO"):
    from sportsedge.nfl_team_aliases import resolve_team, NflTeamAliasError
    per_day={}
    for g in games:
        try:
            away,home=resolve_team(g["away"]),resolve_team(g["home"])
        except NflTeamAliasError:
            continue
        mk=[]
        for key,label in (("h2h","moneyline"),("spreads","spread"),("totals","total")):
            row=g["markets"].get(key)
            if row is None:
                continue
            is_total=key=="totals"
            mk.append({"market":label,"line":row["line"],
                       "away_or_over_price":row["over"] if is_total else row["away"],
                       "home_or_under_price":row["under"] if is_total else row["home"],
                       "raw":"THE_ODDS_API_DK_TWO_SIDED",
                       "team":None,"player":None,
                       "quote_retrieved_at":row["observed_at"],
                       "quote_timestamp_source":row.get("timestamp_source","PROVIDER_LAST_UPDATE")})
        if not mk:
            continue
        per_day.setdefault(g["slate_ct"],[]).append({
            "away":away,"home":home,"header":away+" @ "+home,"markets":mk,
            "commence_time":g["commence_time"]})
    return {d:{"sport":"NFL","slate":d,"observed_at":captured_at.isoformat(),
               "source":source,"games":games}
            for d,games in per_day.items()}


def cfb_compact(games):
    rows=[]
    for g in games:
        m=g["markets"]
        row={"away":g["away"],"home":g["home"],
             "start_ts":g["commence_time"],
             "quote_source":"THE_ODDS_API_DK_AUTO",
             "book_quote_receipt_verified":True,
             "peers":g.get("peer_books") or [],
             "quote_captured_at":next(iter(g["markets"].values()))["observed_at"]}
        if "h2h" in m: row["ml"]=[m["h2h"]["away"],m["h2h"]["home"]]
        if "spreads" in m: row["spread"]=[m["spreads"]["line"],m["spreads"]["away"],m["spreads"]["home"]]
        if "totals" in m: row["total"]=[m["totals"]["line"],m["totals"]["over"],m["totals"]["under"]]
        rows.append(row)
    return rows


def mlb_line_text(games):
    lines=[]
    for g in games:
        m=g["markets"]
        lines.append(g["away"]+" @ "+g["home"])
        if "h2h" in m: lines.append("ML {} {}".format(m["h2h"]["away"],m["h2h"]["home"]))
        if "spreads" in m:
            a=m["spreads"]
            lines.append("RL {:+g} {} {}".format(a["line"],a["away"],a["home"]))
        if "totals" in m:
            a=m["totals"]
            lines.append("Total {:g} {} {}".format(a["line"],a["over"],a["under"]))
        lines.append("")
    return "\n".join(lines)


def fetch(sport,key,opener=urlopen):
    q=urlencode({"apiKey":key,"bookmakers":",".join(BOOKMAKERS),
                 "markets":",".join(MARKETS),"oddsFormat":"american","dateFormat":"iso"})
    req=Request(API+"/"+SPORTS[sport]+"/odds?"+q,headers={"Accept":"application/json",
                "User-Agent":"SportsEdge-QuoteIntake/1"})
    with opener(req,timeout=30) as response:
        value=json.loads(response.read().decode("utf-8"))
        if not isinstance(value,list):
            raise ValueError("ODDS_RESPONSE_NOT_LIST")
        return value


def discover_active_sports(key, opener=urlopen):
    """The provider's free /sports listing avoids paid calls during offseasons.

    Return None on failure: the per-sport quota guard remains authoritative.
    """
    try:
        req=Request(API+"/?"+urlencode({"apiKey":key}),
                    headers={"Accept":"application/json","User-Agent":"SportsEdge-ActiveSports/1"})
        with opener(req,timeout=20) as response:
            payload=json.loads(response.read().decode("utf-8"))
        if not isinstance(payload,list):
            return None
        return {str(x["key"]) for x in payload if isinstance(x,dict) and x.get("active") is True and x.get("key")}
    except (OSError,ValueError,TypeError,KeyError):
        return None


def prioritize_sports(sports):
    """Football goes first even when a phone dispatch lists other sports first."""
    selected = set(sports)
    return [name for name in SPORT_PRIORITY if name in selected]


def collect(sports,out_dir,now,reserve,provider_fetch=fetch,quota_probe=probe_quota,active_sports=None):
    """A snapshot per sport. Preserve NFL/CFB future credit capacity."""
    out_dir.mkdir(parents=True,exist_ok=True)
    snapshots={}
    keys=configured_keys()
    for sport in prioritize_sports(sports):
        active = active_sports is None or SPORTS[sport] in active_sports
        # Lower-priority sports cannot consume the minimum credits required
        # for another round of NFL+CFB even if the provider reports both active.
        minimum = reserve + CREDIT_COST + (FOOTBALL_PRIORITY_BUFFER if sport in {"MLB", "NBA"} else 0)
        quota = (quota_probe(keys,minimum_remaining=minimum)
                 if active else {"state":"BLOCKED","reason":"SPORT_INACTIVE",
                                 "max_remaining":None,"ready_key_slots":[]})
        record={"sport":sport,"captured_at_utc":now.isoformat(),
                "source":"THE_ODDS_API_V4","requested_markets":list(MARKETS),
                "cost_budget_credits":CREDIT_COST,
                "quota_remaining_preflight":quota["max_remaining"],
                "status":"UNAVAILABLE","reason":quota["reason"],
                "games":[],"estimate_p":None}
        if quota["state"]=="READY":
            ready={name for name in quota["ready_key_slots"]}
            # One successful key per sport; never run multiple paid sources in parallel.
            for name,key in keys:
                if name not in ready: continue
                try:
                    events=provider_fetch(sport,key)
                    record["games"]=events_to_board(sport,events,now)
                    record["status"]="READY" if record["games"] else "NO_DK_MARKETS"
                    record["reason"]=None if record["games"] else "NO_FRESH_PAIRED_DK_LINES"
                    break
                except HTTPError as exc:
                    # Plan not entitled to a sport: moving keys does not grant access.
                    record["reason"]="PROVIDER_HTTP_"+str(exc.code)
                    if exc.code in (401,403,429):break
                except (ValueError, OSError, TimeoutError) as exc:
                    record["reason"]="FETCH_FAILED_"+type(exc).__name__
        snapshots[sport]=record
        path=out_dir/(sport.lower()+"_odds.json")
        path.write_text(json.dumps(record,indent=2,sort_keys=True)+"\n",encoding="utf-8")
        if sport=="NFL":
            for date,ticket in nfl_tickets(record["games"],now).items():
                (out_dir/("nfl_ticket_"+date+".json")).write_text(
                    json.dumps(ticket,indent=2)+"\n",encoding="utf-8")
        elif sport=="CFB":
            (out_dir/"cfb_dk_board.json").write_text(
                json.dumps(cfb_compact(record["games"]),indent=2)+"\n",encoding="utf-8")
        elif sport=="MLB":
            (out_dir/"mlb_dk_lines.txt").write_text(mlb_line_text(record["games"]),encoding="utf-8")
    summary=["# SportsEdge automatic DK odds","", "DK book quotes from The Odds API; POWER_V1 references are context, NOT a model prediction.",""]
    for name,r in snapshots.items():
        summary.append("- {}: {} · {} DK games · {}".format(
            name,r["status"],len(r["games"]),r["reason"] or "FRESH_PAIRED_LINES"))
    summary.extend(["","Missing games or markets need another source. No odds or probabilities were invented.",
                    "NBA: quote capture only until an NBA predictive engine is ready."])
    (out_dir/"summary.md").write_text("\n".join(summary)+"\n",encoding="utf-8")
    return snapshots


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--sports",nargs="+",choices=list(SPORTS),default=list(SPORTS))
    ap.add_argument("--out-dir",type=Path,default=Path("artifacts/auto_dk"))
    ap.add_argument("--reserve",type=int,default=DEFAULT_RESERVE)
    args=ap.parse_args()
    if args.reserve < DEFAULT_RESERVE:
        raise SystemExit("FROZEN_NFL_CONFIRMATION_RESERVE_CANNOT_DECREASE")
    keys=configured_keys()
    active=discover_active_sports(keys[0][1]) if keys else None
    snapshots=collect(args.sports,args.out_dir,datetime.now(timezone.utc),
                      args.reserve,active_sports=active)
    print(json.dumps({s:{"status":r["status"],"games":len(r["games"]),
                         "reason":r["reason"]} for s,r in snapshots.items()}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
