#!/usr/bin/env python3
"""t272 reproducibility: fetch keyless ESPN FBS final scores (2023-2025) to
espn_results_2023_2025.json in the current directory. Public scoreboard
endpoint, no key, no credits. Usage: python fetch_espn_results.py"""
import json,urllib.request,time
out={}
for season in (2023,2024,2025):
  for st,weeks in ((2,range(1,17)),(3,range(1,2))):
    for w in weeks:
      u=f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?dates={season}&seasontype={st}&week={w}&groups=80&limit=400"
      d=json.load(urllib.request.urlopen(urllib.request.Request(u,headers={"User-Agent":"SportsEdge-free-context/1.0"}),timeout=30))
      for e in d.get("events",[]):
        c=e["competitions"][0]
        if not c["status"]["type"].get("completed"): continue
        t={x["homeAway"]:x for x in c["competitors"]}
        try: out[e["id"]]={"season":season,"date":e["date"],"neutral":c.get("neutralSite",False),"home":t["home"]["team"]["id"],"away":t["away"]["team"]["id"],"hs":float(t["home"]["score"]),"as":float(t["away"]["score"])}
        except Exception: pass
      time.sleep(0.2)
  print(season,len(out))
json.dump(out,open("espn_results_2023_2025.json","w"))
