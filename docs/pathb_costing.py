#!/usr/bin/env python3
"""Path B (postseason-exclusion) costing for the CFB freeze erratum.

Reuses the recount's documented funnel (same order, same frozen inputs as
recount_r3.py): IL -> unresolved -> no-contest -> non-FBS -> population,
season-effective FBS from the frozen bindings config override table +
directory snapshot classifications, over the frozen snapshot corpus.
Computes Reading A (as counted) and Reading B (season_type == '3'
excluded) populations, matched pools, exclusion-class x postseason
intersections, and composition facts. No scoring, no evaluation.
"""
import json
from collections import Counter
from pathlib import Path

SNAP = Path("/home/hatch/workspace/sportsedge/cfb_four_family_evaluation_20261013/snapshots")
IL = {"356","77","305","2350","82","71","2287","79","2565","2197","2710","2459","2130"}

results = json.loads((SNAP / "results_snapshot.json").read_text())
lines = json.loads((SNAP / "lines_snapshot.json").read_text())
directory = json.loads((SNAP / "directory_snapshot.json").read_text())
snap_manifest = json.loads((SNAP / "SNAPSHOT_MANIFEST.json").read_text())
config = json.loads(Path("/tmp/frozen_bindings_config.json").read_text())

games = results["payload"]["games"]
teams = directory["payload"]["teams"]
lgames = lines["payload"]["games"]
overrides = {t["team_id"]: t for t in config["fbs_membership_overrides"]["teams"]}

def is_fbs(tid, season):
    ov = overrides.get(tid)
    if ov is not None:
        if season in ov.get("fcs_seasons", []):
            return False
        if season in ov.get("fbs_seasons", []):
            return True
        return ov["table_classification"].lower() == "fbs"
    return teams.get(tid, {}).get("classification", "").lower() == "fbs"

# ---- funnel (documented order) ----
popA, excl = [], {"il": [], "unres": [], "nocontest": [], "nonfbs": []}
for g in games:
    h, a = g["home_team_id"], g["away_team_id"]
    if h in IL or a in IL:
        excl["il"].append(g); continue
    if not h or not a or h not in teams or a not in teams:
        excl["unres"].append(g); continue
    if g.get("home_score") is None or g.get("away_score") is None:
        excl["nocontest"].append(g); continue
    if not (is_fbs(h, g["season"]) and is_fbs(a, g["season"])):
        excl["nonfbs"].append(g); continue
    popA.append(g)

POST = "3"
pop_post = [g for g in popA if g["season_type"] == POST]
popB = [g for g in popA if g["season_type"] != POST]
by_id = {g["game_id"]: g for g in games}
popA_ids = {g["game_id"] for g in popA}

def folds(pop):
    return {s: sum(1 for g in pop if g["season"] == s) for s in (2021,2022,2023,2024,2025)}
def burnin(pop):
    return sum(1 for g in pop if 2013 <= g["season"] <= 2020)
def matched(pop, seasons=range(2021,2026)):
    m = {"moneyline": Counter(), "spread": Counter(), "total": Counter(), "team_total": Counter()}
    anyrec = Counter()
    for g in pop:
        s = g["season"]
        if s not in seasons: continue
        rec = lgames.get(g["game_id"])
        if rec is None: continue
        anyrec[s] += 1
        if rec["ml_crosscheck"] == "PASS": m["moneyline"][s] += 1
        if rec.get("spread_home") is not None: m["spread"][s] += 1
        if rec.get("total") is not None: m["total"][s] += 1
        if rec.get("team_total_home") is not None: m["team_total"][s] += 1
    return m, anyrec

mA, anyA = matched(popA)
mB, anyB = matched(popB)
out = {}
out["popA"] = len(popA); out["popB"] = len(popB); out["pop_postseason"] = len(pop_post)
out["popA_season_type"] = dict(Counter(g["season_type"] for g in popA))
out["burninA"] = burnin(popA); out["burninB"] = burnin(popB)
out["foldsA"] = folds(popA); out["foldsB"] = folds(popB)
out["postseason_per_season_in_pop"] = {str(s): sum(1 for g in pop_post if g["season"] == s)
                                       for s in range(2013, 2026)}
out["matchedA"] = {k: dict(v) for k, v in mA.items()}
out["matchedB"] = {k: dict(v) for k, v in mB.items()}
out["matchedA_pooled"] = {k: sum(v.values()) for k, v in mA.items()}
out["matchedB_pooled"] = {k: sum(v.values()) for k, v in mB.items()}
out["anyrecA"] = dict(anyA); out["anyrecB"] = dict(anyB)
# coverage + floors under B
covB, floorB = {}, {}
for s in (2021,2022,2023,2024,2025):
    covB[s] = {fam: (mB[fam][s] / folds(popB)[s] if folds(popB)[s] else 0) for fam in mB}
