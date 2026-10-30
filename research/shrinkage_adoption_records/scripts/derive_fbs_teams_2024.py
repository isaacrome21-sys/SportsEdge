#!/usr/bin/env python3
"""Derive the 2024-season FBS team-id set for the CFB QB challenger lane.

Same method as backtest_program_20261014/scripts/derive_fbs_teams.py:
NCAA.com official FBS standings school list as the authoritative anchor,
matched against the corpus team payloads (site v2 team location) with the
same token normalization + alias table.

2024 list = the script's 2025 list (136) minus Delaware and Missouri
State, whose first FBS seasons were 2025 (both were FCS/CAA + Missouri
Valley in 2024; confirmed via web, Oct 2026). Expected count: 134.

Output: ~/workspace/tmp/bt_data/espn_cfb/fbs_2024_team_ids.json
        {"2024": {team_id: name}}
No repo writes. Transport (team info lookups) only, before scoring.
"""
from __future__ import annotations
import json, os, sys, urllib.request

DATA = os.path.expanduser("~/workspace/tmp/bt_data/espn_cfb")
CACHE = os.path.join(DATA, "team_info.json")
OUT = os.path.join(DATA, "fbs_2024_team_ids.json")
sys.path.insert(0, os.path.expanduser(
    "~/workspace/sportsedge/backtest_program_20261014/scripts"))
import derive_fbs_teams as D  # noqa: E402 (definitions only; main() not called)

EXCLUDE_2024 = {D.norm("Delaware"), D.norm("Missouri State")}


def main() -> None:
    corpus = {}
    for name in os.listdir(DATA):
        if name.startswith("scoreboard_"):
            with open(os.path.join(DATA, name)) as f:
                d = json.load(f)
            for ev in d.get("events") or []:
                comp = (ev.get("competitions") or [{}])[0]
                for c in comp.get("competitors") or []:
                    t = c.get("team") or {}
                    if t.get("id") is not None:
                        corpus[str(t["id"])] = t.get("displayName")
    print("corpus teams:", len(corpus), flush=True)
    cache = json.load(open(CACHE)) if os.path.exists(CACHE) else {}
    for tid in sorted(corpus):
        if tid in cache:
            continue
        url = ("https://site.api.espn.com/apis/site/v2/sports/football/"
               f"college-football/teams/{tid}")
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "SportsEdgeBacktest/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode())
            t = d.get("team") or {}
            cache[tid] = {"displayName": t.get("displayName"),
                          "location": t.get("location"), "name": t.get("name")}
        except Exception as exc:  # noqa: BLE001
            cache[tid] = {"error": str(exc)}
        with open(CACHE, "w") as f:
            json.dump(cache, f, indent=0)
        print("fetched team info", tid, flush=True)
    def candidates(tid):
        info = cache.get(tid) or {}
        loc = D.norm(info.get("location") or "")
        disp = D.norm(info.get("displayName") or "")
        mascot = D.norm(info.get("name") or "")
        school = disp[: len(disp) - len(mascot)].strip() if mascot else disp
        return {loc, school}
    schools = [s for s in D.NCAA_2026
               if D.norm(s) not in EXCLUDE_2024
               and s not in D.TRANSITIONAL_2026_ONLY]
    print("NCAA 2024 schools:", len(schools), flush=True)
    matched, problems = {}, []
    for school in schools:
        base = D.norm(school)
        targets = {base} | D.ALIASES.get(base, set())
        hits = [tid for tid in corpus if targets & candidates(tid)]
        if len(hits) == 1:
            matched[school] = hits[0]
        else:
            problems.append((school, hits))
    print("matched:", len(matched), flush=True)
    for school, hits in problems:
        print("  PROBLEM:", school, "->",
              [(h, cache.get(h, {}).get("displayName")) for h in hits])
    out = {"2024": {tid: corpus[tid] for tid in matched.values()}}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=0)
    print("2024 FBS ids:", len(out["2024"]), "WROTE", OUT, flush=True)

if __name__ == "__main__":
    main()
