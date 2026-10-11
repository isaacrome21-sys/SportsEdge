#!/usr/bin/env python3
"""Phone-readable NFL/CFB cards from actual SportsEdge AUTO artifacts.

Presentation only: NEVER calculate probabilities, fabricate a missing price,
turn peer-book market probabilities into model estimates, or certify leans.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

CENTRAL = ZoneInfo("America/Chicago")
from pathlib import Path


def _utc(value):
    """Unknown or invalid timestamps cannot establish pregame availability."""
    try:
        t=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if t.tzinfo is None or t.utcoffset() is None:
            return None
        return t.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def _local_time(value):
    instant=_utc(value)
    return instant.astimezone(CENTRAL).strftime("%a %b %-d · %-I:%M %p CT") if instant else "MISSING"


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
    if sport=="NFL":
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
                "kickoff_utc":r.get("start_ts"),
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
    kickoff = _local_time(r.get("kickoff_utc"))
    observed = _local_time(r.get("quote_observed_at"))
    stamp = (f" · kickoff {kickoff} · quote {observed}"
             if r.get("quote_observed_at") is not None else f" · kickoff {kickoff}")
    return (f"- **{label}** · DK {price(r['price'])} · "
            f"estimate {pct(r['estimate_p'])} · edge {pct(r['edge'],True)} · "
            f"EV {pct(r['ev'],True)}{stamp} · {str(r['reason'])}")


def render(root: Path, run_url: str, *, asof: datetime | None = None):
    summary=json.loads((root/"summary.json").read_text(encoding="utf-8"))
    now=asof or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("PHONE_SUMMARY_ASOF_REQUIRES_TIMEZONE")
    now=now.astimezone(timezone.utc)
    lines=["## SportsEdge AUTO — ranked NFL / CFB","",
           f"Pregame snapshot: {now.astimezone(CENTRAL).strftime('%a %b %-d · %-I:%M %p CT')}. "
           "This is not a continuously updated live odds feed.","",
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
            for candidate in candidates(sport,payload):
                kickoff=_utc(candidate.get("kickoff_utc"))
                # Never display started-game prices as pregame opportunities.
                if kickoff is None or kickoff <= now:
                    continue
                picked.append(candidate)
        if sport=="CFB":
            lines.append("CFB model still requires out-of-sample validation; candidates are tracking only until then.")
            lines.append(f"Matched SDV games: {sum(int(x.get('priced_rows',0)) for x in cards)} modeled market rows; "
                         f"unmatched games: {state.get('unmatched_games','MISSING')}.")
        lines.append("Model status: "+", ".join(sorted(set(statuses))) if statuses else "Model status: MISSING")
        lines.append("")
        for role,title in (("BEST","Best Plays"),("LEAN","Top Leans")):
            lines.append(f"**{title}**")
            view=[r for r in picked if r["role"]==role][:5]
            if view:
                lines.extend(row_text(r) for r in view)
            else:
                lines.append("None with supported pregame pricing." if role=="BEST" else "No upcoming modeled leans.")
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
