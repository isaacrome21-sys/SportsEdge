#!/usr/bin/env python3
"""Self-contained R3 recount for CFB_FOUR_FAMILY_EVALUATION_V1 — remote
reproduction edition (issue #2218 M2; answers the PR #2258 reproduction
blocker).

This file is a mechanical merge of the two published recount scripts
(docs/recount_r3.py, phase 1: snapshot-corpus recount, 112 checks;
docs/recount_r3_raw.py, phase 2: raw-source re-derivation, 32 checks).
All check logic is verbatim from those scripts; the only changes are:

  * inputs are parameterized (--sources-dir / --snapshots-dir / --config)
    instead of local workspace paths and a /tmp config;
  * BEFORE any counting, every input file's SHA-256 (and size, where the
    frozen config pins it) is verified against the frozen pins — the
    bindings config's own pins for the raw sources, and the EXPECTED_*
    constants below for the snapshot corpus. Any mismatch aborts with a
    message naming the file (exit 2) and no counting is performed;
  * the two original summary lines are printed verbatim, followed by a
    combined TOTAL line; the exit code is 1 if any check mismatches
    (the originals printed mismatches and exited 0 — disclosed
    difference), 2 on input-verification failure, 0 on a clean pass.

Verification recount ONLY: no model scoring, no evaluation, no imports
from the SportsEdge repo.
"""

import argparse
import csv
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

CONFIG = None  # frozen bindings config dict, loaded by run()
SRC = None     # assigned by run() from --sources-dir
_P1_CHECKS = []  # phase 1 appends its check list here for the combined total

# SHA-256 of SNAPSHOT_MANIFEST.json itself, recorded from the frozen
# corpus (the manifest's contents are additionally cross-checked against
# the snapshot files by phase 1's own checks).
EXPECTED_SNAPSHOT_MANIFEST_SHA256 = \
    "3860cca7393bae68faee110a43c2753b0807a61c0025387606e58cfd11e82b99"


def _verify_inputs(sources_dir, snapshots_dir, config):
    """Hash-verify EVERY input against the frozen pins before counting."""
    failures = []

    def expect(path, want_sha, want_size=None):
        if not path.is_file():
            failures.append(f"{path}: MISSING")
            return
        got = sha256_of(path)
        if got != want_sha:
            failures.append(f"{path}: sha256 {got} != pinned {want_sha}")
        elif want_size is not None and path.stat().st_size != want_size:
            failures.append(
                f"{path}: size {path.stat().st_size} != pinned {want_size}")

    for fname, want in EXPECTED_FILE_SHA256.items():
        expect(snapshots_dir / fname, want)
    expect(snapshots_dir / "SNAPSHOT_MANIFEST.json",
           EXPECTED_SNAPSHOT_MANIFEST_SHA256)
    sched = config["sources"]["schedules"]["seasons"]
    for season, pin in sorted(sched.items()):
        expect(sources_dir / "schedules" / pin["asset_name"],
               pin["sha256"], pin["size_bytes"])
    lpin = config["sources"]["lines"]
    expect(sources_dir / "cfb_line_odds.csv.gz",
           lpin["expected_sha256"], lpin["expected_size_bytes"])
    tpin = config["sources"]["team_directory"]["identity_table"]
    expect(sources_dir / "cfb_team_info_2024.parquet",
           tpin["sha256"], tpin["size_bytes"])
    if failures:
        for f in failures:
            print(f"INPUT VERIFICATION FAILED: {f}", file=sys.stderr)
        raise SystemExit(2)
    n = len(EXPECTED_FILE_SHA256) + 1 + len(sched) + 2
    print(f"INPUT VERIFICATION: {n} files hash-verified against frozen pins")


import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

SNAP = None  # assigned by run() from --snapshots-dir

IL_COLLEGE_ESPN_IDS = {
    "356",   # Illinois
    "77",    # Northwestern
    "305",   # DePaul
    "2350",  # Loyola Chicago
    "82",    # UIC
    "71",    # Bradley
    "2287",  # Illinois State
    "79",    # Southern Illinois
    "2565",  # SIU Edwardsville
    "2197",  # Eastern Illinois
    "2710",  # Western Illinois
    "2459",  # Northern Illinois
    "2130",  # Chicago State
}

