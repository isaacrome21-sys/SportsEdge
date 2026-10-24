#!/usr/bin/env python3
"""Render NFL, CFB or MLB SportsEdge engine JSON as a phone-saveable PNG.

Presentation ONLY. No probability estimation, de-vigging, quote acquisition,
or synthetic matchup context. Unknown fields visibly remain MISSING.
Optional mascot PNG assets must be supplied explicitly (never silently fetched).
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1440, 1580
BG = "#09111E"
PANEL = "#111E31"
WHITE = "#F5F9FF"
SOFT = "#9DB1CB"
CYAN = "#3FE1FA"
GOLD = "#FFB953"
RED = "#FF647D"


def font(size: int, *, bold: bool = False):
    face = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for p in (Path("/usr/share/fonts/truetype/dejavu") / face, Path("/usr/local/share/fonts") / face):
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    try:
        return ImageFont.truetype(face, size)
    except OSError:
        return ImageFont.load_default()


def val(row: dict, *keys):
    for key in keys:
        v = row.get(key)
        if v is not None and v != "":
            return v
    return None


def fmt_pct(x):
    try:
        return f"{float(x) * 100:+.1f}%" if x is not None else "MISSING"
    except (ValueError, TypeError):
        return "MISSING"


def fmt_prob(x):
    try:
        return f"{float(x) * 100:.1f}%" if x is not None else "MISSING"
    except (ValueError, TypeError):
        return "MISSING"


def fmt_odds(x):
    try:
        p = int(float(x))
        return f"+{p}" if p > 0 else str(p)
    except (ValueError, TypeError):
        return "MISSING"


def text_fit(draw, x, y, raw, maximum, *, fill, face):
    t = str("MISSING" if raw is None or raw == "" else raw).replace("\n", " ").strip()
    while t and draw.textbbox((0, 0), t, font=face)[2] > maximum:
        t = t[:-2].rstrip() + "…"
    draw.text((x, y), t, fill=fill, font=face)


def as_rows(payload: dict, sport: str):
    """Show research prices, never convert a label into validation/PLAY.

    This generic graphic renderer has no independent verdict/owner-approval
    binding. Even a producer-supplied BET, ACTIONABLE, 99/100 or alleged
    approval is not evidence of market accuracy. Keep each raw row in its
    source artifact; the illustration may show it only as a diagnostic.
    """
    out = []
    if sport == "NFL" and isinstance(payload.get("games"), list):
        for game in payload["games"]:
            for market in game.get("markets") or []:
                for field, label in (("pick", "BEST"), ("lean", "LEAN")):
                    raw = market.get(field)
                    if not isinstance(raw, dict):
                        continue
                    row = dict(raw)
                    row["market"] = market.get("market")
                    row["status"] = label
                    row["matchup"] = f"{game.get('away', '?')} @ {game.get('home', '?')}"
                    row["reason"] = val(row, "lean_reason", "reason") or market.get("lean_block") or "MODEL_ESTIMATE"
                    out.append(row)
    else:
        for raw in payload.get("results") or payload.get("rows") or []:
            if not isinstance(raw, dict):
                continue
            status = str(val(raw, "scored_status", "bet_status", "status") or "").upper()
            if status not in {"ACTIONABLE", "BET", "LEAN", "CANDIDATE"}:
                continue
            row = dict(raw)
            row["status"] = "BEST" if status in {"ACTIONABLE", "BET"} else "LEAN"
            row["matchup"] = val(raw, "matchup", "game_id") or "MATCHUP MISSING"
            out.append(row)
    for row in out:
        row["price"] = val(row, "price_american", "american_odds")
        row["raw_estimate"] = val(row, "estimate_p", "model_p")
        row["raw_ev"] = val(row, "ev_per_dollar", "expected_roi")
        row["raw_edge_value"] = val(row, "edge_probability_points", "edge")
        # In a shareable PNG an untested +40% EV or 95% win chance is just
        # as deceptive as a 99/100 score. Those values remain in source JSON
        # for audit and must not be promoted by this generic visual path.
        row["est"] = None
        row["ev"] = None
        row["edge_value"] = None
        # Score B in NFL/MLB is operational qualification (PIT, quote age,
        # simulation path coverage), not calibrated forecast accuracy.
        # Neither an upstream BEST/BET label nor caller-controlled flags
        # can elevate it to a trustworthy 0-100 prediction score.
        row["raw_qualification_score"] = val(row, "score_0_100", "confidence_score")
        row["score_value"] = None
        row["score_status"] = "WITHHELD_UNVALIDATED_PREDICTION_ACCURACY"
        row["status"] = "LEAN"
        row["reason"] = "RESEARCH_NOT_VALIDATED_FOR_PLAY: " + str(row.get("reason") or "")
        if (row["price"] is None or row["raw_estimate"] is None
                or row["raw_ev"] is None or row["raw_edge_value"] is None):
            row["status"] = "LEAN"
            row["reason"] = "INCOMPLETE_DATA " + str(row.get("reason") or "")
    def num(v):
        try:
            return float(v) if v is not None else float("-inf")
        except (ValueError, TypeError):
            return float("-inf")
    out.sort(key=lambda r: (-num(r.get("ev")), -num(r.get("edge_value")),
                           str(r.get("matchup")), str(r.get("market")), str(r.get("selection") or r.get("side"))))
    return out


def symbol(draw, x, y, color):
    # Draw a small flame silhouette without relying on emoji fonts.
    draw.polygon([(x+12,y),(x+23,y+15),(x+20,y+32),(x+31,y+19),
                  (x+30,y+39),(x+18,y+51),(x+4,y+43),(x+1,y+26)],
                 fill=color)


def mascot(draw, im, left, top, team, folder):
    name = re.sub(r"[^a-zA-Z0-9_-]", "_", str(team or "")).lower()
    hit = next((folder / f"{name}{ext}" for ext in (".png", ".webp") if (folder / f"{name}{ext}").is_file()), None)
    draw.rounded_rectangle((left, top, left+116, top+100), radius=20, fill=PANEL, outline="#30475B", width=2)
    if hit:
        try:
            with Image.open(hit) as logo:
                pic = logo.convert("RGBA")
                pic.thumbnail((104, 88))
                im.paste(pic, (left + (116-pic.width)//2, top+(100-pic.height)//2), pic)
                return
        except (OSError, ValueError):
            pass
    text_fit(draw, left+12, top+18, team or "?", 95, fill=CYAN, face=font(28, bold=True))
    draw.text((left+12, top+67), "LOGO MISSING", fill=SOFT, font=font(11, bold=True))


def tile(draw, r, left, top, number, *, best):
    x1, x2, y2 = left, left+655, top+232
    accent = GOLD if best else CYAN
    draw.rounded_rectangle((x1, top, x2, y2), radius=19, fill=PANEL, outline=accent, width=2)
    if best:
        symbol(draw, left+16, top+18, GOLD)
    else:
        draw.ellipse((left+23,top+32,left+42,top+51),fill=CYAN)
    text_fit(draw,left+67,top+14, f"#{number}  {r.get('matchup') or 'MATCHUP MISSING'}",
             570,fill=accent,face=font(24,bold=True))
    selection = val(r, "selection", "side") or "SELECTION MISSING"
    player = val(r, "player", "subject_name")
    name = f"{player} · {selection}" if player else selection
    market = str(r.get("market") or "MARKET MISSING")
    text_fit(draw, left+22,top+61,
             f"{market}: {name}  {r.get('line') if r.get('line') is not None else ''}",
             475, fill=WHITE, face=font(25,bold=True))
    draw.text((left+518,top+62),fmt_odds(r.get("price")),fill=GOLD,font=font(24,bold=True))
    draw.line((left+22,top+107,left+633,top+107),fill="#2D4562",width=2)
    # Owner ruling Oct 24 2026: no 0-100 score on cards; show the model version.
    values = [("ESTIMATE","WITHHELD"),("EV","WITHHELD"),
              ("EDGE","WITHHELD"),
              ("MODEL",str(val(r,"model_version") or "—"))]
    for i,(label,value) in enumerate(values):
        x = left+25+i*156
        draw.text((x,top+118),label,fill=SOFT,font=font(13,bold=True))
        text_fit(draw,x,top+139,value,147,fill=CYAN if i in (1,2) else WHITE,face=font(21,bold=True))
    reason = str(val(r,"reason","lean_reason") or "REASON MISSING")
    text_fit(draw,left+24,top+184,reason,606,fill=SOFT,face=font(16))


def render(payload, sport, output: Path, mascots: Path):
    sport = str(sport).upper()
    if sport not in {"NFL", "CFB", "MLB"}:
        raise ValueError("SPORT_MUST_BE_NFL_CFB_OR_MLB")
    rows = as_rows(payload,sport)
    best = [r for r in rows if r["status"]=="BEST"][:4]
    leans = [r for r in rows if r["status"]=="LEAN"][:4]
    image = Image.new("RGB",(W,H),BG)
    d=ImageDraw.Draw(image)
    d.rectangle((0,0,W,11),fill=CYAN)
    d.text((45,37),"SPORTSEDGE",fill=WHITE,font=font(57,bold=True))
    d.text((48,105),f"{sport}   |   UNVALIDATED RESEARCH DIAGNOSTICS",fill=CYAN,font=font(22,bold=True))
    games = payload.get("games") if isinstance(payload.get("games"),list) else []
    matchups = sorted({str(row.get("matchup") or "") for row in rows if row.get("matchup")})
    # The first game is NOT the whole NFL slate. Its context and mascots
    # must never imply that every tile belongs to that matchup.
    multi = len(games)>1 or len(matchups)>1
    if multi:
        headline = f"{sport} MULTI-GAME SLATE"
    elif games:
        headline = f"{games[0].get('away','?')} @ {games[0].get('home','?')}"
    elif len(matchups)==1:
        headline = matchups[0]
    else:
        headline = payload.get("matchup") or f"{sport} SLATE"
    text_fit(d,48,153,headline,870,fill=WHITE,face=font(31,bold=True))
    g = games[0] if len(games)==1 else {}
    if not multi:
        away,home=g.get("away"),g.get("home")
        if not (away and home) and " @ " in headline:
            away,home=str(headline).split(" @ ",1)
        mascot(d,image,1138,26,away,mascots)
        mascot(d,image,1266,26,home,mascots)
    context = (g.get("context") if isinstance(g,dict) else {}) or payload.get("context") or {}
    info = context.get("game_info") or {}
    d.rounded_rectangle((44,218,1395,293),radius=15,fill=PANEL,outline="#284562",width=2)
    strip = [
        ("STARTERS", val(context,"starters","last_start_qb") or info.get("starters")),
        ("WEATHER",val(context,"weather") or info.get("weather")),
        ("ROOF",val(context,"roof") or info.get("roof")),
        ("LINEUPS",val(context,"lineups") or info.get("lineups")),
        ("UMPIRE",val(context,"umpire") or info.get("umpire")),
    ]
    for i,(k,v) in enumerate(strip):
        x=60+i*271
        d.text((x,229),k,fill=CYAN,font=font(14,bold=True))
        if isinstance(v,dict):
            if k=="STARTERS":
                qb_names=[str((item or {}).get("qb") or "") for item in v.values() if isinstance(item,dict)]
                v=", ".join(name for name in qb_names if name) or None
            else:
                v="RETRIEVED" if v else None
        elif isinstance(v,list):
            v=", ".join(map(str,v[:2])) if v else None
        text_fit(d,x,253,v if v is not None else "MISSING",255,fill=WHITE if v is not None else RED,face=font(16,bold=True))
    d.text((46,317),f"VERIFIED PLAYS   {len(best)}",fill=GOLD,font=font(26,bold=True))
    d.text((733,317),f"RESEARCH ROWS   {len(leans)}",fill=CYAN,font=font(26,bold=True))
    for n,r in enumerate(best):
        tile(d,r,44,365+n*249,n+1,best=True)
    for n,r in enumerate(leans):
        tile(d,r,730,365+n*249,n+1,best=False)
    if not best:
        d.text((67,421),"NO VERIFIED PLAYS",fill=SOFT,font=font(26,bold=True))
    if not leans:
        d.text((750,421),"NO RESEARCH ROWS",fill=SOFT,font=font(26,bold=True))
    d.line((44,1400,1395,1400),fill="#375A74",width=3)
    d.text((48,1418),"SOURCE: SPORTSEDGE ENGINE CARD  |  MISSING IS NOT ZERO",fill=SOFT,font=font(18,bold=True))
    d.text((48,1455),"UNVALIDATED ESTIMATES ARE NOT PICKS   |   0–100 SCORES WITHHELD",fill=SOFT,font=font(17))
    d.text((48,1491),"Research-only; no independently verified market edge or PLAY authority.",fill=SOFT,font=font(17))
    output.parent.mkdir(parents=True,exist_ok=True)
    image.save(output,format="PNG",optimize=True)
    return {"sport":sport,"best":len(best),"leans":len(leans),"output":str(output)}


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--card",type=Path,required=True)
    ap.add_argument("--sport",choices=("NFL","CFB","MLB"),required=True)
    ap.add_argument("--output",type=Path,required=True)
    ap.add_argument("--mascot-dir",type=Path,default=Path("assets/team_mascots"))
    args=ap.parse_args()
    result=render(json.loads(args.card.read_text(encoding="utf-8")),args.sport,args.output,args.mascot_dir)
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
