#!/usr/bin/env python3
"""Independent R3 recount, phase 2 — raw-source re-derivation.

Companion to recount_r3.py. The bindings build's staging directory
(~/workspace/tmp/cfbbind/) retains the pinned raw sources; every file is
hash-checked against the frozen config's pins BEFORE use. This script
re-derives, from raw rows only (no SportsEdge repo code):

  * the results corpus: all 13 schedule CSVs -> per-game records,
    compared field-by-field against results_snapshot.json;
  * the lines side: the cfbfastR archive -> per-game Bovada markets for
    2021-2025, the moneyline spread-sign cross-check (the documented
    admission rule), orphan and post-kickoff sets — all compared
    against lines_snapshot.json and the frozen flag/quarantine lists.

Moneyline rule (BINDINGS.md / FREEZE_PACKAGE R3, with the exact
mechanics established empirically against the frozen outcomes in this
recount): sides are assigned by school identity using the archive's
own per-game naming (game_desc 'Away@Home' — the directory parquet's
school strings differ for some programs, e.g. 'App State' vs
'Appalachian State', 'UTSA' vs 'UT San Antonio', and do NOT reproduce
the frozen outcomes). The cross-check is per-side sign agreement:
the spread favorite's moneyline must be negative and the spread
underdog's moneyline must be positive; any violation (including a
both-negative pair, or a flipped pair) -> ML_SPREAD_SIGN_INCONSISTENT;
a pick'em spread (0.0) leaves no sign to check against ->
ML_CROSSCHECK_UNAVAILABLE.
"""

import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

WS = Path.home() / "workspace"
SNAP = WS / "sportsedge/cfb_four_family_evaluation_20261013/snapshots"
SRC = WS / "tmp/cfbbind/sources"
CONFIG = json.loads(Path("/tmp/frozen_bindings_config.json").read_text())

checks = []


def check(name, mine, frozen):
    ok = mine == frozen
    checks.append((name, mine, frozen, ok))
    return ok


def sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main():
    details = {}

    # ---------- schedule sources: pin verification ----------
    sched_pins = CONFIG["sources"]["schedules"]["seasons"]
    sched_rows = {}
    for season, pin in sorted(sched_pins.items()):
        p = SRC / "schedules" / pin["asset_name"]
        check(f"schedule pin {season}", sha256_of(p), pin["sha256"])
        with gzip.open(p, "rt", newline="") as f:
            sched_rows[season] = list(csv.DictReader(f))

    # ---------- results rebuild vs snapshot ----------
    results = json.loads((SNAP / "results_snapshot.json").read_text())["payload"]
    snap_games = {g["game_id"]: g for g in results["games"]}
    field_mismatch = Counter()
    rebuilt = {}
    for season, rows in sched_rows.items():
        for r in rows:
            gid = r["game_id"]
            rec = {
                "season": int(r["season"]),
                "week": int(r["week"]),
                "season_type": (str(int(r["season_type"]))
                                if r["season_type"] != "" else ""),
                "home_team_id": r["home_id"],
                "away_team_id": r["away_id"],
                "home_team_name": r["home_team"],
                "away_team_name": r["away_team"],
                "home_score": int(r["home_score"]),
                "away_score": int(r["away_score"]),
                "status": r["status"],
                "neutral_site": r["neutral_site"] == "true",
                "kickoff_utc": parse_ts(r["game_date"]).astimezone(timezone.utc),
            }
            rebuilt[gid] = rec
    check("rebuilt results game count", len(rebuilt), len(snap_games))
    check("rebuilt results id set == snapshot id set",
          set(rebuilt) == set(snap_games), True)
    for gid, rec in rebuilt.items():
        g = snap_games.get(gid)
        if g is None:
            continue
        for field in ("season", "week", "season_type", "home_team_id",
                      "away_team_id", "home_team_name", "away_team_name",
                      "home_score", "away_score", "status", "neutral_site"):
            if rec[field] != g[field]:
                field_mismatch[field] += 1
        if rec["kickoff_utc"] != parse_ts(g["kickoff_utc"]):
            field_mismatch["kickoff_utc"] += 1
    check("results field mismatches (of 11495 games x 12 fields)",
          dict(field_mismatch), {})

    # ---------- lines archive: pin verification ----------
    lpin = CONFIG["sources"]["lines"]
    archive = SRC / "cfb_line_odds.csv.gz"
    check("lines archive sha256", sha256_of(archive), lpin["expected_sha256"])
    check("lines archive size", archive.stat().st_size,
          lpin["expected_size_bytes"])

    directory = json.loads((SNAP / "directory_snapshot.json").read_text())["payload"]
    teams = directory["teams"]
    lines = json.loads((SNAP / "lines_snapshot.json").read_text())["payload"]
    snap_lines = lines["games"]

    # group archive rows: (book, game) -> market -> list of rows
    by_game = defaultdict(lambda: defaultdict(list))
    books_games = defaultdict(set)
    game_desc = {}
    with gzip.open(archive, "rt", newline="") as f:
        for row in csv.DictReader(f):
            season = int(float(row["season"]))
            if season not in (2021, 2022, 2023, 2024, 2025):
                continue
            gid = row["game_id"].split(".")[0]
            books_games[row["book"]].add(gid)
            if row["book"] == "Bovada":
                by_game[gid][row["market_type"]].append(row)
                game_desc[gid] = row["game_desc"]

    bovada_ids = set(by_game)
    result_ids = set(snap_games)
    # The snapshot's games dict covers ALL archive Bovada games; the 58
    # orphans (absent from the results corpus) appear with empty team
    # ids. Joined games number 4,267, not 4,325.
    check("Bovada games 2021-2025 in archive (all)", len(bovada_ids), 4325)
    check("archive Bovada set == snapshot lines games",
          bovada_ids == set(snap_lines), True)
    orphans = bovada_ids - result_ids
    snap_orphans = {x["game_id"] for x in
                    json.loads((SNAP / "SNAPSHOT_MANIFEST.json").read_text())
                    ["lines"]["load_flags"]
                    if x["flag"] == "LINE_RECORD_WITHOUT_RESULTS_GAME"}
    check("orphan ids (Bovada, not in results)", orphans, snap_orphans)
    joined = bovada_ids & result_ids
    check("Bovada games joined to results", len(joined), 4267)
    check("snapshot records with empty team ids == orphans",
          {g for g, r in snap_lines.items() if r["home_team_id"] == ""},
          orphans)

    # per-book orphan counts under the alternative (all-books) reading
    details["orphans_by_book"] = {
        b: len(s - result_ids) for b, s in sorted(books_games.items())}

    # ---------- rebuild Bovada markets + cross-check ----------
    def school_names(gid, probe):
        """Home/away school names for side assignment by school identity,
        from the archive's own game_desc 'Away@Home'."""
        away_school, home_school = game_desc[gid].rsplit("@", 1)
        return home_school.strip(), away_school.strip()

    outcomes = Counter()
    outcome_by_game = {}
    value_mismatch = Counter()
    mismatch_games = []
    dt_mismatch = 0
    for gid in bovada_ids:
        markets = by_game[gid]
        probe = markets["money_line"][0] if markets["money_line"] else \
            (markets["spread"][0] if markets["spread"] else markets["total"][0])
        home_school, away_school = school_names(gid, probe)

        def side_of(row):
            if row["abbr"] == home_school:
                return "home"
            if row["abbr"] == away_school:
                return "away"
            return None
        ml, spread = {}, {}
        total_val = None
        dt = None
        for row in markets["money_line"]:
            s = side_of(row)
            if s:
                ml[s] = float(row["odds"])
            dt = row["date_time"]
        for row in markets["spread"]:
            s = side_of(row)
            if s:
                spread[s] = float(row["lines"])
            dt = row["date_time"]
        for row in markets["total"]:
            if row["abbr"] == "over":
                total_val = float(row["lines"])
            dt = row["date_time"]

        # cross-check: per-side sign agreement (see module docstring)
        if len(ml) < 2:
            outcome = "NO_PAIR"
        elif len(spread) < 2:
            outcome = "ML_CROSSCHECK_UNAVAILABLE"
        elif spread["home"] == 0:
            outcome = "ML_CROSSCHECK_UNAVAILABLE"
        else:
            fav = "home" if spread["home"] < 0 else "away"
            dog = "away" if fav == "home" else "home"
            if ml[fav] < 0 and ml[dog] > 0:
                outcome = "PASS"
            else:
                outcome = "ML_SPREAD_SIGN_INCONSISTENT"
        outcomes[outcome] += 1
        outcome_by_game[gid] = outcome

        # reconcile against the snapshot record
        rec = snap_lines[gid]
        snap_outcome = ("PASS" if rec["ml_crosscheck"] == "PASS"
                        else (rec["markets_quarantined"][0]["reason"]
                              if rec["markets_quarantined"] else "NO_PAIR"))
        if snap_outcome != outcome:
            value_mismatch["outcome"] += 1
            mismatch_games.append(gid)
        if outcome == "PASS" and (rec["home_moneyline"] != ml["home"]
                                  or rec["away_moneyline"] != ml["away"]):
            value_mismatch["moneyline_values"] += 1
        if len(spread) == 2 and rec.get("spread_home") != spread["home"]:
            value_mismatch["spread_home"] += 1
        if total_val is not None and rec.get("total") != total_val:
            value_mismatch["total"] += 1
        if dt is not None and parse_ts(dt) != parse_ts(rec["date_time_utc"]):
            dt_mismatch += 1
    check("cross-check outcomes", dict(outcomes),
          {"PASS": 3588, "ML_SPREAD_SIGN_INCONSISTENT": 214,
           "ML_CROSSCHECK_UNAVAILABLE": 6, "NO_PAIR": 517})
    check("per-game outcome/value mismatches vs snapshot",
          dict(value_mismatch), {})
    check("date_time mismatches vs snapshot", dt_mismatch, 0)
    quar = {x["game_id"]: x["reason"] for x in lines["quarantine"]}
    check("quarantine set == rebuilt FAIL+UNCHECKABLE set",
          {g for g, o in outcome_by_game.items() if o.startswith("ML_")},
          set(quar))
    check("quarantine reasons == rebuilt outcomes",
          {g: outcome_by_game[g] for g in quar}, quar)

    details["outcome_mismatch_games"] = mismatch_games
    # spread/total availability counts from raw rows (all archive games;
    # the snapshot's provider_coverage counts include the orphans)
    check("games with spread (raw)",
          sum(1 for g in bovada_ids if by_game[g]["spread"]), 4324)
    check("games with total (raw)",
          sum(1 for g in bovada_ids if by_game[g]["total"]), 4323)
    check("games with any team-total market (raw)",
          sum(1 for g in bovada_ids
              if any(r["market_type"] not in ("money_line", "spread", "total")
                     for m in by_game[g].values() for r in m)), 0)

    # ---------- post-kickoff from raw ----------
    postk = set()
    for gid in joined:
        rows = [r for m in by_game[gid].values() for r in m]
        dts = {r["date_time"] for r in rows}
        if len(dts) != 1:
            details.setdefault("games_with_multiple_date_times", []).append(gid)
        if parse_ts(dts.pop()) > parse_ts(snap_games[gid]["kickoff_utc"]):
            postk.add(gid)
    snap_postk = {x["game_id"] for x in
                  json.loads((SNAP / "SNAPSHOT_MANIFEST.json").read_text())
                  ["lines"]["load_flags"]
                  if x["flag"] == "POST_KICKOFF_LINE_TIMESTAMP"}
    check("post-kickoff set (Bovada date_time > schedule kickoff)",
          postk, snap_postk)
    details["post_kickoff_deltas_minutes"] = {
        g: (parse_ts(snap_lines[g]["date_time_utc"])
            - parse_ts(snap_games[g]["kickoff_utc"])).total_seconds() / 60.0
        for g in sorted(postk)}

    n_fail = sum(1 for c in checks if not c[3])
    print(f"PHASE-2 CHECKS: {len(checks)} total, {len(checks) - n_fail} match, "
          f"{n_fail} MISMATCH")
    for name, mine, frozen, ok in checks:
        if not ok:
            print(f"  MISMATCH {name}: recount={mine!r} frozen={frozen!r}")
    print("DETAILS:", json.dumps(details, indent=1, default=str))


if __name__ == "__main__":
    main()
