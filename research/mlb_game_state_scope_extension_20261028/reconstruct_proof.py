#!/usr/bin/env python3
"""PA-level reconstruction proof for the MLB_GAME_STATE_V1 scope extension.

Reads Retrosheet annual event files (the zips pinned in
extension_manifest.json, pulled by pull_retrosheet_events.py) and proves
that the pinned bytes support, for every game 2022-2025:

  * each team's starting lineup (start records: batting slot + position)
  * every plate appearance with the batter, the pitcher of record
    (defensive-lineup state: the player at fielding position 1), and both
    players' handedness (roster .ROS bats/throws; a switch hitter,
    bats = B, is resolved to the side opposite the pitcher's throwing
    hand -- the standard convention, declared here)
  * the home-plate umpire's identity (info,umphome)

Parsing rules (each one forced by a measured discrepancy, all recorded in
SCOPE_EXTENSION_RECORD.md):

  * `play` records whose event is exactly `NP` are substitution markers,
    not plays: no plate appearance occurs (an announced pinch hitter
    replaced before a pitch). Skipping them is required for exact PA
    totals.
  * A play record completes the batter's PA unless every segment of its
    primary event is a baserunning-only play (steal, caught stealing,
    pickoff, wild pitch, passed ball, balk, defensive indifference).
    Base designators after the prefix may be digits or `H` (SBH,
    CSH(2452)); an error parenthetical may be truncated by the `/`
    modifier split (PO1(E1/TH...).

Modes:
  --audit        offline; reconstructs EVERY game in --data-dir and prints
                 the coverage summary (games, PAs, ROS resolution of every
                 batter/pitcher, batting-order slot continuity).
  --crosscheck   network; compares three sample games (one per season
                 2023/2024/2025) against MLB StatsAPI (free, no key):
                 final score from the linescore and PA totals from the
                 play-by-play feed's atBat plays.

Data bytes are never committed to the repo; --data-dir points at the
unzipped events tree produced by pull_retrosheet_events.py.
"""

import argparse
import glob
import json
import re
import sys
import urllib.request
from pathlib import Path

_BASERUNNING_SEG = re.compile(
    r"^(POCS|CS|SB|PO|PB|WP|BK|DI|OA|NP|FLE)[0-9H]*(\(.*)?$"
)


def pa_completes(event):
    """True unless every primary-event segment is baserunning-only."""
    primary = event.split(".")[0].split("/")[0]
    if not primary:
        return False
    return not all(_BASERUNNING_SEG.match(s) for s in primary.split(";"))


def count_runs(event):
    adv = event.split(".", 1)[1] if "." in event else ""
    return len(re.findall(r"[123B]-H", adv)) + (
        1 if re.match(r"^H(R)?\b", event.split(".")[0]) and "B-H" not in adv else 0
    )


def load_rosters(events_dir, year):
    ros = {}
    for fn in glob.glob(str(Path(events_dir) / str(year) / "*.ROS")):
        for line in open(fn, encoding="utf-8", errors="replace"):
            f = line.rstrip("\n").split(",")
            if len(f) >= 6:
                ros[f[0]] = {
                    "last": f[1], "first": f[2], "bats": f[3],
                    "throws": f[4], "team": f[5],
                }
    return ros


def find_game_lines(events_dir, year, game_id):
    team = game_id[:3]
    for fn in glob.glob(str(Path(events_dir) / str(year) / f"{year}{team}.EV*")):
        lines, capture = [], False
        for line in open(fn, encoding="utf-8", errors="replace"):
            line = line.rstrip("\n")
            if line.startswith("id,"):
                capture = line.split(",", 1)[1] == game_id
            if capture:
                lines.append(line)
            elif lines:
                break
        if lines:
            return lines
    raise KeyError(game_id)


def reconstruct(events_dir, year, game_id):
    ros = load_rosters(events_dir, year)
    lines = find_game_lines(events_dir, year, game_id)
    info = {}
    batting = {0: [None] * 10, 1: [None] * 10}  # slot 1..9 -> player id
    slot_of = {}
    defense = {0: {}, 1: {}}  # fielding position -> player id
    pas, runs = [], {0: 0, 1: 0}
    cur_pa = None
    for line in lines:
        f = line.split(",")
        t = f[0]
        if t == "info":
            info[f[1]] = f[2] if len(f) > 2 else ""
        elif t in ("start", "sub"):
            pid, team, slot, pos = f[1], int(f[3]), int(f[4]), int(f[5])
            if slot >= 1:
                batting[team][slot] = pid
                slot_of[(team, pid)] = slot
            for p, holder in list(defense[team].items()):
                if holder == pid:
                    del defense[team][p]
            if pos >= 1:
                defense[team][pos] = pid
        elif t == "play":
            inning, team, batter, event = int(f[1]), int(f[2]), f[3], f[6]
            if event == "NP":
                continue  # substitution marker, not a play: no PA occurs
            pitcher = defense[1 - team].get(1)
            if (
                cur_pa is None
                or cur_pa["batter"] != batter
                or cur_pa["inning"] != inning
                or cur_pa["team"] != team
            ):
                cur_pa = {
                    "inning": inning, "team": team, "batter": batter,
                    "pitcher": pitcher, "events": [],
                    "slot": slot_of.get((team, batter)),
                }
                pas.append(cur_pa)
            else:
                cur_pa["pitcher"] = pitcher
            cur_pa["events"].append(event)
            runs[team] += count_runs(event)
            if pa_completes(event):
                cur_pa = None
    out_pas = []
    for pa in pas:
        b = ros.get(pa["batter"], {})
        p = ros.get(pa["pitcher"], {}) if pa["pitcher"] else {}
        bb, pt = b.get("bats"), p.get("throws")
        if bb == "B":  # switch hitter: side opposite the pitcher's hand
            bb = "L" if pt == "R" else "R"
        out_pas.append({
            "inning": pa["inning"], "team": pa["team"], "slot": pa.get("slot"),
            "batter": pa["batter"], "batter_hand_used": bb,
            "pitcher": pa["pitcher"], "pitcher_hand": pt,
            "final_event": pa["events"][-1],
            "completed": pa_completes(pa["events"][-1]) if pa["events"] else False,
        })
    lineups = {0: [], 1: []}
    for line in lines:
        f = line.split(",")
        if f[0] == "start":
            lineups[int(f[3])].append({
                "slot": int(f[4]), "pos": int(f[5]), "player": f[1],
                "name": f[2].strip('"'),
                "bats": ros.get(f[1], {}).get("bats"),
                "throws": ros.get(f[1], {}).get("throws"),
            })
    return {
        "game_id": game_id, "date": info.get("date"),
        "vis": info.get("visteam"), "home": info.get("hometeam"),
        "umphome_id": info.get("umphome"), "lineups": lineups, "pas": out_pas,
        "pa_total": len(out_pas),
        "pa_by_team": {t: sum(1 for x in out_pas if x["team"] == t) for t in (0, 1)},
        "runs": {"vis": runs[0], "home": runs[1]},
    }


