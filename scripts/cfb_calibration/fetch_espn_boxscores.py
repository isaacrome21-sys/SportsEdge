#!/usr/bin/env python3
"""t273 reproducibility: keyless ESPN game summaries -> per-team box stats
(plays, yards, turnovers, third-down conversions) for every game in
espn_results_2023_2025.json. Writes espn_box_2023_2025.json (cwd).
Public endpoint, no key, no credits; re-runs resume from the output file."""
import json, os, urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event={}"
OUT = "espn_box_2023_2025.json"


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def one(eid):
    try:
        req = urllib.request.Request(URL.format(eid), headers={"User-Agent": "SportsEdge-free-context/1.0"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        out = {}
        for t in d["boxscore"]["teams"]:
            s = {x["name"]: x.get("displayValue") for x in t.get("statistics", [])}
            ca = (s.get("completionAttempts") or "").replace("-", "/").split("/")
            td = (s.get("thirdDownEff") or "").split("-")
            pa, ra = _num(ca[1]) if len(ca) == 2 else None, _num(s.get("rushingAttempts"))
            out[str(t["team"]["id"])] = {
                "yards": _num(s.get("totalYards")),
                "plays": pa + ra if pa is not None and ra is not None else None,
                "to": _num(s.get("turnovers")),
                "td_conv": _num(td[0]) if len(td) == 2 else None,
                "td_att": _num(td[1]) if len(td) == 2 else None}
        return eid, out
    except Exception:
        return eid, None


def main():
    res = json.load(open("espn_results_2023_2025.json"))
    box = json.load(open(OUT)) if os.path.exists(OUT) else {}
    todo = [e for e in res if box.get(e) is None]
    with ThreadPoolExecutor(8) as ex:
        for i, (eid, out) in enumerate(ex.map(one, todo)):
            box[eid] = out
            if i % 500 == 0:
                json.dump(box, open(OUT, "w"))
    json.dump(box, open(OUT, "w"))
    print(len(box), sum(v is not None for v in box.values()))


if __name__ == "__main__":
    main()