# FREEZE_PACKAGE.md section 4, R2 table, transcribed verbatim:
# (school as printed, team id, table classification, deviating seasons
#  expressed as {kind: [seasons]} where kind is the season-effective
#  classification that DIFFERS from the table)
PACKAGE_R2 = [
    ("Appalachian State", "2026", "FBS", {"FCS": [2013]}),
    ("Georgia Southern", "290", "FBS", {"FCS": [2013]}),
    ("Old Dominion", "295", "FBS", {"FCS": [2013]}),
    ("Charlotte", "2429", "FBS", {"FCS": [2013, 2014]}),
    ("Coastal Carolina", "324", "FBS", {"FCS": [2013, 2014, 2015, 2016]}),
    ("Liberty", "2335", "FBS", {"FCS": [2013, 2014, 2015, 2016, 2017]}),
    ("James Madison", "256", "FBS",
     {"FCS": [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021]}),
    ("Sam Houston", "2534", "FBS",
     {"FCS": [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022]}),
    ("Jacksonville State", "55", "FBS",
     {"FCS": [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022]}),
    ("Kennesaw State", "338", "FBS",
     {"FCS": [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023]}),
    ("Delaware", "48", "FCS", {"FBS": [2025]}),
    ("Missouri State", "2623", "FCS", {"FBS": [2025]}),
    ("Idaho", "70", "FCS", {"FBS": [2013, 2014, 2015, 2016, 2017]}),
]

EXPECTED_FILE_SHA256 = {
    "results_snapshot.json":
        "830ebe5a0262b26b8ebc62b6075a7bf70eb814c99025b1ea94ab9596ae586389",
    "lines_snapshot.json":
        "72c4476f78f7b1b82919df97a1c02f781260969f334ab5f7185c8b0e42e0c578",
    "directory_snapshot.json":
        "503d29b60e05ff73fb0997eba83b8dcd908a510415737674bb621d2e93b9a3b6",
    "DRY_RUN_MANIFEST.json":
        "d6a1e30a1cd6c4780833ccafd35cb2ace15da73ecd4b5c913f024861f4c2bb6d",
}
EXPECTED_SNAPSHOT_IDS = {
    "results_snapshot.json":
        "151774e84e45d8348c9e36c87d390d720c059023b190cf022bd16375b20d1195",
    "lines_snapshot.json":
        "9cc966b57db5d8b61fc644ceab587ab90f7d6bef576540479503ab8607a7d7b5",
    "directory_snapshot.json":
        "764a32c87688b6e56716b889f3f943150037880fbbf36c8d9a37419894d27e31",
}


