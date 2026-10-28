#!/usr/bin/env python3
"""
MLB_GAME_DIST_V1 - Phase D FULL-FIDELITY data fetch (design section 2.2).

Pulls, for every regular-season game 2021-2026 from the official MLB
StatsAPI (public, free):
  - schedule/results (date, gamePk, teams, final score), and
  - the boxscore pitching split the full-fidelity PIT decomposition needs:
    the ACTUAL starter per team (design 2.3: "Confirmed starter = the
    pitcher who actually starts") with his outs recorded and runs allowed,
    plus team bullpen outs/runs (team pitching totals minus the starter).

Output: one compact JSON dataset (games with starter/bullpen splits) plus a
manifest (counts, sha256, sanity flags). Resumable: per-season JSONL cache;
re-running skips games already cached. Point-in-time note: this assembles
HISTORICAL facts; the model script enforces strictly-prior discipline at
feature time (a game's own boxscore is only used to update history AFTER
that game has been scored).
"""
import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SEASONS = [2021, 2022, 2023, 2024, 2025, 2026]
BASE = "https://statsapi.mlb.com/api/v1"
HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)


def ip_to_outs(ip):
    """StatsAPI inningsPitched string: '5.2' = 5 innings + 2 outs."""
    if ip is None:
        return 0
    s = str(ip)
    if "." in s:
        whole, frac = s.split(".")
        return int(whole) * 3 + int(frac)
    return int(s) * 3


def get_json(url, sess, tries=4):
    last = None
    for i in range(tries):
        try:
            r = sess.get(url, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001 - retry any transport error
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def fetch_schedule(season, sess):
    games = {}
    for month in range(3, 12):
        url = (f"{BASE}/schedule?sportId=1&gameType=R"
               f"&startDate={season}-{month:02d}-01&endDate={season}-{month:02d}-28")
        data = get_json(url, sess)
        for d in data.get("dates", []):
            for g in d.get("games", []):
                if g["status"]["abstractGameState"] != "Final":
                    continue
                ht, at = g["teams"]["home"], g["teams"]["away"]
                if ht.get("score") is None or at.get("score") is None:
                    continue
                games[g["gamePk"]] = dict(
                    pk=g["gamePk"], date=d["date"], season=season,
                    ht=ht["team"]["id"], at=at["team"]["id"],
                    hs=ht["score"], as_=at["score"])
    # end-of-month days 29-31
    url = (f"{BASE}/schedule?sportId=1&gameType=R"
           f"&startDate={season}-03-29&endDate={season}-11-30")
    data = get_json(url, sess)
    for d in data.get("dates", []):
        for g in d.get("games", []):
            if g["status"]["abstractGameState"] != "Final":
                continue
            ht, at = g["teams"]["home"], g["teams"]["away"]
            if ht.get("score") is None or at.get("score") is None:
                continue
            games.setdefault(g["gamePk"], dict(
                pk=g["gamePk"], date=d["date"], season=season,
                ht=ht["team"]["id"], at=at["team"]["id"],
                hs=ht["score"], as_=at["score"]))
    return games


def parse_boxscore(pk, sess):
    b = get_json(f"{BASE}/game/{pk}/boxscore", sess)
    out = {}
    for side in ("home", "away"):
        t = b["teams"][side]
        starter = None
        tot_outs = 0
        tot_runs = 0
        n_starters = 0
        for pid in t.get("pitchers", []):
            p = t["players"][f"ID{pid}"]
            st = p.get("stats", {}).get("pitching", {})
            outs = ip_to_outs(st.get("inningsPitched"))
            runs = int(st.get("runs", 0))
            tot_outs += outs
            tot_runs += runs
            if st.get("gamesStarted"):
                n_starters += 1
                starter = dict(pid=pid, outs=outs, runs=runs)
        out[side] = dict(starter=starter, tot_outs=tot_outs,
                         tot_runs=tot_runs, n_starters=n_starters)
    return out


def main():
    sess = requests.Session()
    all_games = {}
    flags = dict(starter_missing=0, starter_multi=0, runs_mismatch=0,
                 boxscore_missing=0)
    for season in SEASONS:
        sched = fetch_schedule(season, sess)
        cache_path = os.path.join(CACHE, f"box_{season}.jsonl")
        cached = {}
        if os.path.exists(cache_path):
            for line in open(cache_path):
                row = json.loads(line)
                cached[row["pk"]] = row
        todo = [pk for pk in sched if pk not in cached]
        print(f"season {season}: schedule {len(sched)} games, "
              f"cached {len(cached)}, to fetch {len(todo)}", flush=True)
        results = {}
        if todo:
            with ThreadPoolExecutor(max_workers=12) as ex:
                futs = {}
                for pk in todo:
                    s2 = requests.Session()
                    futs[ex.submit(parse_boxscore, pk, s2)] = pk
                done = 0
                with open(cache_path, "a") as fh:
                    for fut in as_completed(futs):
                        pk = futs[fut]
                        try:
                            results[pk] = fut.result()
                        except Exception as e:  # noqa: BLE001
                            print(f"  boxscore {pk} FAILED: {e}", flush=True)
                            results[pk] = None
                        fh.write(json.dumps(dict(pk=pk, box=results[pk])) + "\n")
                        done += 1
                        if done % 500 == 0:
                            print(f"  {season}: {done}/{len(todo)}", flush=True)
        for pk, g in sched.items():
            box = cached.get(pk, {}).get("box") if pk in cached else results.get(pk)
            if box is None:
                flags["boxscore_missing"] += 1
                continue
            row = dict(g)
            for side, tside in (("home", "h"), ("away", "a")):
                bx = box[side]
                opp_score = g["as_"] if side == "home" else g["hs"]
                if bx["starter"] is None:
                    flags["starter_missing"] += 1
                if bx["n_starters"] != 1:
                    flags["starter_multi"] += 1
                if bx["tot_runs"] != opp_score:
                    flags["runs_mismatch"] += 1
                st = bx["starter"] or dict(pid=None, outs=0, runs=0)
                row[f"{tside}_starter"] = st
                row[f"{tside}_bp_outs"] = bx["tot_outs"] - st["outs"]
                # bullpen runs anchored to the official score so team
                # totals always reconcile (pitcher 'runs' can differ from
                # the score on rare scoring rulings)
                row[f"{tside}_bp_runs"] = opp_score - st["runs"]
                row[f"{tside}_tot_outs"] = bx["tot_outs"]
            all_games[pk] = row
        print(f"season {season}: assembled {sum(1 for g in all_games.values() if g['season'] == season)}",
              flush=True)
    games = sorted(all_games.values(), key=lambda g: (g["date"], g["pk"]))
    payload = json.dumps(games, separators=(",", ":"))
    out_path = os.path.join(HERE, "pitching_dataset.json")
    with open(out_path, "w") as fh:
        fh.write(payload)
    manifest = dict(n_games=len(games),
                    seasons={s: sum(1 for g in games if g["season"] == s)
                             for s in SEASONS},
                    sha256=hashlib.sha256(payload.encode()).hexdigest(),
                    bytes=len(payload), flags=flags,
                    source="MLB StatsAPI schedule + boxscore, pulled " +
                           time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with open(os.path.join(HERE, "pitching_dataset_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    print(json.dumps(manifest, indent=1), flush=True)


if __name__ == "__main__":
    main()