def game_ids(events_dir, year):
    ids = []
    for fn in glob.glob(str(Path(events_dir) / str(year) / "*.EV*")):
        for line in open(fn, encoding="utf-8", errors="replace"):
            if line.startswith("id,"):
                ids.append(line.strip().split(",")[1])
    return ids


def audit(events_dir, years=(2022, 2023, 2024, 2025)):
    summary = {}
    for year in years:
        ids = game_ids(events_dir, year)
        ros = load_rosters(events_dir, year)
        tot_pa = unresolved_b = unresolved_p = 0
        slot_checked = slot_viol = 0
        ump_ok = 0
        for gid in ids:
            r = reconstruct(events_dir, year, gid)
            tot_pa += r["pa_total"]
            if r["umphome_id"] and r["umphome_id"] != "(none)":
                ump_ok += 1
            for pa in r["pas"]:
                if pa["batter"] not in ros:
                    unresolved_b += 1
                if pa["pitcher"] not in ros:
                    unresolved_p += 1
            for team in (0, 1):
                seq = [x for x in r["pas"] if x["team"] == team]
                for a, b in zip(seq, seq[1:]):
                    if a["slot"] is None or b["slot"] is None:
                        continue
                    slot_checked += 1
                    expected = a["slot"] % 9 + 1
                    interrupted_repeat = b["slot"] == a["slot"] and not a["completed"]
                    if b["slot"] != expected and not interrupted_repeat:
                        slot_viol += 1
        summary[year] = {
            "games": len(ids), "plate_appearances": tot_pa,
            "unresolved_batter": unresolved_b, "unresolved_pitcher": unresolved_p,
            "slot_transitions_checked": slot_checked, "slot_violations": slot_viol,
            "umphome_present": ump_ok,
        }
        print(year, json.dumps(summary[year]))
    return summary


_TEAM_ABBR = {"ANA": "LAA", "CHA": "CWS", "LAN": "LAD", "SLN": "STL"}


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sportsedge-research/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def crosscheck(events_dir, samples=((2023, "HOU202303300"), (2024, "LAN202403280"),
                                    (2025, "ANA202504040"))):
    results = []
    for year, gid in samples:
        r = reconstruct(events_dir, year, gid)
        y, m, d = r["date"].split("/")
        sched = _get(f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&hydrate=team&date={y}-{m}-{d}")
        pk = None
        for date_block in sched["dates"]:
            for g in date_block["games"]:
                home_abbr = g["teams"]["home"]["team"]["abbreviation"]
                if home_abbr == _TEAM_ABBR.get(r["home"], r["home"]):
                    pk = g["gamePk"]
        feed = _get(f"https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live")
        ls = feed["liveData"]["linescore"]["teams"]
        atbats = [p for p in feed["liveData"]["plays"]["allPlays"]
                  if p["result"]["type"] == "atBat"]
        pa_api = {0: 0, 1: 0}
        for p in atbats:
            pa_api[0 if p["about"]["halfInning"] == "top" else 1] += 1
        row = {
            "game_id": gid, "date": r["date"], "vis": r["vis"], "home": r["home"],
            "statsapi_game_pk": pk,
            "runs_retrosheet": [r["runs"]["vis"], r["runs"]["home"]],
            "runs_statsapi": [ls["away"]["runs"], ls["home"]["runs"]],
            "pa_retrosheet": [r["pa_by_team"][0], r["pa_by_team"][1]],
            "pa_statsapi": [pa_api[0], pa_api[1]],
        }
        row["runs_match"] = row["runs_retrosheet"] == row["runs_statsapi"]
        row["pa_match"] = row["pa_retrosheet"] == row["pa_statsapi"]
        results.append(row)
        print(json.dumps(row))
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True,
                    help="unzipped events tree (one subdir per season)")
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--crosscheck", action="store_true")
    args = ap.parse_args()
    if args.audit:
        audit(args.data_dir)
    if args.crosscheck:
        crosscheck(args.data_dir)
    if not (args.audit or args.crosscheck):
        ap.error("pass --audit and/or --crosscheck")
    return 0


if __name__ == "__main__":
    sys.exit(main())
