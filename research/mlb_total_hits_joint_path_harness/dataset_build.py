"""Dataset extraction for the MLB Total Hits joint-path harness (PREREG V1).

Source: the project's archived StatsAPI acquisition only
(~/workspace/tmp/bt_data/boxscore_cache + pbp_cache, schedules in pbp_cache).
No collectors are run; no sportsbook prices are touched.

Outputs (written to the directory given as argv[1]):
  games.jsonl        one row per archived regular-season game (2024, 2025)
                     with lineups, starters, realized hits and PBP cross-checks
  pa_rows.jsonl.gz   one row per plate appearance (batter, pitcher role,
                     mapped outcome, pitch count, game date)
  hook_rows.jsonl.gz starter hook opportunities (cumulative pitches / runs
                     allowed after each starter-faced PA, removed flag)
  baserun_rows.jsonl.gz baserunning opportunities for the three profile kinds
  extraction_report.json  counts, event-name census, integrity mismatches

Outcome mapping (StatsAPI result.event -> simulator outcome), declared in the
dataset manifest: exact hit/walk/HBP/strikeout names map directly; a strikeout
where the batter reaches first is K_REACH; 'Sac Fly*' is SAC_FLY; double/triple
play batted-ball events are GIDP; 'Catcher Interference' is K_REACH; every
remaining event resolves by the batter's own out status on the play (out ->
OUT, reached -> K_REACH, which is the simulator's generic reach bucket).
"""
from __future__ import annotations

import gzip
import json
import sys
from collections import Counter
from pathlib import Path

CACHE = Path.home() / "workspace/tmp/bt_data"
SEASONS = (2024, 2025)
HIT_OUTCOMES = {"1B", "2B", "3B", "HR"}
NON_PA_PREFIXES = ("Caught Stealing", "Pickoff", "Stolen Base", "Wild Pitch",
                   "Passed Ball", "Balk", "Game Advisory", "Runner Out")


def map_outcome(play: dict, event_census: Counter) -> str:
    res = play.get("result") or {}
    ev = res.get("event") or ""
    event_census[ev] += 1
    batter_id = (play.get("matchup") or {}).get("batter", {}).get("id")
    batter_entry = None
    for r in play.get("runners") or []:
        if (r.get("details") or {}).get("runner", {}).get("id") == batter_id:
            batter_entry = r
            break
    bmove = (batter_entry or {}).get("movement") or {}
    batter_out = bool(bmove.get("isOut"))
    batter_end = bmove.get("end")
    if ev == "Single":
        return "1B"
    if ev == "Double":
        return "2B"
    if ev == "Triple":
        return "3B"
    if ev == "Home Run":
        return "HR"
    if ev in ("Walk", "Intentional Walk", "Intent Walk"):
        return "BB"
    if ev == "Hit By Pitch":
        return "HBP"
    if ev.startswith("Strikeout"):
        return "K_REACH" if (not batter_out and batter_end == "1B") else "K"
    if "Sac Fly" in ev:
        return "SAC_FLY"
    if ev == "Grounded Into DP" or "Double Play" in ev or "Triple Play" in ev:
        return "GIDP"
    if ev == "Catcher Interference":
        return "K_REACH"
    return "OUT" if batter_out else "K_REACH"


def pitch_count(play: dict) -> int:
    n = sum(1 for e in play.get("playEvents") or [] if e.get("isPitch"))
    return max(1, n)


def scoring_runners(play: dict):
    out = []
    for r in play.get("runners") or []:
        mv = r.get("movement") or {}
        det = r.get("details") or {}
        if mv.get("end") == "score" or det.get("isScoringEvent"):
            out.append(r)
    return out


