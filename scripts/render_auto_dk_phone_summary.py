#!/usr/bin/env python3
"""Phone-readable NFL/CFB cards from actual SportsEdge AUTO artifacts.

Presentation only: NEVER calculate probabilities, fabricate a missing price,
turn peer-book market probabilities into model estimates, or certify leans.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


def _utc(value):
    try:
        t=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if t.tzinfo is None or t.utcoffset() is None:
            return None
        return t.astimezone(timezone.utc)
    except (TypeError,ValueError,OverflowError):
        return None


def _ct(value):
    t=_utc(value)
    return t.astimezone(ZoneInfo("America/Chicago")).strftime("%a %b %-d %-I:%M %p CT") if t else "MISSING"


def pct(value, signed=False):
    if value is None:
        return "MISSING"
    try:
        v=float(value)*100
        return f"{v:+.1f}%" if signed else f"{v:.1f}%"
    except (TypeError,ValueError,OverflowError):
        return "MISSING"


def price(value):
    if value is None:
        return "MISSING"
    try:
        v=int(float(value))
        return f"+{v}" if v>0 else str(v)
    except (TypeError,ValueError,OverflowError):
        return "MISSING"


def candidates(sport, payload):
    rows=[]
    if sport=="NFL" and payload.get("residual_pricing_enabled"):
        # All AUTO NFL prices now come from the separately declared residual
        # research adapter. Legacy calibrated absolute-model leans are NOT
        # displayed in this lane, even if a historical artifact contains them.
        for game in payload.get("games") or []:
            research=game.get("residual_research")
            if not isinstance(research,dict) or research.get("status")!="RESEARCH_ONLY":
                continue
            if research.get("validated_markets") != [] or not research.get("forward_track_signal"):
                continue
            for market in research.get("markets") or []:
                for side in market.get("sides") or []:
                    try:
                        ev=float(side["ev_per_dollar"])
                        edge=float(side["edge_probability_points"])
                        american=int(side["price_american"])
                    except (KeyError,TypeError,ValueError,OverflowError):
                        continue
                    # The existing +2% floor and -165 straight-price ceiling
                    # are unchanged. Forward CLV remains required for BEST.
                    if ev < 0.02 or edge <= 0 or american < -165:
                        continue
                    selection=str(side.get("selection") or "").lower()
                    if market.get("market")=="moneyline":
                        display=(game.get(selection) or selection)+" ML"
                    elif market.get("market")=="spread":
                        display=(game.get(selection) or selection)
                    elif market.get("market")=="total":
                        display=selection.title()
                    else:
                        continue
                    rows.append({
                        "role":"LEAN",
                        "matchup":f"{game.get('away','?')} @ {game.get('home','?')}",
                        "market":market["market"], "side":display,
                        "line":side.get("line"),"price":american,
                        "estimate_p":side.get("conditional_win_probability"),
                        "edge":edge,"ev":ev,"score":None,
                        "kickoff_utc":game.get("commence_time"),
                        "quote_observed_at":market.get("quote_retrieved_at"),
                        "quote_timestamp_source":"PROVIDER_LAST_UPDATE",
                        "reason":"RESIDUAL_RESEARCH_ONLY:PREDECLARED_SHRINKAGE_NOT_FORWARD_CLV",
                    })
    elif sport=="NFL":
        for game in payload.get("games") or []:
            for market in game.get("markets") or []:
                for field,label in (("pick","BEST"),("lean","LEAN")):
                    r=market.get(field)
                    if not isinstance(r,dict):
                        continue
                    rows.append({
                        "role":label,"matchup":f"{game.get('away','?')} @ {game.get('home','?')}",
                        "market":market.get("market"),"side":r.get("selection"),
                        "line":r.get("line"),"price":r.get("price_american"),
                        "estimate_p":r.get("estimate_p"),"edge":r.get("edge_probability_points"),
                        "ev":r.get("ev_per_dollar"),"score":r.get("score_0_100"),
                        "kickoff_utc":game.get("commence_time"),
                        "quote_observed_at":market.get("quote_retrieved_at"),
                        "quote_timestamp_source":market.get("quote_timestamp_source"),
                        "reason":r.get("lean_reason") or r.get("reason") or "MISSING"
                    })
    elif sport=="CFB":
        for r in payload.get("results") or []:
            status=str(r.get("bet_status") or "").upper()
            if status not in {"BET","LEAN"}:
                continue
            rows.append({
                "role":"BEST" if status=="BET" else "LEAN",
                "matchup":r.get("matchup"),"market":r.get("market"),
                "side":r.get("side"),"line":r.get("line"),
                "price":r.get("american_odds"),
                "estimate_p":r.get("estimate_p") if r.get("estimate_p") is not None else r.get("model_p"),
                "edge":r.get("edge"),"ev":r.get("expected_roi"),
                "score":r.get("score_0_100"),
                "reason":r.get("reason") or "MISSING",
            })
    for r in rows:
        if any(r.get(k) is None for k in ("estimate_p","edge","ev","price")):
            r["role"]="LEAN"
            r["reason"]="UNPRICED_OR_UNMODELED:"+str(r["reason"])
    def n(x):
        try:return float(x) if x is not None else float("-inf")
        except (ValueError,TypeError):return float("-inf")
    # Role is for presentation, never used to inflate an EV or confidence score.
    rows.sort(key=lambda x:(-n(x.get("ev")),-n(x.get("edge")),
                            str(x.get("matchup")),str(x.get("market")),str(x.get("side"))))
    return rows


def row_text(r):
    line=r.get("line")
    market=str(r.get("market") or "MARKET MISSING")
    if line is None:
        threshold=""
    elif "spread" in market.lower():
        threshold=f" {float(line):+g}"
    else:
        threshold=f" {float(line):g}"
    label=f"{r.get('matchup') or 'MATCHUP MISSING'} — {market} {r.get('side') or 'SIDE MISSING'}{threshold}"
    quote_label=("DK intake stamp" if r.get("quote_timestamp_source")=="INTAKE_STAMPED"
                 else "DK quote")
    pit=(f" · kickoff {_ct(r.get('kickoff_utc'))} · {quote_label} {_ct(r.get('quote_observed_at'))}"
         if r.get("kickoff_utc") else "")
    return (f"- **{label}** · DK {price(r['price'])} · "
            f"estimate {pct(r['estimate_p'])} · edge {pct(r['edge'],True)} · "
            f"EV {pct(r['ev'],True)}{pit} · {str(r['reason'])}")


def render(root: Path, run_url: str, *, as_of_date: str | None = None,
           asof: datetime | None = None):
    now=asof or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("PREGAME_SNAPSHOT_REQUIRES_TIMEZONE")
    now=now.astimezone(timezone.utc)
    as_of_date = as_of_date or now.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    summary=json.loads((root/"summary.json").read_text(encoding="utf-8"))
    lines=["## SportsEdge AUTO — ranked NFL / CFB","",
           f"Snapshot captured {_ct(now.isoformat())}. Not continuously live; game starts invalidate pregame prices.","",
           "Prices: captured DraftKings offers. Probabilities: existing SportsEdge engines.",
           "**EV and edge are model estimates, not a guarantee of profitability.**",""]
    for sport in ("NFL","CFB"):
        state=summary.get(sport) or {}
        lines.append(f"### {sport} · {state.get('status') or 'MISSING'}")
        cards=state.get("cards") or []
        if not cards:
            lines.extend(["No generated model card for this sport.",""])
            continue
        picked=[]
        statuses=[]
        for item in cards:
            if not item.get("json"):
                continue
            source=root/Path(item["json"]).name
            if not source.is_file():
                statuses.append("CARD_FILE_MISSING:"+source.name)
                continue
            payload=json.loads(source.read_text(encoding="utf-8"))
            statuses.append(str(item.get("model_status") or item.get("state") or "MISSING"))
            found=candidates(sport,payload)
            if sport=="NFL":
                for row in found:
                    row["slate_date"]=item.get("date")
                    kickoff=_utc(row.get("kickoff_utc"))
                    if kickoff is None or kickoff <= now:
                        continue
                    picked.append(row)
            else:
                picked.extend(found)
        if sport=="CFB":
            lines.append("CFB model still requires out-of-sample validation; candidates are tracking only until then.")
            lines.append(f"Matched SDV games: {sum(int(x.get('priced_rows',0)) for x in cards)} modeled market rows; "
                         f"unmatched games: {state.get('unmatched_games','MISSING')}.")
        lines.append("Model status: "+", ".join(sorted(set(statuses))) if statuses else "Model status: MISSING")
        lines.append("")
        if sport=="NFL":
            lines.append("Market-anchored residual prices are RESEARCH ONLY. No NFL market has positive forward CLV proof; these are not qualified wagers.")
            # A Sunday phone card must not mix Thursday's future NFL slate into
            # its ranked Sunday leans. Every displayed row keeps its game date.
            dates=sorted({r.get("slate_date") for r in picked if r.get("slate_date")})
            if not dates and picked:
                dates=["MISSING"]
            for date in dates:
                if date=="MISSING":
                    label="Date MISSING — check source artifact"
                else:
                    try:
                        dt=datetime.fromisoformat(date)
                        label=f"{dt.strftime('%a %b')} {dt.day}"
                    except ValueError:
                        label=str(date)
                    label+=(" · TODAY" if date==as_of_date else
                            " · UPCOMING" if date>as_of_date else " · PAST")
                lines.append(f"**NFL slate: {label}**")
                group=[r for r in picked if (r.get("slate_date") or "MISSING")==date]
                for role,title in (("BEST","Best Plays"),("LEAN","Top Leans")):
                    lines.append(f"**{title}**")
                    view=[r for r in group if r["role"]==role][:5]
                    if view:
                        lines.extend(row_text(r) for r in view)
                    else:
                        lines.append("None with supported pregame pricing." if role=="BEST" else "No upcoming modeled leans.")
                    lines.append("")
            if not dates:
                lines.append("No priced NFL candidates on any captured date.")
                lines.append("")
            lines.extend(["**NFL player props — research-only paired DK offers**",
                          "These are not backtest-qualified bets; availability depends on PIT player roles and verified game identity."])
            found_any=False
            for item in cards:
                prop=item.get("props") or {}
                state=str(prop.get("status") or "NOT_CAPTURED")
                if state!="RESEARCH_ONLY":
                    if state not in {"NOT_CAPTURED","NO_PAIRED_DK_PROPS"}:
                        lines.append(f"- {item.get('date','DATE MISSING')}: {state} · {prop.get('reason') or 'SOURCE_UNAVAILABLE'}")
                    continue
                candidate=root/Path(prop.get("json") or "").name
                if not candidate.is_file():
                    lines.append("- Missing research artifact (not priced)")
                    continue
                prop_card=json.loads(candidate.read_text(encoding="utf-8"))
                chosen=[r for r in prop_card.get("selected_rows") or [] if
                        r.get("status")=="PRICED" and
                        r.get("price_american") is not None and
                        r.get("estimate_p") is not None and
                        r.get("ev_per_dollar") is not None and
                        r.get("edge_probability_points") is not None]
                chosen.sort(key=lambda r:(-float(r["ev_per_dollar"]),-float(r["edge_probability_points"]),
                                          str(r.get("player")),str(r.get("market"))))
                for r in chosen[:4]:
                    found_any=True
                    lines.append(f"- {r.get('player') or 'PLAYER MISSING'} {r.get('market') or 'MARKET MISSING'} "
                        f"{r.get('selection') or 'SIDE MISSING'} {r.get('line') if r.get('line') is not None else 'MISSING'} · "
                        f"DK {price(r.get('price_american'))} · estimate {pct(r.get('estimate_p'))} · "
                        f"edge {pct(r.get('edge_probability_points'),True)} · EV {pct(r.get('ev_per_dollar'),True)} · RESEARCH ONLY")
            if not found_any:
                lines.append("No supported priced research prop candidates.")
            lines.append("")
        else:
            for role,title in (("BEST","Best Plays"),("LEAN","Top Leans")):
                lines.append(f"**{title}**")
                view=[r for r in picked if r["role"]==role][:5]
                if view:
                    lines.extend(row_text(r) for r in view)
                else:
                    lines.append("None with supported model pricing." if role=="BEST" else "No modeled leans.")
                lines.append("")
    lines.extend(["**Open the run for the full quotes, cards and PNG images (when available):**",run_url,"",
                  "Unavailable data stays MISSING. A directional lean is not a verified betting edge."])
    return "\n".join(lines)+"\n"


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,default=Path("artifacts/auto_dk_cards"))
    ap.add_argument("--output",type=Path,default=Path("artifacts/auto_dk_cards/phone_summary.md"))
    ap.add_argument("--run-url",required=True)
    args=ap.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(render(args.root,args.run_url),encoding="utf-8")


if __name__=="__main__":
    main()
