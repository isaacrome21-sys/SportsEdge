"""Cross-check open [BET] issues against the AUTO card leans.

Presentation only: reads EV/prices already written on the issues and cards.
No probability, EV, or price is computed or changed here.
"""
from __future__ import annotations

import re

SPORT_ALIASES={"NCAAF":"CFB","CFB":"CFB","NFL":"NFL","MLB":"MLB","NBA":"NBA","NHL":"NHL"}


def _key(text):
    return re.sub(r"[^a-z0-9]","",str(text or "").lower())


def _market(text):
    t=str(text or "").lower()
    if "total" in t or "over" in t or "under" in t:
        return "TOTAL"
    if "spread" in t or "run line" in t or "puck line" in t:
        return "SPREAD"
    if "money" in t or t in {"ml","h2h"}:
        return "MONEYLINE"
    return t.upper() or "MISSING"


def _side(text):
    t=str(text or "").strip().lower()
    for word in ("over","under"):
        if t.startswith(word):
            return word.upper()
    t=re.sub(r"\s*[+-]\d+(\.\d+)?\s*$","",t)
    return _key(t)


def _fields(body):
    out,cur={},None
    for line in (body or "").splitlines():
        if line.startswith("### "):
            cur=line[4:].strip(); out[cur]=[]
        elif cur is not None:
            out[cur].append(line)
    return {k:"\n".join(v).strip() for k,v in out.items()}


def _float(x):
    try:
        return float(str(x).replace("+","").replace("%","").strip())
    except (TypeError,ValueError):
        return None


def parse_bets(issues,as_of_date):
    bets=[]
    for issue in issues or []:
        title=str(issue.get("title") or "")
        if not title.startswith("[BET]"):
            continue
        f=_fields(issue.get("body"))
        if f.get("Game date") and f.get("Game date")!=as_of_date:
            continue
        sport=SPORT_ALIASES.get(str(f.get("Sport") or "").upper().strip(),str(f.get("Sport") or "MISSING").upper())
        source=re.search(r"\(([^()]*)\)\s*$",title)
        bets.append({
            "number":issue.get("number"),"sport":sport,
            "away":f.get("Away team") or "","home":f.get("Home team") or "",
            "market":f.get("Market") or "","pick":f.get("Pick") or "",
            "line":f.get("Line") or "","price":f.get("Price") or "",
            "ev_pct":_float(f.get("Tool EV %")),
            "source":source.group(1) if source else (f.get("Source") or "MISSING"),
        })
    bets.sort(key=lambda b:(-(b["ev_pct"] if b["ev_pct"] is not None else float("-inf")),b["number"] or 0))
    return bets


def _same_game(bet,row):
    m=str(row.get("matchup") or "")
    if "@" not in m:
        return False
    away,home=(_key(x) for x in m.split("@",1))
    ba,bh=_key(bet["away"]),_key(bet["home"])
    return bool(ba and bh) and (ba in away or away in ba) and (bh in home or home in bh)


def compare(bet,auto_rows):
    """Return (status, matching auto rows) for one bet."""
    game=[r for r in auto_rows if _same_game(bet,r)]
    if not game:
        return "NO_AUTO_LEAN",[]
    bm,bs=_market(bet["market"]),_side(bet["pick"])
    same_mkt=[r for r in game if _market(r.get("market"))==bm]
    if not same_mkt:
        return "DIFFERENT_MARKET",game
    if any(_side(r.get("side"))==bs or (bs and bs in _side(r.get("side"))) for r in same_mkt):
        return "AGREE",same_mkt
    return "OPPOSITE_SIDE",same_mkt


def _auto_label(r):
    line=r.get("line")
    ln="" if line is None else f" {line:+g}" if "spread" in str(r.get("market")).lower() else f" {line:g}"
    ev=r.get("ev")
    evs="EV MISSING" if ev is None else f"EV {float(ev)*100:+.1f}%"
    return f"{r.get('market')} {r.get('side')}{ln} ({evs})"


def render_crosscheck(issues,auto_rows_by_sport,as_of_date):
    bets=parse_bets(issues,as_of_date)
    lines=["### Logged [BET] picks vs AUTO leans",
           f"Open [BET] issues for {as_of_date}, ranked by EV (high to low). EV is the value written on each issue."]
    if not bets:
        return lines+["No open [BET] issues for this date.",""]
    flagged=0
    for sport in sorted({b["sport"] for b in bets}):
        lines.append(f"**{sport}**")
        auto=auto_rows_by_sport.get(sport) or []
        for b in [x for x in bets if x["sport"]==sport]:
            status,rows=compare(b,auto)
            ev="EV MISSING" if b["ev_pct"] is None else f"EV {b['ev_pct']:+.1f}%"
            flag={"OPPOSITE_SIDE":" · ⚠️ CONFLICT: AUTO lean is the other side",
                  "DIFFERENT_MARKET":" · ⚠️ CONFLICT: AUTO lean is a different market",
                  "AGREE":" · ✅ AUTO agrees","NO_AUTO_LEAN":" · no AUTO lean on this game"}[status]
            if status in {"OPPOSITE_SIDE","DIFFERENT_MARKET"}:
                flagged+=1
            auto_txt=("; AUTO: "+", ".join(_auto_label(r) for r in rows[:2])) if rows else ""
            lines.append(f"- **{b['away']} @ {b['home']} — {b['market']} {b['pick']} {b['line']}** · "
                         f"{b['price']} · {ev} · {b['source']} · #{b['number']}{flag}{auto_txt}")
        lines.append("")
    lines.append(f"Games where the two sources disagree: {flagged}.")
    lines.append("")
    return lines