out["coverageB"] = covB
out["foldmin_matched_B"] = {fam: min(mB[fam][s] for s in (2021,2022,2023,2024,2025))
                            for fam in mB}

# ---- exclusion class x postseason intersections ----
quar = lines["payload"]["quarantine"]
q_ids = [x["game_id"] for x in quar]
q_reason = {x["game_id"]: x["reason"] for x in quar}
flags = snap_manifest["lines"]["load_flags"]
orphan_ids = [x["game_id"] for x in flags if x["flag"] == "LINE_RECORD_WITHOUT_RESULTS_GAME"]
postk_ids = [x["game_id"] for x in flags if x["flag"] == "POST_KICKOFF_LINE_TIMESTAMP"]

q_in_results = [i for i in q_ids if i in by_id]
out["quarantine_total"] = len(q_ids)
out["quarantine_in_results"] = len(q_in_results)
out["quarantine_not_in_results"] = [i for i in q_ids if i not in by_id]
out["quarantine_season_type_in_results"] = dict(
    Counter(by_id[i]["season_type"] for i in q_in_results))
out["quarantine_in_popA"] = sum(1 for i in q_ids if i in popA_ids)
out["quarantine_in_popA_postseason"] = sum(
    1 for i in q_ids if i in popA_ids and by_id[i]["season_type"] == POST)
out["quarantine_in_popA_regular"] = sum(
    1 for i in q_ids if i in popA_ids and by_id[i]["season_type"] != POST)
out["quarantine_reason_x_pop_postseason"] = dict(Counter(
    q_reason[i] for i in q_ids
    if i in popA_ids and by_id[i]["season_type"] == POST))
out["quarantine_reason_x_pop_regular"] = dict(Counter(
    q_reason[i] for i in q_ids
    if i in popA_ids and by_id[i]["season_type"] != POST))
out["orphans_total"] = len(orphan_ids)
out["orphans_also_quarantined"] = [i for i in orphan_ids if i in set(q_ids)]
out["postkickoff"] = {i: {"season_type": by_id[i]["season_type"],
                          "season": by_id[i]["season"],
                          "in_popA": i in popA_ids} for i in postk_ids}
out["unresolved_games"] = {g["game_id"]: {"season_type": g["season_type"],
                                          "season": g["season"],
                                          "week": g["week"],
                                          "home": g["home_team_name"],
                                          "away": g["away_team_name"]}
                           for g in excl["unres"]}

# ---- postseason composition facts (population, folds) ----
fold_post = [g for g in pop_post if g["season"] >= 2021]
out["fold_postseason_games"] = len(fold_post)
mp, _ = matched(pop_post)
out["fold_postseason_matched_pooled"] = {k: sum(v.values()) for k, v in mp.items()}
out["neutral_postseason_pop"] = sum(1 for g in pop_post if g["neutral_site"])
out["neutral_regular_pop"] = sum(1 for g in popB if g["neutral_site"])
out["neutral_share_postseason"] = (out["neutral_postseason_pop"] / len(pop_post)) if pop_post else None
out["neutral_share_regular"] = (out["neutral_regular_pop"] / len(popB)) if popB else None
out["distinct_teams_popA"] = len({g["home_team_id"] for g in popA} | {g["away_team_id"] for g in popA})
out["distinct_teams_postseason"] = len({g["home_team_id"] for g in pop_post} | {g["away_team_id"] for g in pop_post})
# burn-in team evidence under both readings
def burn_teams(pop):
    return ({g["home_team_id"] for g in pop if g["season"] <= 2020}
            | {g["away_team_id"] for g in pop if g["season"] <= 2020})
def fold_teams(pop):
    return ({g["home_team_id"] for g in pop if g["season"] >= 2021}
            | {g["away_team_id"] for g in pop if g["season"] >= 2021})
out["burnin_distinct_teams_A"] = len(burn_teams(popA))
out["burnin_distinct_teams_B"] = len(burn_teams(popB))
out["eval_teams_no_burnin_A"] = len(fold_teams(popA) - burn_teams(popA))
out["eval_teams_no_burnin_B"] = len(fold_teams(popB) - burn_teams(popB))
out["eval_teams_no_burnin_B_names"] = sorted(
    (teams.get(t, {}).get("school") or t) for t in (fold_teams(popB) - burn_teams(popB)))
# postseason in results corpus overall (context)
out["results_total_postseason"] = sum(1 for g in games if g["season_type"] == POST)
out["results_season_type_all"] = dict(Counter(g["season_type"] for g in games))

print(json.dumps(out, indent=1, default=str))