def main() -> None:
    out_dir = Path(sys.argv[1])
    out_dir.mkdir(parents=True, exist_ok=True)
    games_out = (out_dir / "games.jsonl").open("w")
    pa_out = gzip.open(out_dir / "pa_rows.jsonl.gz", "wt")
    hook_out = gzip.open(out_dir / "hook_rows.jsonl.gz", "wt")
    base_out = gzip.open(out_dir / "baserun_rows.jsonl.gz", "wt")
    census: Counter = Counter()
    report = {
        "games_seen": 0, "games_parsed": 0, "games_missing_files": [],
        "hits_mismatch": [], "pa_mismatch": [], "runs_mismatch": [],
        "pa_rows": 0, "hook_rows": 0, "baserun_rows": 0,
    }
    seen_pk: set = set()
    for season in SEASONS:
        sched = json.loads((CACHE / f"pbp_cache/schedule_{season}.json").read_text())
        for day in sched.get("dates") or []:
            for g in day.get("games") or []:
                if g.get("gameType") != "R":
                    continue
                # The cached season schedules list some games twice
                # (identical officialDate and facts). Each gamePk is one
                # game: process it once or its PAs would be double-counted
                # in every empirical profile.
                if g["gamePk"] in seen_pk:
                    continue
                seen_pk.add(g["gamePk"])
                report["games_seen"] += 1
                pk = g["gamePk"]
                date = g["officialDate"]
                box_p = CACHE / f"boxscore_cache/{pk}.json"
                pbp_p = CACHE / f"pbp_cache/pbp_{pk}.json"
                if not box_p.exists() or not pbp_p.exists():
                    report["games_missing_files"].append(pk)
                    continue
                box = json.loads(box_p.read_text())
                pbp = json.loads(pbp_p.read_text())
                facts = {"game_id": str(pk), "date": date, "season": season}
                starters, lineups = {}, {}
                ok = True
                for side in ("away", "home"):
                    tdata = box["teams"][side]
                    facts[f"{side}_team"] = tdata["team"]["abbreviation"]
                    facts[f"{side}_hits"] = tdata["teamStats"]["batting"]["hits"]
                    facts[f"{side}_pa_box"] = tdata["teamStats"]["batting"]["plateAppearances"]
                    facts[f"{side}_runs_box"] = tdata["teamStats"]["batting"]["runs"]
                    order, starter = [], None
                    for p in tdata["players"].values():
                        bo = p.get("battingOrder")
                        if bo and str(bo).endswith("00"):
                            order.append((int(bo), p["person"]["id"]))
                        pit = (p.get("stats") or {}).get("pitching") or {}
                        if pit.get("gamesStarted") == 1:
                            starter = p["person"]["id"]
                    order.sort()
                    lineups[side] = [pid for _, pid in order]
                    starters[side] = starter
                    if len(order) != 9 or starter is None:
                        ok = False
                facts["away_lineup"] = lineups["away"]
                facts["home_lineup"] = lineups["home"]
                facts["away_starter"] = starters["away"]
                facts["home_starter"] = starters["home"]
                facts["lineup_complete"] = ok
                # Non-concluding action entries (caught stealing / pickoff /
                # stolen base / wild pitch / runner out ...) sit in allPlays
                # under their own atBatIndex: the plate appearance never
                # concluded, so they are not PA rows (and not in the official
                # boxscore PA count). Excluded before mapping.
                plays = [p for p in pbp.get("allPlays") or []
                         if (p.get("result") or {}).get("type") == "atBat"
                         and not ((p.get("result") or {}).get("event") or "")
                         .startswith(NON_PA_PREFIXES)]
                pbp_hits = {"away": 0, "home": 0}
                pa_count = {"away": 0, "home": 0}
                # defensive sequences for hook opportunities
                defense_seq = {"away": [], "home": []}  # team DEFENDING
                for play in plays:
                    half = (play.get("about") or {}).get("halfInning")
                    off_side = "away" if half == "top" else "home"
                    def_side = "home" if half == "top" else "away"
                    outcome = map_outcome(play, census)
                    pitcher = (play.get("matchup") or {}).get("pitcher", {}).get("id")
                    batter = (play.get("matchup") or {}).get("batter", {}).get("id")
                    role = "STARTER" if pitcher == starters[def_side] else "BULLPEN"
                    pa_count[off_side] += 1
                    if outcome in HIT_OUTCOMES:
                        pbp_hits[off_side] += 1
                    pa_out.write(json.dumps({
                        "d": date, "g": pk, "b": batter, "r": role,
                        "o": outcome, "p": pitch_count(play),
                    }) + "\n")
                    report["pa_rows"] += 1
                    defense_seq[def_side].append((pitcher, play))
                    # baserunning opportunities
                    starts = {}
                    ends = {}
                    for r in play.get("runners") or []:
                        rid = (r.get("details") or {}).get("runner", {}).get("id")
                        mv = r.get("movement") or {}
                        det = r.get("details") or {}
                        starts[rid] = mv.get("start")
                        ends[rid] = (mv.get("end"), bool(det.get("isScoringEvent")))
                    if outcome == "1B":
                        for rid, st in starts.items():
                            if st == "2B":
                                end, scored = ends[rid]
                                base_out.write(json.dumps({
                                    "d": date, "g": pk, "k": "SINGLE_SECOND_SCORES",
                                    "s": bool(scored or end == "score")}) + "\n")
                                report["baserun_rows"] += 1
                            elif st == "1B" and "2B" not in starts.values():
                                end, scored = ends[rid]
                                base_out.write(json.dumps({
                                    "d": date, "g": pk, "k": "SINGLE_FIRST_TO_THIRD",
                                    "s": bool(scored or end in ("3B", "score"))}) + "\n")
                                report["baserun_rows"] += 1
                    elif outcome == "2B":
                        for rid, st in starts.items():
                            if st == "1B":
                                end, scored = ends[rid]
                                base_out.write(json.dumps({
                                    "d": date, "g": pk, "k": "DOUBLE_FIRST_SCORES",
                                    "s": bool(scored or end == "score")}) + "\n")
                                report["baserun_rows"] += 1
                # hook opportunities per defensive team
                for def_side, seq in defense_seq.items():
                    starter = starters[def_side]
                    cum_p = 0
                    cum_r = 0
                    pending = None
                    for pitcher, play in seq:
                        for r in scoring_runners(play):
                            rp = (r.get("details") or {}).get("responsiblePitcher") or {}
                            if rp.get("id") == starter:
                                cum_r += 1
                        if pitcher == starter:
                            cum_p += pitch_count(play)
                            if pending is not None:
                                hook_out.write(json.dumps({
                                    "d": date, "g": pk, "p": pending[0],
                                    "r": pending[1], "x": 0}) + "\n")
                                report["hook_rows"] += 1
                            pending = (cum_p, cum_r)
                        else:
                            if pending is not None:
                                hook_out.write(json.dumps({
                                    "d": date, "g": pk, "p": pending[0],
                                    "r": pending[1], "x": 1}) + "\n")
                                report["hook_rows"] += 1
                                pending = None
                facts["pbp_away_hits"] = pbp_hits["away"]
                facts["pbp_home_hits"] = pbp_hits["home"]
                facts["pa_away"] = pa_count["away"]
                facts["pa_home"] = pa_count["home"]
                if pbp_hits["away"] != facts["away_hits"] or pbp_hits["home"] != facts["home_hits"]:
                    report["hits_mismatch"].append(pk)
                if pa_count["away"] != facts["away_pa_box"] or pa_count["home"] != facts["home_pa_box"]:
                    report["pa_mismatch"].append(pk)
                if plays:
                    last = (plays[-1].get("result") or {})
                    if (last.get("awayScore") != facts["away_runs_box"]
                            or last.get("homeScore") != facts["home_runs_box"]):
                        report["runs_mismatch"].append(pk)
                games_out.write(json.dumps(facts) + "\n")
                report["games_parsed"] += 1
    games_out.close(); pa_out.close(); hook_out.close(); base_out.close()
    report["event_census"] = dict(census.most_common())
    (out_dir / "extraction_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({k: (v if not isinstance(v, list) or k == "event_census"
                           else f"{len(v)} games")
                      for k, v in report.items()}, indent=1)[:3000])


if __name__ == "__main__":
    main()
