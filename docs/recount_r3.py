#!/usr/bin/env python3
"""Independent R3 recount for CFB_FOUR_FAMILY_EVALUATION_V1 (issue #2218 M2).

Verification recount ONLY: no model scoring, no evaluation, no imports from
the SportsEdge repo (in particular NOT the bindings module and NOT the
harness module — this script re-implements the documented counting rules
from FREEZE_PACKAGE.md / BINDINGS.md over the frozen snapshot corpus).

Inputs (all frozen artifacts, read-only):
  snapshots/results_snapshot.json, lines_snapshot.json,
  directory_snapshot.json, SNAPSHOT_MANIFEST.json, DRY_RUN_MANIFEST.json
  frozen bindings config extracted from git:
    git show bfba59f3f:config/research/cfb_four_family_bindings_v1.json

Data transcribed as frozen inputs (cited, not derived by this script):
  * IL_COLLEGE_ESPN_IDS — the harness module's constant
    (sportsedge/research/cfb_four_family_evaluation_v1.py at b68114e0f,
    itself citing artifacts/free_models.py frozen on main by PR #2148).
  * PACKAGE_R2 — the R2 table as printed in FREEZE_PACKAGE.md section 4.
"""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
SNAP = HERE / "snapshots"

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


def main():
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else \
        Path("/tmp/frozen_bindings_config.json")
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
    config = json.loads(config_path.read_text())
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
    for name, mine, frozen, ok in checks:
        if not ok:
            print(f"  MISMATCH {name}: recount={mine!r} frozen={frozen!r}")
    print("DETAILS:", json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
