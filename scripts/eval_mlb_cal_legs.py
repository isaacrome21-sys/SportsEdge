"""MLB Lane A calibration legs M6 (team totals) + M3 (alternate run lines).

Evaluand: artifacts/free_models.py Lane A team means, as published in
the Stage 1 M2 audit artifact (hash-verified at load), read as the
construction's own independent-Poisson distributions.

Governing specs (verified at runtime; a mismatch stops the run):
- mlb_market_legs_20261014/SPEC_M6_TEAM_TOTALS.md
  SHA-256 92d92c6ef1ae082b91940197571cf70fc474d2b7f1fc4459383dd70710ea6b43
- mlb_market_legs_20261014/SPEC_M3_ALT_RUNLINE.md
  SHA-256 fd49b533b937e51fe6ad1924b6efe076d43317cbb4711318a206c60b6dae3202

Label of output: RESEARCH_EVIDENCE (retrospective calibration only).
The M6/M3 market legs are FORWARD_ONLY_BY_DESIGN and are not scored.

Verification built into the run (spec M6 SS5 / M3 SS5):
- Dataset and audit SHA-256 verified at load.
- The M2 SS8 climatology is reconstructed independently here; the
  eligible set must equal the audit's crps_clim-nonempty set exactly
  and recomputed margin CRPS must match the audit's crps_clim to
  rounding (<= 2e-6) on every eligible game, else the run stops.
- M3 main-line cells are checked against the audit's own p_model /
  y columns on the closing-spread subsets (tolerance 2e-6, the
  audit's 6-dp rounding bound).
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import json
import math
import random
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
REPO = HOME / "workspace/tmp/wt-market-legs"
LANE = REPO / "mlb_market_legs_20261014"
WS_RESULTS = HOME / "workspace/sportsedge/mlb_market_legs_20261014/results"

EXPECTED_DATASET_SHA256 = (
    "3f952fd0bfae9f4f2d17e66692cb936ce6e1a5f6b415318012090c85933b882b")
EXPECTED_AUDIT_SHA256 = (
    "b0b39ab2a92e2114ed4ecaa9b0823396fb28bbd917d248e8cf448b82967b39dc")
SPEC_SHA256 = {
    "M6": "92d92c6ef1ae082b91940197571cf70fc474d2b7f1fc4459383dd70710ea6b43",
    "M3": "fd49b533b937e51fe6ad1924b6efe076d43317cbb4711318a206c60b6dae3202",
}
MAIN_PIN = "83e0c396a4761ea3de80583be5e61e8ca2e07f9a"
FREE_MODELS_BLOB = "253b0c6d91840c906941216be117f2acc1497a57"
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261015
EPS = 1e-15
CLIM_MIN_PRIOR = 30
SEALED_START = datetime(2024, 7, 1, tzinfo=timezone.utc)
SEALED_END = datetime(2024, 9, 1, tzinfo=timezone.utc)

HALF_LINES = [-4.5, -3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5, 4.5]
INT_LINES = [-4.0, -3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0]
ALL_LINES = HALF_LINES + INT_LINES

sys.path.insert(0, str(REPO / "artifacts"))
import free_models as fm  # noqa: E402


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def check_spec_hashes():
    for item, fname in (("M6", "SPEC_M6_TEAM_TOTALS.md"),
                        ("M3", "SPEC_M3_ALT_RUNLINE.md")):
        got = sha256_bytes((LANE / fname).read_bytes())
        if got != SPEC_SHA256[item]:
            raise SystemExit(f"SPEC_SHA256_MISMATCH {item}: {got}")


def check_model_blob():
    out = subprocess.run(
        ["git", "-C", str(HOME / "workspace/tmpgit/sportsedge-ci"),
         "rev-parse", f"{MAIN_PIN}:artifacts/free_models.py"],
        capture_output=True, text=True, check=True).stdout.strip()
    if out != FREE_MODELS_BLOB:
        raise SystemExit(f"MODEL_BLOB_MISMATCH at pin: {out}")
    local = subprocess.run(
        ["git", "-C", str(REPO), "hash-object", "artifacts/free_models.py"],
        capture_output=True, text=True, check=True).stdout.strip()
    if local != FREE_MODELS_BLOB:
        raise SystemExit(f"MODEL_BLOB_MISMATCH in worktree: {local}")


def parse_start(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def in_sealed_window(start):
    return SEALED_START <= start < SEALED_END


def load_games(path):
    raw_bytes = Path(path).read_bytes()
    if sha256_bytes(raw_bytes) != EXPECTED_DATASET_SHA256:
        raise SystemExit("DATASET_SHA256_MISMATCH — refusing to score")
    raw = json.loads(raw_bytes)
    games = []
    for date_key in sorted(raw):
        for g in raw[date_key]:
            gv = g.get("gameView") or {}
            games.append({
                "start": parse_start(gv["startDate"]),
                "season": parse_start(gv["startDate"]).year,
                "game_type": gv.get("gameType"),
                "home": (gv.get("homeTeam") or {}).get("fullName"),
                "away": (gv.get("awayTeam") or {}).get("fullName"),
                "home_score": gv.get("homeTeamScore"),
                "away_score": gv.get("awayTeamScore"),
            })
    games.sort(key=lambda g: (g["start"], g["away"] or "", g["home"] or ""))
    return games


def load_audit(path):
    raw = Path(path).read_bytes()
    if sha256_bytes(raw) != EXPECTED_AUDIT_SHA256:
        raise SystemExit("AUDIT_SHA256_MISMATCH — refusing to score")
    rows = {}
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            if r["status"] == "INCLUDED":
                rows[(r["start"], r["away"], r["home"])] = r
    return rows


def brier(p, y):
    return (p - y) ** 2


def logloss(p, y):
    p = min(max(p, EPS), 1.0 - EPS)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def block_bootstrap_ci(diffs_by_block, resamples=BOOTSTRAP_RESAMPLES,
                       seed=BOOTSTRAP_SEED):
    blocks = [list(v) for v in diffs_by_block.values() if v]
    if not blocks:
        return None
    total_n = sum(len(b) for b in blocks)
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        s, n = 0.0, 0
        for _ in range(len(blocks)):
            block = blocks[rng.randrange(len(blocks))]
            s += sum(block)
            n += len(block)
        means.append(s / n)
    means.sort()
    return {"mean_diff": sum(sum(b) for b in blocks) / total_n,
            "ci95_lo": means[int(0.025 * resamples)],
            "ci95_hi": means[min(resamples - 1, int(0.975 * resamples))],
            "n_blocks": len(blocks), "resamples": resamples}


def crps_int(pmf, y):
    ks = sorted(pmf)
    lo, hi = ks[0], ks[-1]
    cum, idx, total = 0.0, 0, 0.0
    for k in range(lo - 1, hi + 1):
        while idx < len(ks) and ks[idx] <= k:
            cum += pmf[ks[idx]]
            idx += 1
        ind = 1.0 if y <= k else 0.0
        total += (cum - ind) ** 2
    return total


def margin_pmf(home_mean, away_mean):
    a, b = fm.poisson(home_mean), fm.poisson(away_mean)
    pmf = defaultdict(float)
    for h, ph in enumerate(a):
        if ph == 0.0:
            continue
        for aw, pa in enumerate(b):
            if pa:
                pmf[h - aw] += ph * pa
    return dict(pmf)


def week_key(start):
    iso = start.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--m2-audit", required=True)
    args = ap.parse_args()

    check_spec_hashes()
    check_model_blob()
    games = load_games(args.dataset)
    audit = load_audit(args.m2_audit)

    # Climatology streams per season (population games, start order):
    # margins and (home_runs, away_runs) pairs.
    clim_starts = defaultdict(list)
    clim_margins = defaultdict(list)
    clim_pairs = defaultdict(list)
    for g in games:
        if g["game_type"] != "R" or in_sealed_window(g["start"]):
            continue
        if g["home_score"] is None or g["away_score"] is None:
            continue
        clim_starts[g["season"]].append(g["start"])
        clim_margins[g["season"]].append(g["home_score"] - g["away_score"])
        clim_pairs[g["season"]].append((g["home_score"], g["away_score"]))

    counts = Counter()
    m6_rows = []       # per game: season, week, crps_model, crps_clim|None,
                       #           crps_model_home/away, midpit_home/away
    m3_game = []       # per game: season, week, d_brier, d_logloss (paired
                       #           subset only)
    m3_lines = defaultdict(list)  # line -> per-game dicts (paired subset)
    m3_check = {-1.5: [], 1.5: []}  # (brier from recomputed, brier from audit)
    clim_repro_max_dev = 0.0
    clim_set_mismatch = 0
    equiv_checks = 0
    equiv_max_dev = 0.0

    for g in games:
        if g["game_type"] != "R" or in_sealed_window(g["start"]):
            continue
        if g["home_score"] is None or g["away_score"] is None:
            continue
        if g["home_score"] == g["away_score"]:
            continue
        key = (g["start"].isoformat(), g["away"], g["home"])
        arow = audit.get(key)
        if arow is None:
            continue
        counts["matched"] += 1
        home_mean = float(arow["home_mean"])
        away_mean = float(arow["away_mean"])
        margin = g["home_score"] - g["away_score"]
        wk = week_key(g["start"])
        season = g["season"]

        # --- climatology snapshot (strictly prior, same season) ---
        starts = clim_starts[season]
        idx = bisect.bisect_left(starts, g["start"])
        eligible = idx >= CLIM_MIN_PRIOR
        audit_eligible = arow["crps_clim"] != ""
        if eligible != audit_eligible:
            clim_set_mismatch += 1
        margin_counts = None
        team_counts = None
        if eligible:
            mvals = clim_margins[season][:idx]
            margin_counts = Counter(mvals)
            pmf_c = {v: c / idx for v, c in margin_counts.items()}
            c_clim_repro = crps_int(pmf_c, margin)
            dev = abs(c_clim_repro - float(arow["crps_clim"]))
            clim_repro_max_dev = max(clim_repro_max_dev, dev)
            tvals = [r for pair in clim_pairs[season][:idx] for r in pair]
            team_counts = Counter(tvals)

        # --- M6: team totals ---
        pmf_h = {k: p for k, p in enumerate(fm.poisson(home_mean))}
        pmf_a = {k: p for k, p in enumerate(fm.poisson(away_mean))}
        cm_h = crps_int(pmf_h, g["home_score"])
        cm_a = crps_int(pmf_a, g["away_score"])
        def midpit(pmf, y):
            flo = sum(p for k, p in pmf.items() if k < y)
            return flo + 0.5 * pmf.get(y, 0.0)
        row6 = {"season": season, "week": wk,
                "crps_model": (cm_h + cm_a) / 2,
                "crps_model_home": cm_h, "crps_model_away": cm_a,
                "midpit_home": midpit(pmf_h, g["home_score"]),
                "midpit_away": midpit(pmf_a, g["away_score"]),
                "crps_clim": None}
        if eligible:
            n_t = sum(team_counts.values())
            pmf_t = {v: c / n_t for v, c in team_counts.items()}
            row6["crps_clim"] = (crps_int(pmf_t, g["home_score"])
                                 + crps_int(pmf_t, g["away_score"])) / 2
        else:
            counts["m6_clim_ineligible"] += 1
        m6_rows.append(row6)

        # --- M3: alternate lines (paired subset only) ---
        if eligible:
            # Cover probabilities are read off the game's margin PMF
            # (the module's own poisson() marginals convolved once).
            # Equivalence with fm.model_probability at every grid
            # line is asserted on the first 50 paired games below.
            mpmf = margin_pmf(home_mean, away_mean)
            mkeys = sorted(mpmf)
            mcum = []
            run = 0.0
            for k in mkeys:
                run += mpmf[k]
                mcum.append(run)

            def p_margin_gt(t):
                j = bisect.bisect_right(mkeys, t)
                return 1.0 - (mcum[j - 1] if j else 0.0)

            if equiv_checks < 50:
                for s in ALL_LINES:
                    w_ref, p_ref = fm.model_probability(
                        "MLB", "SPREAD", "HOME", s, home_mean, away_mean)
                    push_from_pmf = mpmf.get(int(-s), 0.0) \
                        if float(s).is_integer() else 0.0
                    dev = max(abs(p_margin_gt(-s) - w_ref),
                              abs(push_from_pmf - p_ref))
                    equiv_max_dev = max(equiv_max_dev, dev)
                equiv_checks += 1
                if equiv_max_dev > 1e-9:
                    raise SystemExit(
                        f"MARGIN_PMF_EQUIVALENCE_FAILED dev "
                        f"{equiv_max_dev:.2e} — refusing to score.")

            per_line_b, per_line_l = [], []
            for s in ALL_LINES:
                win_m = p_margin_gt(-s)
                push_m = mpmf.get(int(-s), 0.0) \
                    if float(s).is_integer() else 0.0
                tot = idx
                n_above = sum(c for v, c in margin_counts.items()
                              if v + s > 0)
                n_push = margin_counts.get(int(-s), 0) \
                    if float(s).is_integer() else 0
                n_below = tot - n_above - n_push
                if margin + s == 0:
                    # this game pushed at this line: excluded for both
                    m3_lines[s].append({"push_game": True})
                    continue
                if float(s).is_integer():
                    p_mod = win_m / (win_m + (1.0 - win_m - push_m)) \
                        if (1.0 - push_m) > 0 else 0.5
                    p_bas = n_above / (n_above + n_below) \
                        if (n_above + n_below) > 0 else 0.5
                else:
                    p_mod = win_m
                    p_bas = n_above / tot
                y = 1 if margin + s > 0 else 0
                db = brier(p_mod, y) - brier(p_bas, y)
                dl = logloss(p_mod, y) - logloss(p_bas, y)
                per_line_b.append(db)
                per_line_l.append(dl)
                m3_lines[s].append({
                    "season": season, "week": wk, "push_game": False,
                    "p_model": p_mod, "p_base": p_bas, "y": y,
                    "d_brier": db, "d_logloss": dl})
            m3_game.append({
                "season": season, "week": wk,
                "d_brier": sum(per_line_b) / len(per_line_b),
                "d_logloss": sum(per_line_l) / len(per_line_l)})

        # --- M3 consistency check vs the audit's own columns ---
        hs = float(arow["home_spread"])
        if hs in (-1.5, 1.5):
            s = hs
            win_m, _ = fm.model_probability(
                "MLB", "SPREAD", "HOME", s, home_mean, away_mean)
            y = int(arow["y_home_cover"])
            m3_check[s].append((brier(win_m, y),
                                brier(float(arow["p_model_home_cover"]), y)))

    if clim_set_mismatch:
        raise SystemExit(
            f"CLIMATOLOGY_ELIGIBILITY_SET_MISMATCH on {clim_set_mismatch} "
            "games — reconstruction does not reproduce the M2 audit; "
            "refusing to score.")
    if clim_repro_max_dev > 2e-6:
        raise SystemExit(
            f"CLIMATOLOGY_CRPS_REPRO_DEVIATION {clim_repro_max_dev:.2e} "
            "> 2e-6 — refusing to score.")

    check_out = {}
    for s, pairs in m3_check.items():
        if pairs:
            dev = max(abs(a - b) for a, b in pairs)
            check_out[str(s)] = {"n": len(pairs), "max_brier_dev": dev}
            if dev > 2e-6:
                raise SystemExit(
                    f"M3_CONSISTENCY_CHECK_FAILED at line {s}: {dev:.2e}")

    # ---------- M6 summaries ----------
    def m6_summary(rows):
        out = {"n": len(rows)}
        paired = [r for r in rows if r["crps_clim"] is not None]
        out["n_paired"] = len(paired)
        if rows:
            out["crps_model_mean"] = \
                sum(r["crps_model"] for r in rows) / len(rows)
        if paired:
            out["crps_model_mean_paired"] = \
                sum(r["crps_model"] for r in paired) / len(paired)
            out["crps_clim_mean_paired"] = \
                sum(r["crps_clim"] for r in paired) / len(paired)
            by_block = defaultdict(list)
            for r in paired:
                by_block[r["week"]].append(r["crps_model"] - r["crps_clim"])
            out["paired_crps_diff"] = block_bootstrap_ci(by_block)
            out["crps_model_home_mean"] = \
                sum(r["crps_model_home"] for r in paired) / len(paired)
            out["crps_model_away_mean"] = \
                sum(r["crps_model_away"] for r in paired) / len(paired)
            pits = sorted([r["midpit_home"] for r in paired]
                          + [r["midpit_away"] for r in paired])
            out["midpit_deciles"] = [
                pits[min(len(pits) - 1, int(q * len(pits)))]
                for q in (0.1, 0.25, 0.5, 0.75, 0.9)]
        return out

    m6_overall = m6_summary(m6_rows)
    m6_seasons = {str(s): m6_summary([r for r in m6_rows
                                      if r["season"] == s])
                  for s in sorted({r["season"] for r in m6_rows})}
    m6_verdict = ("BEATS_BASELINE"
                  if m6_overall["paired_crps_diff"]["ci95_hi"] < 0
                  else "DOES_NOT_BEAT_BASELINE")

    # ---------- M3 summaries ----------
    def paired_ci(game_rows, field):
        by_block = defaultdict(list)
        for r in game_rows:
            by_block[r["week"]].append(r[field])
        return block_bootstrap_ci(by_block)

    m3_overall = {"n_games_paired": len(m3_game),
                  "paired_brier_diff": paired_ci(m3_game, "d_brier"),
                  "paired_logloss_diff": paired_ci(m3_game, "d_logloss")}
    m3_seasons = {}
    for s in sorted({r["season"] for r in m3_game}):
        sub = [r for r in m3_game if r["season"] == s]
        m3_seasons[str(s)] = {
            "n_games_paired": len(sub),
            "paired_brier_diff": paired_ci(sub, "d_brier"),
            "paired_logloss_diff": paired_ci(sub, "d_logloss")}
    m3_verdict = ("BEATS_BASELINE"
                  if (m3_overall["paired_brier_diff"]["ci95_hi"] < 0
                      and m3_overall["paired_logloss_diff"]["ci95_hi"] < 0)
                  else "DOES_NOT_BEAT_BASELINE")

    line_table = {}
    for s in ALL_LINES:
        entries = m3_lines[s]
        scored = [e for e in entries if not e["push_game"]]
        pushes = len(entries) - len(scored)
        by_block = defaultdict(list)
        for e in scored:
            by_block[e["week"]].append(e["d_brier"])
        line_table[str(s)] = {
            "n_resolved": len(scored), "push_games_excluded": pushes,
            "mean_p_model": (sum(e["p_model"] for e in scored)
                             / len(scored)) if scored else None,
            "mean_p_base": (sum(e["p_base"] for e in scored)
                            / len(scored)) if scored else None,
            "observed_cover_rate": (sum(e["y"] for e in scored)
                                    / len(scored)) if scored else None,
            "brier_model": (sum(brier(e["p_model"], e["y"]) for e in scored)
                            / len(scored)) if scored else None,
            "brier_base": (sum(brier(e["p_base"], e["y"]) for e in scored)
                           / len(scored)) if scored else None,
            "paired_brier_diff": block_bootstrap_ci(by_block)
            if scored else None}

    generated = datetime.now(timezone.utc).isoformat()
    base_meta = {
        "label": "RESEARCH_EVIDENCE_RETROSPECTIVE_NOT_VALIDATION",
        "evidence_class": "RETROSPECTIVE_DIAGNOSTIC — calibration leg "
                          "only; no market leg exists for this family "
                          "historically (FORWARD_ONLY_BY_DESIGN).",
        "model_identity": {
            "file": "artifacts/free_models.py",
            "main_commit": MAIN_PIN,
            "blob_sha1": FREE_MODELS_BLOB,
            "path": "Lane A team means from the Stage 1 M2 audit "
                    "artifact (M1-verified walk-forward), module "
                    "poisson() / model_probability() read directly"},
        "dataset": {
            "file": "mlb_odds_dataset.json",
            "sha256": EXPECTED_DATASET_SHA256, "in_repo": False,
            "manifest": "mlb_market_legs_20261014/DATASET_MANIFEST.md + "
                        "DATASET_MANIFEST_STAGE2.md",
            "audit_artifact": "mlb_market_legs_20261014/"
                              "audit_m2_runline.csv",
            "audit_sha256": EXPECTED_AUDIT_SHA256},
        "counts": dict(counts),
        "verification": {
            "dataset_sha256_verified": True,
            "audit_sha256_verified": True,
            "spec_sha256_verified": True,
            "model_blob_verified_at_pin_and_worktree": True,
            "climatology_reconstruction": {
                "eligibility_set_matches_audit": True,
                "crps_clim_max_reproduction_deviation": clim_repro_max_dev},
            "margin_pmf_equivalence_vs_model_probability": {
                "games_checked": equiv_checks,
                "lines_per_game": len(ALL_LINES),
                "max_deviation": equiv_max_dev},
        },
        "generated_at": generated,
    }

    res6 = {"item": "M6_TEAM_TOTAL_RUNS_CAL_LEG",
            "spec_sha256": SPEC_SHA256["M6"],
            **base_meta,
            "overall": m6_overall, "by_season": m6_seasons,
            "verdict": m6_verdict}
    res3 = {"item": "M3_ALTERNATE_RUN_LINES_CAL_LEG",
            "spec_sha256": SPEC_SHA256["M3"],
            **base_meta,
            "overall": m3_overall, "by_season": m3_seasons,
            "per_line": line_table,
            "verification": {**base_meta["verification"],
                             "main_line_consistency_vs_audit": check_out},
            "verdict": m3_verdict}

    (LANE / "results_m6_team_totals.json").write_text(
        json.dumps(res6, indent=2))
    (LANE / "results_m3_alt_runline.json").write_text(
        json.dumps(res3, indent=2))

    WS_RESULTS.mkdir(parents=True, exist_ok=True)
    with open(WS_RESULTS / "audit_m6_team_totals.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["season", "week", "crps_model", "crps_model_home",
                    "crps_model_away", "crps_clim", "midpit_home",
                    "midpit_away"])
        for r in m6_rows:
            w.writerow([r["season"], r["week"], round(r["crps_model"], 6),
                        round(r["crps_model_home"], 6),
                        round(r["crps_model_away"], 6),
                        (round(r["crps_clim"], 6)
                         if r["crps_clim"] is not None else ""),
                        round(r["midpit_home"], 6),
                        round(r["midpit_away"], 6)])
    with open(WS_RESULTS / "audit_m3_alt_runline.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["season", "week", "line", "p_model", "p_base", "y"])
        for s in ALL_LINES:
            for e in m3_lines[s]:
                if not e["push_game"]:
                    w.writerow([e["season"], e["week"], s,
                                round(e["p_model"], 6),
                                round(e["p_base"], 6), e["y"]])

    print(json.dumps({"M6": {"verdict": m6_verdict,
                             "overall": m6_overall},
                      "M3": {"verdict": m3_verdict,
                             "overall": m3_overall}}, indent=2))


if __name__ == "__main__":
    main()