def sha256_of(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def phase1():
    config = CONFIG  # frozen bindings config, loaded + hash-verified by run()
    out = {}
    checks = []

    def check(name, mine, frozen):
        ok = mine == frozen
        checks.append((name, mine, frozen, ok))
        return ok

    # ---------- A. corpus file identity ----------
    file_hashes = {}
    for fname, expected in EXPECTED_FILE_SHA256.items():
        h = sha256_of(SNAP / fname)
        file_hashes[fname] = h
        check(f"file sha256 {fname}", h, expected)
    snap_manifest = json.loads((SNAP / "SNAPSHOT_MANIFEST.json").read_text())
    for key, fname in (("results_snapshot", "results_snapshot.json"),
                       ("lines_snapshot", "lines_snapshot.json"),
                       ("directory_snapshot", "directory_snapshot.json")):
        check(f"snapshot_manifest hash {fname}",
              file_hashes[fname], snap_manifest["snapshots"][key]["file_sha256"])
        check(f"snapshot_manifest bytes {fname}",
              (SNAP / fname).stat().st_size,
              snap_manifest["snapshots"][key]["file_bytes"])

    results = json.loads((SNAP / "results_snapshot.json").read_text())
    lines = json.loads((SNAP / "lines_snapshot.json").read_text())
    directory = json.loads((SNAP / "directory_snapshot.json").read_text())
    dry = json.loads((SNAP / "DRY_RUN_MANIFEST.json").read_text())
    for doc, fname in ((results, "results_snapshot.json"),
                       (lines, "lines_snapshot.json"),
                       (directory, "directory_snapshot.json")):
        check(f"snapshot_id {fname}", doc["snapshot_id"],
              EXPECTED_SNAPSHOT_IDS[fname])

    rp, lp, dp = results["payload"], lines["payload"], directory["payload"]
    games = rp["games"]
    teams = dp["teams"]

    # ---------- B. R2 override table ----------
    cfg_teams = config["fbs_membership_overrides"]["teams"]
    check("config override table size", len(cfg_teams), 13)
    check("directory payload override size", len(dp["overrides"]), 13)
    check("config override version",
          config["fbs_membership_overrides"]["version"],
          "FBS_MEMBERSHIP_OVERRIDES_V1")
    check("config override status",
          config["fbs_membership_overrides"]["status"],
          "BINDINGS_DECLARED_NOT_OWNER_RULED")

    name_diffs, season_diffs, class_diffs, guard_fail = [], [], [], []
    cfg_by_id = {t["team_id"]: t for t in cfg_teams}
    for school, tid, table_cls, dev in PACKAGE_R2:
        t = cfg_by_id.get(tid)
        if t is None:
            name_diffs.append((school, tid, "MISSING from config"))
            continue
        if t["school"] != school:
            name_diffs.append((school, tid, f"config says {t['school']!r}"))
        if t["table_classification"].upper() != table_cls:
            class_diffs.append((school, tid, t["table_classification"]))
        want_fcs = dev.get("FCS", [])
        want_fbs = dev.get("FBS", [])
        if sorted(t.get("fcs_seasons", [])) != want_fcs or \
           sorted(t.get("fbs_seasons", [])) != want_fbs:
            season_diffs.append((school, tid,
                                 (t.get("fcs_seasons"), t.get("fbs_seasons")),
                                 (want_fcs, want_fbs)))
        # builder guard: directory classification must equal table class
        if teams.get(tid, {}).get("classification", "").lower() != \
                t["table_classification"].lower():
            guard_fail.append((school, tid,
                               teams.get(tid, {}).get("classification")))
        # directory payload copy must equal the config copy
        dpo = dp["overrides"].get(tid)
        if dpo is None or dpo["school"] != t["school"] or \
           sorted(dpo.get("fcs_seasons", [])) != sorted(t.get("fcs_seasons", [])) or \
           sorted(dpo.get("fbs_seasons", [])) != sorted(t.get("fbs_seasons", [])) or \
           dpo["table_classification"] != t["table_classification"]:
            season_diffs.append((school, tid, "directory payload copy differs"))
    out["r2_name_diffs"] = name_diffs
    out["r2_season_diffs"] = season_diffs
    out["r2_class_diffs"] = class_diffs
    out["r2_guard_failures"] = guard_fail
    check("R2 ids in config", sorted(cfg_by_id), sorted(x[1] for x in PACKAGE_R2))

    # ---------- C. R1 provider ----------
    check("R1 lines payload designated_provider", lp["designated_provider"], "Bovada")
    check("R1 config designated_provider",
          config["sources"]["lines"]["designated_provider"], "Bovada")
    check("R1 dry-run designated_provider",
          dry["market_data_descriptive_only"]["designated_provider"], "Bovada")
    check("R1 status string", config["sources"]["lines"]
          ["designated_provider_status"], "BINDINGS_DEFAULT_NOT_OWNER_RULED")

    # ---------- D. results corpus ----------
    check("results total games", len(games), 11495)
    check("results payload game_count", rp["game_count"], 11495)
    ids = [g["game_id"] for g in games]
    check("results duplicate game ids", len(ids) - len(set(ids)), 0)
    per_season = Counter(g["season"] for g in games)
    out["per_season_rows"] = {str(k): per_season[k] for k in sorted(per_season)}
    for s, rec in snap_manifest["results"]["per_season"].items():
        check(f"results rows season {s}", per_season[int(s)], rec["rows"])
    undecided = [g for g in games
                 if g.get("home_score") is None or g.get("away_score") is None]
    check("results undecided games (null scores)", len(undecided), 0)
    out["season_type_all"] = dict(Counter(g["season_type"] for g in games))

    result_team_ids = set()
    for g in games:
        result_team_ids.add(g["home_team_id"])
        result_team_ids.add(g["away_team_id"])
    unresolved = sorted(result_team_ids - set(teams))
    frozen_unres = sorted(snap_manifest["results"]["unresolved_team_ids"])
    # Frozen record lists 8 "unresolved" ids. Decompose it: ids absent from
    # the directory vs ids present but with empty classification (the
    # all-star entities). Only the absent ones can produce
    # BLOCK_TEAMS_UNRESOLVED games; the present-but-unclassified ones exit
    # the funnel as non-FBS. Both readings must give identical game counts.
    present_unclassified = sorted(
        i for i in frozen_unres
        if i in teams and teams[i].get("classification", "") == "")
    out["frozen_unresolved_id_list"] = frozen_unres
    out["unresolved_absent_from_directory"] = unresolved
    out["unresolved_present_unclassified_allstar"] = present_unclassified
    out["unresolved_decomposition"] = (
        f"{len(unresolved)} absent + {len(present_unclassified)} "
        f"present-unclassified = {len(frozen_unres)} frozen-listed")
    check("unresolved decomposition covers frozen list",
          sorted(unresolved + present_unclassified), frozen_unres)
    out["games_touching_present_unclassified_allstar_ids"] = len(
        {g["game_id"] for g in games
         if g["home_team_id"] in present_unclassified
         or g["away_team_id"] in present_unclassified})
    unresolved_games = [g for g in games
                        if g["home_team_id"] in unresolved
                        or g["away_team_id"] in unresolved]
    out["games_touching_unresolved_ids"] = len(unresolved_games)

    # ---------- E. season-effective FBS, recomputed ----------
    overrides = {t["team_id"]: t for t in cfg_teams}

    def is_fbs(team_id, season):
        ov = overrides.get(team_id)
        if ov is not None:
            if season in ov.get("fcs_seasons", []):
                return False
            if season in ov.get("fbs_seasons", []):
                return True
            return ov["table_classification"].lower() == "fbs"
        return teams.get(team_id, {}).get("classification", "").lower() == "fbs"

    out["directory_classification_values"] = dict(
        Counter(t.get("classification", "") for t in teams.values()))
    check("directory team count", len(teams), 1840)
    flag_disagree = 0
    for g in games:
        if is_fbs(g["home_team_id"], g["season"]) != g["home_fbs"]:
            flag_disagree += 1
        if is_fbs(g["away_team_id"], g["season"]) != g["away_fbs"]:
            flag_disagree += 1
    check("stored *_fbs flag disagreements (of 22990)", flag_disagree, 0)

    # ---------- F. population funnel, documented order ----------
    # order per FREEZE_PACKAGE 3.4 + harness classifier:
    # IL -> unresolved -> no-contest -> non-FBS -> population
    n_il = n_unres = n_nocontest = n_nonfbs = 0
    population = []
    for g in games:
        if g["home_team_id"] in IL_COLLEGE_ESPN_IDS or \
           g["away_team_id"] in IL_COLLEGE_ESPN_IDS:
            n_il += 1
            continue
        if not g["home_team_id"] or not g["away_team_id"] or \
           g["home_team_id"] not in teams or g["away_team_id"] not in teams:
            n_unres += 1
            continue
        if g.get("home_score") is None or g.get("away_score") is None:
            n_nocontest += 1
            continue
        if not (is_fbs(g["home_team_id"], g["season"])
                and is_fbs(g["away_team_id"], g["season"])):
            n_nonfbs += 1
            continue
        population.append(g)
    check("excluded Illinois fixtures", n_il, 511)
    check("excluded unresolved", n_unres, 2)
    check("excluded no-contest", n_nocontest, 0)
    check("excluded non-FBS opponent", n_nonfbs, 1446)
    check("POPULATION", len(population), 9536)
    check("funnel arithmetic", len(games) - n_il - n_unres - n_nocontest
          - n_nonfbs, 9536)
    burn_in = [g for g in population if 2013 <= g["season"] <= 2020]
    check("burn-in population 2013-2020", len(burn_in), 5754)
    check("burn-in distinct teams",
          len({g["home_team_id"] for g in burn_in}
              | {g["away_team_id"] for g in burn_in}), 128)
    fold_pop = {}
    for s in (2021, 2022, 2023, 2024, 2025):
        fold_pop[s] = sum(1 for g in population if g["season"] == s)
        check(f"fold population {s}", fold_pop[s],
              dry["folds"][str(s)]["population_games"])
    check("pooled fold population", sum(fold_pop.values()), 3782)
    out["population_season_type"] = dict(
        Counter(g["season_type"] for g in population))
    out["population_postseason_games"] = sum(
        1 for g in population if g["season_type"] != "2")
    # READING B: FREEZE_PACKAGE 3.4 describes the population as regular-
    # season only ("Postseason games ... are a separate population and
    # are never pooled"), but the classifier applies no season-type
    # filter. Report the regular-season-only population alongside.
    pop_b = [g for g in population if g["season_type"] in ("2", "")]
    out["readingB_regular_season_only_population"] = len(pop_b)
    out["readingB_burn_in"] = sum(1 for g in pop_b if g["season"] <= 2020)
    out["readingB_folds"] = {str(s): sum(1 for g in pop_b if g["season"] == s)
                             for s in (2021, 2022, 2023, 2024, 2025)}
    fold_teams = ({g["home_team_id"] for g in population if g["season"] >= 2021}
                  | {g["away_team_id"] for g in population if g["season"] >= 2021})
    check("evaluation distinct teams", len(fold_teams),
          dry["population"]["evaluation_distinct_teams"])
    burn_teams = ({g["home_team_id"] for g in burn_in}
                  | {g["away_team_id"] for g in burn_in})
    check("evaluation teams without burn-in evidence",
          len(fold_teams - burn_teams),
          dry["population"]["evaluation_teams_without_burn_in_evidence"])

    # overlap diagnostics (independent of funnel order)
    def is_il(g):
        return g["home_team_id"] in IL_COLLEGE_ESPN_IDS or \
            g["away_team_id"] in IL_COLLEGE_ESPN_IDS

    def is_unres(g):
        return g["home_team_id"] not in teams or g["away_team_id"] not in teams

    def is_nonfbs(g):
        return not (is_fbs(g["home_team_id"], g["season"])
                    and is_fbs(g["away_team_id"], g["season"]))
    out["overlap_il_and_nonfbs"] = sum(1 for g in games if is_il(g) and is_nonfbs(g))
    out["overlap_il_and_unresolved"] = sum(1 for g in games if is_il(g) and is_unres(g))
    out["overlap_unresolved_and_nonfbs"] = sum(
        1 for g in games if is_unres(g) and is_nonfbs(g))

    # ---------- G. lines side ----------
    lgames = lp["games"]
    check("lines games (Bovada)", len(lgames), 4325)
    check("lines payload game_count", lp["game_count"], 4325)
    check("lines providers present",
          sorted({g["provider"] for g in lgames.values()}), ["Bovada"])
    ml_pass = [g for g in lgames.values() if g["ml_crosscheck"] == "PASS"]
    ml_na = [g for g in lgames.values() if g["ml_crosscheck"] != "PASS"]
    check("Bovada moneyline_ok (crosscheck PASS)", len(ml_pass), 3588)
    quar_in_dict = [g for g in ml_na if g.get("markets_quarantined")]
    check("Bovada records with ML quarantined", len(quar_in_dict), 220)
    check("Bovada records with no ML pair at all",
          len(ml_na) - len(quar_in_dict), 517)
    check("Bovada spread_ok",
          sum(1 for g in lgames.values() if g.get("spread_home") is not None), 4324)
    check("Bovada total_ok",
          sum(1 for g in lgames.values() if g.get("total") is not None), 4323)
    check("Bovada team-total lines present",
          sum(1 for g in lgames.values() if g.get("team_total_home") is not None), 0)

    q = lp["quarantine"]
    check("quarantine list size", len(q), 220)
    check("quarantine reasons", dict(Counter(x["reason"] for x in q)),
          {"ML_SPREAD_SIGN_INCONSISTENT": 214, "ML_CROSSCHECK_UNAVAILABLE": 6})
    check("quarantine providers", dict(Counter(x["provider"] for x in q)),
          {"Bovada": 220})
    q_mismatch = 0
    for x in q:
        g = lgames.get(x["game_id"])
        if g is None or not any(m.get("market") == x["market"]
                                and m.get("reason") == x["reason"]
                                for m in g.get("markets_quarantined", [])):
            q_mismatch += 1
    check("quarantine entries inconsistent with game records", q_mismatch, 0)

    # provider_coverage cross-check vs FREEZE_PACKAGE R1 table
    r1_table = {
        "Bovada": (4325, 3588, 220, 4324, 4323),
        "ESPN Bet": (3541, 1524, 68, 3529, 3532),
        "William Hill (New Jersey)": (3105, 0, 0, 3105, 3103),
        "DraftKings": (2379, 2128, 122, 2370, 2259),
    }
    for prov, (gm, ok, quar, sp, tot) in r1_table.items():
        cov = lp["provider_coverage"][prov]
        check(f"R1 coverage {prov}",
              (cov["games_with_any_market"], cov["moneyline_ok"],
               cov["moneyline_quarantined"], cov["spread_ok"], cov["total_ok"]),
              (gm, ok, quar, sp, tot))

    # load flags: two manifests must agree; verify dispositions
    flags_snap = Counter(x["flag"] for x in snap_manifest["lines"]["load_flags"])
    flags_dry = Counter(x["flag"] for x in dry["market_data_descriptive_only"]
                        ["load_flags"])
    check("load flags SNAPSHOT_MANIFEST", dict(flags_snap),
          {"LINE_RECORD_WITHOUT_RESULTS_GAME": 58,
           "POST_KICKOFF_LINE_TIMESTAMP": 3})
    check("load flags DRY_RUN_MANIFEST", dict(flags_dry), dict(flags_snap))
    result_ids = set(ids)
    orphan_ids = [x["game_id"] for x in snap_manifest["lines"]["load_flags"]
                  if x["flag"] == "LINE_RECORD_WITHOUT_RESULTS_GAME"]
    postk_ids = [x["game_id"] for x in snap_manifest["lines"]["load_flags"]
                 if x["flag"] == "POST_KICKOFF_LINE_TIMESTAMP"]
    check("orphan ids actually absent from results",
          sum(1 for i in orphan_ids if i not in result_ids), 58)
    check("post-kickoff ids present in results",
          sum(1 for i in postk_ids if i in result_ids), 3)
    # Observation, not a pass/fail: the 3 flagged records ARE retained in
    # the snapshot file's games dict (the flag lives in the manifests);
    # all 3 games are FBS-vs-FCS, i.e. non-population, so no population
    # or matched count turns on their disposition. Record the facts.
    from datetime import datetime

    def _ts(s):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    kick = {g["game_id"]: g for g in games}
    pk_detail = {}
    for i in postk_ids:
        rec = lgames.get(i)
        delta_min = None
        if rec is not None:
            delta_min = (_ts(rec["date_time_utc"])
                         - _ts(kick[i]["kickoff_utc"])).total_seconds() / 60.0
        pk_detail[i] = {
            "in_lines_snapshot": rec is not None,
            "archive_minus_schedule_kickoff_minutes": delta_min,
            "population_game": kick[i]["home_fbs"] and kick[i]["away_fbs"],
        }
    out["post_kickoff_detail"] = pk_detail
    out["post_kickoff_ids"] = postk_ids
    out["post_kickoff_results_kickoffs"] = {
        i: kick[i]["kickoff_utc"] for i in postk_ids}

    # matched recount over my population
    pop_by_season = Counter()
    matched = {"moneyline": Counter(), "spread": Counter(),
               "total": Counter(), "team_total": Counter()}
    any_rec = Counter()
    for g in population:
        s = g["season"]
        if s < 2021:
            continue
        pop_by_season[s] += 1
        rec = lgames.get(g["game_id"])
        if rec is None:
            continue
        any_rec[s] += 1
        if rec["ml_crosscheck"] == "PASS":
            matched["moneyline"][s] += 1
        if rec.get("spread_home") is not None:
            matched["spread"][s] += 1
        if rec.get("total") is not None:
            matched["total"][s] += 1
        if rec.get("team_total_home") is not None:
            matched["team_total"][s] += 1
    for s in (2021, 2022, 2023, 2024, 2025):
        check(f"fold {s} with any lines record", any_rec[s],
              dry["folds"][str(s)]["with_any_lines_record"])
        fam = dry["folds"][str(s)]["families"]
        for fam_name, key in (("moneyline", "moneyline"), ("spread", "spread"),
                              ("total", "total"), ("team_total", "team_total")):
            want = fam[fam_name]["matched_games"] if "matched_games" in fam[fam_name] \
                else fam[fam_name]
            check(f"fold {s} matched {fam_name}", matched[key][s], want)
    for fam_name in ("moneyline", "spread", "total", "team_total"):
        check(f"pooled matched {fam_name}", sum(matched[fam_name].values()),
              dry["pooled"][fam_name]["matched_games"])
    out["matched_by_fold"] = {k: dict(v) for k, v in matched.items()}
    # Reading B matched counts (regular-season-only population).
    matched_b = Counter()
    for g in population:
        if g["season"] < 2021 or g["season_type"] not in ("2", ""):
            continue
        rec = lgames.get(g["game_id"])
        if rec is None:
            continue
        if rec["ml_crosscheck"] == "PASS":
            matched_b["moneyline"] += 1
        if rec.get("spread_home") is not None:
            matched_b["spread"] += 1
        if rec.get("total") is not None:
            matched_b["total"] += 1
    out["readingB_pooled_matched"] = dict(matched_b)

    # ---------- H. PIT / timestamp disclosures ----------
    out["results_per_record_timestamps"] = rp["per_record_timestamps"]
    out["lines_limitation"] = lp["limitation"]
    out["lines_source_limitations"] = lp["source"]["limitations"]
    out["results_payload_source"] = rp["source"]["contract"]
    check("dry-run run_state", dry["run_state"], "NOT_RUN")
    check("dry-run probabilities_computed", dry["probabilities_computed"], False)
    check("dry-run attempts_consumed", dry["attempts_consumed"], 0)
    check("dry-run freeze_sha", dry["freeze_sha"], None)

    # ---------- summary ----------
    n_fail = sum(1 for c in checks if not c[3])
    print(f"CHECKS: {len(checks)} total, {len(checks) - n_fail} match, "
          f"{n_fail} MISMATCH")
    _P1_CHECKS.extend(checks)
    for name, mine, frozen, ok in checks:
        if not ok:
            print(f"  MISMATCH {name}: recount={mine!r} frozen={frozen!r}")
    print("DETAILS:", json.dumps(out, indent=1, default=str))



import csv
import gzip
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SRC = None  # assigned by run() from --sources-dir
# SNAP and CONFIG are the shared driver-set globals declared above.

checks2 = []


def check2(name, mine, frozen):
    ok = mine == frozen
    checks2.append((name, mine, frozen, ok))
    return ok


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def phase2():
    details = {}

    # ---------- schedule sources: pin verification ----------
    sched_pins = CONFIG["sources"]["schedules"]["seasons"]
    sched_rows = {}
    for season, pin in sorted(sched_pins.items()):
        p = SRC / "schedules" / pin["asset_name"]
        check2(f"schedule pin {season}", sha256_of(p), pin["sha256"])
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
    check2("rebuilt results game count", len(rebuilt), len(snap_games))
    check2("rebuilt results id set == snapshot id set",
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
    check2("results field mismatches (of 11495 games x 12 fields)",
          dict(field_mismatch), {})

    # ---------- lines archive: pin verification ----------
    lpin = CONFIG["sources"]["lines"]
    archive = SRC / "cfb_line_odds.csv.gz"
    check2("lines archive sha256", sha256_of(archive), lpin["expected_sha256"])
    check2("lines archive size", archive.stat().st_size,
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
    check2("Bovada games 2021-2025 in archive (all)", len(bovada_ids), 4325)
    check2("archive Bovada set == snapshot lines games",
          bovada_ids == set(snap_lines), True)
    orphans = bovada_ids - result_ids
    snap_orphans = {x["game_id"] for x in
                    json.loads((SNAP / "SNAPSHOT_MANIFEST.json").read_text())
                    ["lines"]["load_flags"]
                    if x["flag"] == "LINE_RECORD_WITHOUT_RESULTS_GAME"}
    check2("orphan ids (Bovada, not in results)", orphans, snap_orphans)
    joined = bovada_ids & result_ids
    check2("Bovada games joined to results", len(joined), 4267)
    check2("snapshot records with empty team ids == orphans",
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
    check2("cross-check outcomes", dict(outcomes),
          {"PASS": 3588, "ML_SPREAD_SIGN_INCONSISTENT": 214,
           "ML_CROSSCHECK_UNAVAILABLE": 6, "NO_PAIR": 517})
    check2("per-game outcome/value mismatches vs snapshot",
          dict(value_mismatch), {})
    check2("date_time mismatches vs snapshot", dt_mismatch, 0)
    quar = {x["game_id"]: x["reason"] for x in lines["quarantine"]}
    check2("quarantine set == rebuilt FAIL+UNCHECKABLE set",
          {g for g, o in outcome_by_game.items() if o.startswith("ML_")},
          set(quar))
    check2("quarantine reasons == rebuilt outcomes",
          {g: outcome_by_game[g] for g in quar}, quar)

    details["outcome_mismatch_games"] = mismatch_games
    # spread/total availability counts from raw rows (all archive games;
    # the snapshot's provider_coverage counts include the orphans)
    check2("games with spread (raw)",
          sum(1 for g in bovada_ids if by_game[g]["spread"]), 4324)
    check2("games with total (raw)",
          sum(1 for g in bovada_ids if by_game[g]["total"]), 4323)
    check2("games with any team-total market (raw)",
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
    check2("post-kickoff set (Bovada date_time > schedule kickoff)",
          postk, snap_postk)
    details["post_kickoff_deltas_minutes"] = {
        g: (parse_ts(snap_lines[g]["date_time_utc"])
            - parse_ts(snap_games[g]["kickoff_utc"])).total_seconds() / 60.0
        for g in sorted(postk)}

    n_fail = sum(1 for c in checks2 if not c[3])
    print(f"PHASE-2 CHECKS: {len(checks2)} total, {len(checks2) - n_fail} match, "
          f"{n_fail} MISMATCH")
    for name, mine, frozen, ok in checks2:
        if not ok:
            print(f"  MISMATCH {name}: recount={mine!r} frozen={frozen!r}")
    print("DETAILS:", json.dumps(details, indent=1, default=str))



def run():
    global CONFIG, SRC, SNAP
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sources-dir", required=True,
                    help="staging layout: schedules/*.csv.gz, "
                         "cfb_line_odds.csv.gz, cfb_team_info_2024.parquet")
    ap.add_argument("--snapshots-dir", required=True,
                    help="the five frozen snapshot/manifest JSON files")
    ap.add_argument("--config", required=True,
                    help="frozen bindings config "
                         "(config/research/cfb_four_family_bindings_v1.json "
                         "from the candidate tree)")
    args = ap.parse_args()
    sources_dir = Path(args.sources_dir)
    snapshots_dir = Path(args.snapshots_dir)
    config_bytes = Path(args.config).read_bytes()
    CONFIG = json.loads(config_bytes)
    SRC = sources_dir
    SNAP = snapshots_dir
    print(f"CONFIG: {args.config} sha256="
          f"{hashlib.sha256(config_bytes).hexdigest()}")
    _verify_inputs(sources_dir, snapshots_dir, CONFIG)
    phase1()
    phase2()
    all_checks = _P1_CHECKS + checks2
    n_fail = sum(1 for c in all_checks if not c[3])
    print(f"TOTAL CHECKS: {len(all_checks)} total, "
          f"{len(all_checks) - n_fail} match, {n_fail} MISMATCH")
    raise SystemExit(1 if n_fail else 0)


if __name__ == "__main__":
    run()
