#!/usr/bin/env python3
"""
MLB_GAME_STATE_V1 screen - StatsAPI history pull (design section 5.1).

Fresh pull of the Phase D substrate (MLB StatsAPI, public, free), extended
for this construction: for every regular-season game 2021-2025 it stores the
schedule facts (date, UTC start, venue, teams, final score) plus the FULL
per-pitcher boxscore lines (appearance order; outs, runs, earned runs,
pitches) that the bullpen-availability layer needs. The Phase D pull stored
only team bullpen aggregates; availability is per-reliever state, so the
lines are pulled per pitcher here.

Output: one compact JSON dataset + a manifest (counts, sha256, flags).
Resumable: per-season JSONL cache in the output dir; re-running skips games
already cached. Point-in-time note: this assembles HISTORICAL facts; the
model enforces strictly-prior discipline at feature time (a game's own
boxscore updates history only AFTER that game is scored).
"""
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

SEASONS = [2021, 2022, 2023, 2024, 2025]
BASE = "https://statsapi.mlb.com/api/v1"


def ip_to_outs(ip):
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
                    game_date_utc=g.get("gameDate"),
                    venue_id=(g.get("venue") or {}).get("id"),
                    venue_name=(g.get("venue") or {}).get("name"),
                    ht=ht["team"]["id"], at=at["team"]["id"],
                    hs=ht["score"], as_=at["score"])
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
            games[g["gamePk"]] = dict(
                pk=g["gamePk"], date=d["date"], season=season,
                game_date_utc=g.get("gameDate"),
                venue_id=(g.get("venue") or {}).get("id"),
                venue_name=(g.get("venue") or {}).get("name"),
                ht=ht["team"]["id"], at=at["team"]["id"],
                hs=ht["score"], as_=at["score"])
    return games


def pitcher_lines(box_team):
    """Appearance-ordered per-pitcher lines for one team's boxscore side."""
    out = []
    players = box_team.get("players") or {}
    for pid in box_team.get("pitchers") or []:
        p = players.get(f"ID{pid}") or {}
        st = (p.get("stats") or {}).get("pitching") or {}
        out.append(dict(
            pid=pid,
            outs=ip_to_outs(st.get("inningsPitched")),
            runs=int(st.get("runs") or 0),
            er=int(st.get("earnedRuns") or 0),
            pitches=int(st.get("numberOfPitches") or 0)))
    return out


def fetch_game(game, sess):
    url = f"{BASE}/game/{game['pk']}/boxscore"
    data = get_json(url, sess)
    teams = data.get("teams") or {}
    h_lines = pitcher_lines(teams.get("home") or {})
    a_lines = pitcher_lines(teams.get("away") or {})
    game = dict(game)
    game["h_pitchers"] = h_lines
    game["a_pitchers"] = a_lines
    game["h_tot_outs"] = sum(p["outs"] for p in h_lines)
    game["a_tot_outs"] = sum(p["outs"] for p in a_lines)
    return game


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.getcwd(), "statsapi_pull")
    os.makedirs(out_dir, exist_ok=True)
    cache_dir = os.path.join(out_dir, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    sess = requests.Session()
    all_games = []
    flags = dict(boxscore_missing=0, starter_missing=0, runs_mismatch=0,
                 no_pitch_count=0)
    season_counts = {}
    for season in SEASONS:
        cache_path = os.path.join(cache_dir, f"games_{season}.jsonl")
        cached = {}
        if os.path.exists(cache_path):
            for line in open(cache_path):
                g = json.loads(line)
                cached[g["pk"]] = g
        sched = fetch_schedule(season, sess)
        todo = [g for pk, g in sched.items() if pk not in cached]
        print(f"season {season}: schedule {len(sched)}, cached {len(cached)}, to fetch {len(todo)}", flush=True)
        done = dict(cached)
        with open(cache_path, "a") as fh, ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(fetch_game, g, sess): g["pk"] for g in todo}
            n = 0
            for fut in as_completed(futs):
                pk = futs[fut]
                try:
                    g = fut.result()
                except Exception:  # noqa: BLE001
                    flags["boxscore_missing"] += 1
                    continue
                done[pk] = g
                fh.write(json.dumps(g) + "\n")
                fh.flush()
                n += 1
                if n % 500 == 0:
                    print(f"  season {season}: {n}/{len(todo)} fetched", flush=True)
        games = [done[pk] for pk in sorted(done)]
        season_counts[season] = len(games)
        for g in games:
            for side, lines, score_against in (
                    ("h", g["h_pitchers"], g["as_"]), ("a", g["a_pitchers"], g["hs"])):
                if not lines:
                    flags["starter_missing"] += 1
                    continue
                if sum(p["runs"] for p in lines) != score_against:
                    flags["runs_mismatch"] += 1
                if any(p["pitches"] == 0 for p in lines):
                    flags["no_pitch_count"] += 1
        all_games.extend(games)
        print(f"season {season}: done {len(games)}", flush=True)
    all_games.sort(key=lambda g: (g["date"], g["pk"]))
    payload = json.dumps(all_games, separators=(",", ":")).encode()
    dataset_path = os.path.join(out_dir, "statsapi_games_2021_2025.json")
    with open(dataset_path, "wb") as fh:
        fh.write(payload)
    manifest = dict(
        source="MLB StatsAPI schedule + boxscore (public, free)",
        pulled_at_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        seasons={str(k): v for k, v in season_counts.items()},
        n_games=len(all_games),
        dataset_file=os.path.basename(dataset_path),
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        flags=flags)
    with open(os.path.join(out_dir, "statsapi_manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    print(json.dumps(manifest, indent=1))


if __name__ == "__main__":
    main()
