#!/usr/bin/env python3
"""CFB QB passing CHALLENGER evaluation — PREREG_CFB_QB (model-fix lane).

Challenger: two-component mixture distribution — each path drawn from
the production builder's path sample with prob gamma=0.25 and from the
Phase 2 B2 team-attempt chain with prob 0.75. Implemented at the CDF
level (the exact pooled-mixture distribution: F_chal = 0.25*F_frozen
+ 0.75*F_B2 over integer yards 0..800, the Phase 2 CRPS convention);
no extra RNG is introduced. gamma=0.25 is the ONLY value scored.

Test split: 2024 season fixtures (Aug-Dec 2024). Priors may reach
into 2022-2023 runway + 2024 (ESPN summaries, the Phase 2 assembly
actually used). Arms on identical fixtures: FROZEN (production
builder), CHALLENGER, B1 (QB trailing empirical), B2 (team chain).
Bootstrap: ISO-week block, 2,000 resamples, NEW seed 20261015.
Gates before scoring: Collins reproduction; 10-fixture 2024 assembly
audit vs ESPN athlete gamelogs (>=9/10); leakage tripwire (>=10).
No repo writes; production builder untouched.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.expanduser("~/workspace/tmpgit/sportsedge-ci"))

import numpy as np  # noqa: E402

from artifacts.free_models import IL_COLLEGE_NAMES, PublicContext  # noqa: E402
from sportsedge.prepricing.qb_identity_evidence import (  # noqa: E402
    STATUS_SATISFIED,
)
from sportsedge.research.cfb_qb_passing_distribution import (  # noqa: E402
    QBDistributionError,
    build_qb_passing_distribution,
)

DATA = os.path.expanduser("~/workspace/tmp/bt_data/espn_cfb")
OUT_PATH = os.environ.get("CHAL_OUT", os.path.expanduser(
    "~/workspace/sportsedge/model_fix_20261014/results/"
    "challenger_cfb_qb_results.json"))
PREREG = os.path.expanduser(
    "~/workspace/sportsedge/model_fix_20261014/specs/PREREG_CFB_QB.md")
SEED = 20261014          # builder + B2 seed policy (Phase 2, production)
BOOT_SEED = 20261015     # preregistered NEW bootstrap seed
PATHS = 20000
GAMMA = 0.25
AVAILABILITY = "AVAILABILITY_UNVERIFIED_NO_TEAM_INJURY_REPORT"
THRESHOLDS = list(range(0, 801))
LADDER = (150, 200, 250, 300)


def parse_catt(value):
    try:
        comp, att = str(value).split("/")
        return int(comp), int(att)
    except Exception:  # noqa: BLE001
        return None


def load_games():
    """Assemble per-event records from cached ESPN summaries (Phase 2)."""
    games = {}
    missing = 0
    for name in os.listdir(DATA):
        if not name.endswith(".json") or name in (
                "fbs_teams.json", "ACQUISITION_DONE.json",
                "fbs_team_ids.json", "fbs_2024_team_ids.json",
                "corpus_teams.json", "team_info.json", "team_groups.json"):
            continue
        if name.startswith("scoreboard_"):
            continue
        with open(os.path.join(DATA, name)) as f:
            d = json.load(f)
        event_id = name[:-5]
        if event_id.startswith("summary_"):
            event_id = event_id[len("summary_"):]
        comp = ((d.get("header") or {}).get("competitions") or [None])[0]
        if comp is None:
            missing += 1
            continue
        kickoff = comp.get("date")
        competitors = {}
        for c in comp.get("competitors") or []:
            team = c.get("team") or {}
            competitors[c.get("homeAway")] = {
                "team_id": str(team.get("id")), "name": team.get("displayName")}
        bs = d.get("boxscore") or {}
        team_stats = {}
        for t in bs.get("teams") or []:
            tid = str((t.get("team") or {}).get("id"))
            stats = {s.get("name"): s.get("displayValue")
                     for s in t.get("statistics") or []}
            ca = parse_catt(stats.get("completionAttempts") or "")
            if ca is None:
                continue
            team_stats[tid] = {
                "pass_att": ca[1],
                "rush_att": int(stats.get("rushingAttempts") or 0),
                "pass_yards": int(stats.get("netPassingYards") or 0),
            }
        passers = defaultdict(list)
        for tp in bs.get("players") or []:
            tid = str((tp.get("team") or {}).get("id"))
            for cat in tp.get("statistics") or []:
                if cat.get("name") != "passing":
                    continue
                labels = cat.get("labels") or []
                for a in cat.get("athletes") or []:
                    ath = a.get("athlete") or {}
                    aid = int(ath.get("id") or 0)
                    if aid <= 0:
                        continue
                    stats = a.get("stats") or []
                    row = dict(zip(labels, stats))
                    ca = parse_catt(row.get("C/ATT") or "")
                    if ca is None:
                        continue
                    passers[tid].append({
                        "athlete_id": aid, "name": ath.get("displayName"),
                        "comp": ca[0], "att": ca[1],
                        "yards": int(row.get("YDS") or 0)})
        if len(competitors) < 2 or not team_stats:
            missing += 1
            continue
        games[event_id] = {"event_id": event_id, "kickoff": kickoff,
                           "competitors": competitors,
                           "team_stats": team_stats, "passers": dict(passers)}
    return games, missing


def kick_dt(game):
    return datetime.fromisoformat(game["kickoff"].replace("Z", "+00:00"))


def crps_from_cdf(cdf, y):
    tot = 0.0
    top = max(len(cdf) - 1, y)
    for k in range(0, top):
        f = cdf[k] if k < len(cdf) else 1.0
        tot += (f - (1.0 if y <= k else 0.0)) ** 2
    return tot


def crps_from_samples(samples, y):
    s = np.sort(np.asarray(samples, dtype=float))
    n = len(s)
    term1 = float(np.mean(np.abs(s - y)))
    idx = np.arange(1, n + 1)
    pair = float(np.sum((2 * idx - n - 1) * s)) * 2.0 / (n * n)
    return term1 - 0.5 * pair


def bootstrap_ci(rows, key_a, key_b):
    weeks = defaultdict(list)
    for r in rows:
        weeks[r["week"]].append(r)
    keys = sorted(weeks)
    rng = random.Random(BOOT_SEED)
    diffs = []
    for _ in range(2000):
        sample = []
        for _ in range(len(keys)):
            sample.extend(weeks[rng.choice(keys)])
        diffs.append(sum(r[key_a] - r[key_b] for r in sample) / len(sample))
    diffs.sort()
    return [diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]]


def pit_hist(rows, key):
    hist = [0] * 10
    for r in rows:
        b = min(9, int(r[key] * 10))
        hist[b] += 1
    return hist


def main() -> None:
    prereg_sha = hashlib.sha256(open(PREREG, "rb").read()).hexdigest()

    # ---------- Collins reproduction gate (Phase 2 §6 verbatim) ----------
    ev_path = os.path.expanduser(
        "~/workspace/sportsedge/cfb_qb_passing_20261014/evidence/"
        "collins_prior_game_records.json")
    with open(ev_path) as f:
        collins_records = json.load(f)
    identity = {
        "status": STATUS_SATISFIED, "team_id": "338",
        "event_id": "401871054", "resolved_athlete_id": 4870645,
        "resolved_athlete_name": "Rickie Collins",
        "availability_status": AVAILABILITY,
        "kickoff_utc": "2026-10-14T23:30:00Z",
        "home_team_name": "Missouri State Bears",
        "away_team_name": "Kennesaw State Owls",
    }
    obj = build_qb_passing_distribution(
        identity_record=identity, prior_games=collins_records,
        as_of_utc="2026-10-14T20:30:00Z", thresholds=(150, 200, 250, 300))
    dist = obj["distribution"]
    shares = {e["threshold_yards"]: e["share_of_paths_at_or_above"]
              for e in dist["exceedance"]}
    collins_detail = {
        "mean": dist["mean_yards"], "sd": dist["sd_yards"],
        "shares": {str(t): shares[t] for t in (150, 200, 250, 300)}}
    ok = (abs(dist["mean_yards"] - 174.4) <= 1.5
          and abs(dist["sd_yards"] - 91.2) <= 1.5
          and all(abs(shares[t] - ref) <= 0.01 for t, ref in
                  ((150, 0.583), (200, 0.414), (250, 0.235), (300, 0.091))))
    print("Collins gate:", "PASS" if ok else "FAIL", collins_detail, flush=True)
    if not ok:
        with open(OUT_PATH, "w") as f:
            json.dump({"collins_gate": "FAILED", "detail": collins_detail}, f, indent=1)
        return

    # ---------- Assembly ----------
    with open(os.path.join(DATA, "fbs_2024_team_ids.json")) as f:
        fbs = json.load(f)["2024"]
    print("FBS teams 2024:", len(fbs), flush=True)
    games, missing = load_games()
    print(f"games assembled: {len(games)} (skipped {missing})", flush=True)

    team_games = defaultdict(list)
    qb_games = defaultdict(list)
    for g in games.values():
        g["_dt"] = kick_dt(g)
        sides = {c["team_id"]: c for c in g["competitors"].values()}
        for tid, ts in g["team_stats"].items():
            if tid not in sides:
                continue
            team_games[tid].append(g)
            for p in g["passers"].get(tid, []):
                qb_games[p["athlete_id"]].append({
                    "event_id": g["event_id"], "game_date_utc": g["kickoff"],
                    "qb_team": sides[tid]["name"],
                    "qb_attempts": float(p["att"]),
                    "qb_completions": float(p["comp"]),
                    "qb_passing_yards": float(p["yards"]),
                    "team_pass_attempts": ts["pass_att"],
                    "team_rush_attempts": ts["rush_att"],
                    "_dt": g["_dt"], "_team_id": tid})
    for tid in team_games:
        team_games[tid].sort(key=lambda g: g["_dt"])
    for aid in qb_games:
        qb_games[aid].sort(key=lambda r: r["_dt"])

    # ---------- Assembly audit: 10 records from the 2024 assembly
    # cross-checked against ESPN athlete gamelogs (Phase 2 method) ----------
    lo24 = datetime(2024, 8, 1, tzinfo=timezone.utc)
    hi24 = datetime(2025, 1, 1, tzinfo=timezone.utc)
    recs24 = []
    for aid in sorted(qb_games):
        for r in qb_games[aid]:
            if lo24 <= r["_dt"] < hi24:
                recs24.append((aid, r))
    step = max(1, len(recs24) // 10)
    audit_sample = recs24[::step][:10]
    audit_rows, audit_ok = [], 0
    for aid, rec in audit_sample:
        season = 2024
        url = ("https://site.web.api.espn.com/apis/common/v3/sports/"
               "football/college-football/athletes/"
               f"{aid}/gamelog?season={season}")
        got = None
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "SportsEdgeBacktest/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = json.loads(r.read().decode())
            if (payload.get("labels") or [])[:3] == ["CMP", "ATT", "YDS"]:
                for st in payload.get("seasonTypes") or []:
                    for cat in st.get("categories") or []:
                        for e in cat.get("events") or []:
                            if str(e.get("eventId")) == str(rec["event_id"]):
                                s = e.get("stats") or []
                                got = (int(s[1]), int(s[0]), int(s[2]))
        except Exception as exc:  # noqa: BLE001
            got = f"FETCH_ERROR:{exc}"
        want = (int(rec["qb_attempts"]), int(rec["qb_completions"]),
                int(rec["qb_passing_yards"]))
        match = (got == want)
        audit_ok += 1 if match else 0
        audit_rows.append({"event_id": rec["event_id"], "athlete_id": aid,
                           "assembled_att_comp_yards": want,
                           "gamelog_att_comp_yards": got, "match": match})
    print(f"audit (2024 assembly): {audit_ok}/10 exact", flush=True)
    if audit_ok < 9:
        with open(OUT_PATH, "w") as f:
            json.dump({"prereg_sha256": prereg_sha, "collins_gate": "PASSED",
                       "audit": audit_rows,
                       "verdict": "AUDIT_FAILED_SCORING_NOT_RUN"}, f, indent=1)
        print("AUDIT FAILED — scoring not run")
        return

    def is_illinois(name):
        return name is not None and PublicContext.key(name) in IL_COLLEGE_NAMES

    rows = []
    excl = defaultdict(int)
    candidates = 0
    tripwire = {"append_fixture_changes_or_refuses": 0,
                "post_asof_identical": 0, "of": 0}
    for g in sorted(games.values(), key=lambda x: x["_dt"]):
        if not (lo24 <= g["_dt"] < hi24):
            continue
        sides = list(g["competitors"].values())
        for side in sides:
            tid = side["team_id"]
            if tid not in fbs:
                continue
            candidates += 1
            opp = sides[1] if sides[0] is side else sides[0]
            if is_illinois(side["name"]) or is_illinois(opp["name"]):
                excl["ILLINOIS_EXCLUDED"] += 1
                continue
            priors_team = [tg for tg in team_games[tid] if tg["_dt"] < g["_dt"]]
            att_totals = defaultdict(int)
            for tg in priors_team:
                for p in tg["passers"].get(tid, []):
                    att_totals[p["athlete_id"]] += p["att"]
            if not att_totals:
                excl["IDENTITY_NOT_ESTABLISHED"] += 1
                continue
            qb_id = max(att_totals, key=lambda a: (att_totals[a], -a))
            qb_name = None
            for tg in priors_team:
                for p in tg["passers"].get(tid, []):
                    if p["athlete_id"] == qb_id:
                        qb_name = p["name"]
            priors = [r for r in qb_games[qb_id] if r["_dt"] < g["_dt"]]
            if len(priors) < 5:
                excl["INSUFFICIENT_PIT_HISTORY"] += 1
                continue
            ts = g["team_stats"].get(tid)
            if ts is None:
                excl["FIXTURE_STATS_MISSING"] += 1
                continue
            fixture_att = 0
            outcome = None
            for p in g["passers"].get(tid, []):
                if p["athlete_id"] == qb_id:
                    fixture_att = p["att"]
                    outcome = p["yards"]
            if ts["pass_att"] <= 0 or fixture_att < 0.6 * ts["pass_att"]:
                excl["ROLE_NOT_MATERIALIZED"] += 1
                continue
            kickoff_iso = g["kickoff"]
            as_of = (g["_dt"] - timedelta(hours=3)).astimezone(
                timezone.utc).isoformat().replace("+00:00", "Z")
            home = g["competitors"].get("home") or {}
            away = g["competitors"].get("away") or {}
            ident = {
                "status": STATUS_SATISFIED, "team_id": tid,
                "event_id": g["event_id"],
                "resolved_athlete_id": qb_id,
                "resolved_athlete_name": qb_name,
                "availability_status": AVAILABILITY,
                "kickoff_utc": kickoff_iso,
                "home_team_name": home.get("name"),
                "away_team_name": away.get("name"),
            }
            clean_priors = [{k: v for k, v in r.items()
                             if not k.startswith("_")} for r in priors]
            try:
                obj = build_qb_passing_distribution(
                    identity_record=ident, prior_games=clean_priors,
                    as_of_utc=as_of, thresholds=THRESHOLDS)
            except QBDistributionError as exc:
                excl[f"BUILDER_REFUSAL:{str(exc)[:50]}"] += 1
                continue
            d = obj["distribution"]
            share = {e["threshold_yards"]: e["share_of_paths_at_or_above"]
                     for e in d["exceedance"]}
            cdf_frozen = [1.0 - share.get(k + 1, 0.0) for k in range(0, 801)]
            y = outcome
            crps_frozen = crps_from_cdf(cdf_frozen, y)
            # B1: QB trailing empirical
            prior_yards = [r["qb_passing_yards"] for r in priors]
            b1map = {}
            for v in sorted(set(prior_yards)):
                b1map[int(v)] = prior_yards.count(v) / len(prior_yards)
            b1_cdf, run = [], 0.0
            for k in range(0, 801):
                run += b1map.get(k, 0.0)
                b1_cdf.append(run)
            crps_b1 = crps_from_cdf(b1_cdf, y)
            b1_share = {t: sum(1 for v in prior_yards if v >= t) / len(prior_yards)
                        for t in LADDER}
            b1_q = np.percentile(np.array(prior_yards, dtype=float), [5, 95])
            # B2: team-attempt chain (Phase 2 §5, seed policy mirrored)
            team_prior = [tg for tg in priors_team
                          if tg["team_stats"].get(tid, {}).get("pass_att", 0) > 0]
            pa = np.array([tg["team_stats"][tid]["pass_att"]
                           for tg in team_prior], dtype=float)
            ypa = np.array([tg["team_stats"][tid]["pass_yards"]
                            / tg["team_stats"][tid]["pass_att"]
                            for tg in team_prior], dtype=float)
            rng = np.random.default_rng(SEED)
            draw = rng.integers(0, len(pa), size=PATHS)
            samples_b2 = pa[draw] * ypa[draw]
            crps_b2 = crps_from_samples(samples_b2, y)
            srt = np.sort(samples_b2)
            cdf_b2 = np.searchsorted(srt, np.arange(0, 801), side="right") / len(srt)
            b2_share = {t: float(np.mean(samples_b2 >= t)) for t in LADDER}
            b2_q = np.percentile(samples_b2, [5, 95])
            # CHALLENGER: gamma mixture at the CDF level (exact pooled
            # mixture distribution of the preregistered path draw)
            cdf_chal = [GAMMA * cdf_frozen[k] + (1 - GAMMA) * float(cdf_b2[k])
                        for k in range(0, 801)]
            crps_chal = crps_from_cdf(cdf_chal, y)
            chal_share = {t: GAMMA * share.get(t, 0.0) + (1 - GAMMA) * b2_share[t]
                          for t in LADDER}
            def quantile_from_cdf(cdf, q):
                for k, f in enumerate(cdf):
                    if f >= q:
                        return k
                return 800
            chal_p5 = quantile_from_cdf(cdf_chal, 0.05)
            chal_p95 = quantile_from_cdf(cdf_chal, 0.95)
            q = d["quantiles_yards"]
            iso = g["_dt"].isocalendar()
            rows.append({
                "event_id": g["event_id"], "team": side["name"],
                "qb": qb_name, "date": g["kickoff"],
                "week": f"{iso[0]}-W{iso[1]:02d}", "y": y,
                "n_priors": len(priors),
                "crps_frozen": crps_frozen, "crps_challenger": crps_chal,
                "crps_b1": crps_b1, "crps_b2": crps_b2,
                "pit_frozen": cdf_frozen[y] if y <= 800 else 1.0,
                "pit_challenger": cdf_chal[y] if y <= 800 else 1.0,
                "pit_b1": b1_cdf[y] if y <= 800 else 1.0,
                "pit_b2": float(cdf_b2[y]) if y <= 800 else 1.0,
                "covered_frozen": 1 if q["p5"] <= y <= q["p95"] else 0,
                "covered_challenger": 1 if chal_p5 <= y <= chal_p95 else 0,
                "covered_b1": 1 if b1_q[0] <= y <= b1_q[1] else 0,
                "covered_b2": 1 if b2_q[0] <= y <= b2_q[1] else 0,
                "brier_frozen": {t: (share.get(t, 0.0) - (1.0 if y >= t else 0.0)) ** 2 for t in LADDER},
                "brier_challenger": {t: (chal_share[t] - (1.0 if y >= t else 0.0)) ** 2 for t in LADDER},
                "brier_b1": {t: (b1_share[t] - (1.0 if y >= t else 0.0)) ** 2 for t in LADDER},
                "brier_b2": {t: (b2_share[t] - (1.0 if y >= t else 0.0)) ** 2 for t in LADDER},
            })
            # ---- leakage tripwire on the first 10 scored fixtures ----
            if tripwire["of"] < 10:
                tripwire["of"] += 1
                fx = {"event_id": g["event_id"],
                      "game_date_utc": kickoff_iso,
                      "qb_team": side["name"],
                      "qb_attempts": float(fixture_att),
                      "qb_completions": float(
                          [p["comp"] for p in g["passers"].get(tid, [])
                           if p["athlete_id"] == qb_id][0]),
                      "qb_passing_yards": float(y),
                      "team_pass_attempts": ts["pass_att"],
                      "team_rush_attempts": ts["rush_att"]}
                try:
                    obj2 = build_qb_passing_distribution(
                        identity_record=ident,
                        prior_games=clean_priors + [fx],
                        as_of_utc=as_of, thresholds=(150,))
                    if abs(obj2["distribution"]["mean_yards"]
                           - d["mean_yards"]) > 1e-9:
                        tripwire["append_fixture_changes_or_refuses"] += 1
                except QBDistributionError:
                    tripwire["append_fixture_changes_or_refuses"] += 1
                ghost = dict(fx)
                ghost["event_id"] = "GHOST"
                ghost["game_date_utc"] = (
                    g["_dt"] - timedelta(hours=1)).astimezone(
                    timezone.utc).isoformat().replace("+00:00", "Z")
                obj3 = build_qb_passing_distribution(
                    identity_record=ident,
                    prior_games=clean_priors + [ghost],
                    as_of_utc=as_of, thresholds=THRESHOLDS)
                if obj3["distribution"]["mean_yards"] == d["mean_yards"] \
                        and obj3["distribution"]["sd_yards"] == d["sd_yards"]:
                    tripwire["post_asof_identical"] += 1
        print(f"scored so far: {len(rows)}", flush=True)

    n = len(rows)
    role_rate = (excl.get("ROLE_NOT_MATERIALIZED", 0) / candidates
                 if candidates else None)
    result = {
        "prereg": {"path": "model_fix_20261014/specs/PREREG_CFB_QB.md",
                   "sha256": prereg_sha,
                   "locked_sha256_in_SPEC_HASHES": "319629eee535bba913953c9178c6f4216476c453ff2231627647ae2fde85ca25"},
        "label": "RESEARCH_EVIDENCE — not a market verdict, not validation",
        "evaluand": {
            "builder": "sportsedge/research/cfb_qb_passing_distribution.py",
            "origin_main": "2a713380c7d49733577c238a126f487382634040",
            "local_clone_head": "12999fc227b6bce3f781749f99918d52c2080b9d",
            "builder_sha256": "163c2c5652691031b41790d3034fabf4391434e2c6bd3058c1bdbc701a049916",
            "byte_identical_origin_main_vs_phase2_evaluand": True,
            "paths": PATHS, "builder_seed": SEED},
        "challenger": {
            "gamma": GAMMA, "gamma_values_scored": [GAMMA],
            "construction": "F_chal(k) = 0.25*F_frozen(k) + 0.75*F_B2(k), "
                            "k=0..800 — the exact pooled-mixture distribution "
                            "of the preregistered per-path draw; B2 sample "
                            "generated per fixture with default_rng(20261014), "
                            "20,000 paths (Phase 2 seed policy)"},
        "assembly": {
            "source": "ESPN game summaries from disk cache "
                      "~/workspace/tmp/bt_data/espn_cfb (summary_*.json) — "
                      "the assembly the Phase 2 implementation actually used "
                      "(spec §2(b) fallback per its amendment); 2022-2023 "
                      "runway scoreboards+summaries acquired by the same "
                      "transport (groups=80) before scoring in this lane",
            "audit_gamelog_crosscheck_2024": audit_rows,
            "audit_exact": f"{audit_ok}/10"},
        "fbs_derivation": {
            "method": "derive_fbs_teams.py method transposed to 2024: NCAA.com "
                      "official FBS standings school list matched to corpus "
                      "team payloads (scripts/derive_fbs_teams_2024.py); 2024 "
                      "list = Phase 2's 2025 list (136) minus Delaware and "
                      "Missouri State (first FBS seasons 2025)",
            "count_2024": len(fbs)},
        "collins_gate": "PASSED",
        "collins_detail": collins_detail,
        "tripwire": tripwire,
        "identity_note": "plurality over ALL prior team games in the record "
                         "set; ties broken by smallest athlete id "
                         "(production/Phase 2 rule, unchanged)",
        "split": "SINGLE_SPLIT 2024 (fixtures Aug-Dec 2024); priors reach "
                 "into 2022-2024 via ESPN summary assembly",
        "population": {
            "candidates": candidates, "scored": n,
            "exclusions": dict(excl),
            "role_not_materialized_rate_of_candidates": role_rate},
    }
    if rows:
        result["crps"] = {arm: sum(r[f"crps_{arm}"] for r in rows) / n
                          for arm in ("frozen", "challenger", "b1", "b2")}
        result["ci_challenger_minus_frozen"] = bootstrap_ci(rows, "crps_challenger", "crps_frozen")
        result["ci_challenger_minus_b1"] = bootstrap_ci(rows, "crps_challenger", "crps_b1")
        result["ci_challenger_minus_b2"] = bootstrap_ci(rows, "crps_challenger", "crps_b2")
        result["coverage_p5_p95"] = {
            arm: sum(r[f"covered_{arm}"] for r in rows) / n
            for arm in ("frozen", "challenger", "b1", "b2")}
        result["pit_histogram"] = {
            arm: pit_hist(rows, f"pit_{arm}")
            for arm in ("frozen", "challenger", "b1", "b2")}
        result["pit_note"] = "PIT value = arm CDF at realized y (discrete CDF form)"
        result["threshold_brier"] = {
            arm: {str(t): sum(r[f"brier_{arm}"][t] for r in rows) / n
                  for t in LADDER}
            for arm in ("frozen", "challenger", "b1", "b2")}
        gate = all(result[k][1] < 0 for k in (
            "ci_challenger_minus_frozen", "ci_challenger_minus_b1",
            "ci_challenger_minus_b2"))
        result["gate_verdict"] = "ADOPT-CANDIDATE" if gate else "KEEP FROZEN"
        result["bootstrap"] = {"method": "ISO-week block bootstrap",
                               "resamples": 2000, "seed": BOOT_SEED}
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump(result, f, indent=1)
    print("WROTE", OUT_PATH, flush=True)
    print(json.dumps({k: result.get(k) for k in
                      ("crps", "ci_challenger_minus_frozen",
                       "ci_challenger_minus_b1", "ci_challenger_minus_b2",
                       "gate_verdict", "population")}, indent=1), flush=True)


if __name__ == "__main__":
    main()
