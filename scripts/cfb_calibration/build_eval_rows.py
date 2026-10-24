#!/usr/bin/env python3
"""t272 reproducibility: build eval_rows.json from the sha256-pinned free CFB
line archive registered in config/research/cfb_historical_market_source_v1.json
and the ESPN results file. Downloads the pinned archive if absent and refuses
any byte mismatch. Run in the same directory as fetch_espn_results.py."""
import hashlib, os, urllib.request
_URL = ("https://raw.githubusercontent.com/sportsdataverse/cfbfastR-data/"
        "f5a05dc815951b8dbe18961a824f34cf154dfa61/betting/csv/cfb_line_odds.csv.gz")
_SHA = "7ae899d9035750dccf22470d7923087a2659052aeb37a44204c35fbf6bf38d4d"
if not os.path.exists("cfb_line_odds.csv.gz"):
    urllib.request.urlretrieve(_URL, "cfb_line_odds.csv.gz")
if hashlib.sha256(open("cfb_line_odds.csv.gz", "rb").read()).hexdigest() != _SHA:
    raise SystemExit("ARCHIVE_SHA256_MISMATCH")
import csv,gzip,json,statistics as S,collections
from datetime import datetime
R=json.load(open("espn_results_2023_2025.json"))
lines=collections.defaultdict(lambda:{"sp":[],"tot":[],"ml":collections.defaultdict(dict)})
for r in csv.DictReader(gzip.open("cfb_line_odds.csv.gz","rt")):
    if r["season"] not in("2024.0","2025.0") or not r["game_id"]: continue
    g=r["game_id"]
    if g not in R: continue
    away,_,home=r["game_desc"].partition("@")
    L=lines[g]
    if r["market_type"]=="spread" and r["lines"]:
        if r["abbr"]==home: L["sp"].append(float(r["lines"]))
    elif r["market_type"]=="total" and r["lines"] and r["abbr"]=="over": L["tot"].append(float(r["lines"]))
    elif r["market_type"]=="money_line" and r["odds"]:
        L["ml"][r["book"]]["H" if r["abbr"]==home else ("A" if r["abbr"]==away else "?")]=float(r["odds"])
def imp(o): return 100/(o+100) if o>0 else -o/(-o+100)
# team histories
hist=collections.defaultdict(list)
for gid,x in R.items():
    d=x["date"]
    hist[x["home"]].append((d,x["season"],x["hs"],x["as"]))
    hist[x["away"]].append((d,x["season"],x["as"],x["hs"]))
def sample(team,season,date):
    s=sorted([h for h in hist[team] if h[1]==season and h[0]<date],reverse=True)[:5]
    return s
rows=[]
for gid,L in lines.items():
    x=R[gid]
    if not L["sp"] or not L["tot"]: continue
    sh,sa=sample(x["home"],x["season"],x["date"]),sample(x["away"],x["season"],x["date"])
    if len(sh)<3 or len(sa)<3: continue
    mlp=[]
    for b,v in L["ml"].items():
        if "H" in v and "A" in v:
            ph,pa=imp(v["H"]),imp(v["A"]); mlp.append(ph/(ph+pa))
    rows.append({"gid":gid,"season":x["season"],"neutral":x["neutral"],
      "spread_home":S.median(L["sp"]),"total":S.median(L["tot"]),"ml_home_nv":S.median(mlp) if mlp else None,
      "margin":x["hs"]-x["as"],"points":x["hs"]+x["as"],
      "h_mm":S.mean(p-a for _,_,p,a in sh),"a_mm":S.mean(p-a for _,_,p,a in sa),
      "h_mt":S.mean(p+a for _,_,p,a in sh),"a_mt":S.mean(p+a for _,_,p,a in sa),
      "h_n":len(sh),"a_n":len(sa)})
json.dump(rows,open("eval_rows.json","w"))
print(len(rows),collections.Counter(r["season"] for r in rows), sum(r["ml_home_nv"] is not None for r in rows))
