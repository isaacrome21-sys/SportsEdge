"""NFL passing-yards v2 forward screen scorer (construction F). RESEARCH_ONLY.

Implements the forward screen defined in the DRAFT preregistration
``research/grok_nfl_passyds_v2_20261022/PREREG_DRAFT_NFL_PASSING_YARDS_V2.md``
(branch ``grok/nfl-passyds-v2-prereg-focus-20261022`` @ 7d6431ff816c; the draft
is NOT FROZEN and this scorer does not freeze anything).

Construction F (constants fixed in the draft, section 3):

    mu_v2 = mu_v1 * r
    r = (sum_y + K * mbar) / (sum_mu_v1 + K * mbar),   K = 200

The sums run over all PASS_YDS-qualified rows (frozen v1 gate) in weeks 4+ of
the current season, in weeks strictly before the game; mbar is the mean mu_v1
of those rows; with no such rows, r = 1. r is recomputed per game week from
in-season data only -- there is no single global multiplier. Everything else
is v1 exactly: the PASS_YDS gate, the K = 3 shrinkage in ``mu_for``, the
league pool, and the gamma CRPS with the frozen cv = 0.3496. v1 is imported
from the pinned frozen evaluator after a sha256 check; v1's files and scoring
are never modified.

Forward screen (draft section 4):

- Population: 2026 regular season, weeks 8 and later, on nflverse weekly
  data in the frozen v1 file layout (``ps_*.csv.gz`` / ``sp_*.csv.gz`` in one
  data directory -- the same records the v1 evaluator consumes). Scoring
  stops after 4 full weeks: weeks 8-11 are scored; rows from week 12 on are
  reported as out-of-window and never scored.
- The verdict is issued only once all 4 window weeks are present
  (SCREEN_INCOMPLETE before that; no interim pass or fail).
- PASS_SCREEN requires ALL of: mean dCRPS (v2 - v1) < 0, the 95%
  season-week-clustered CI upper bound < 0 (the evaluator's cluster
  bootstrap, blocks = season-week), and |bias_v2| < |bias_v1|, where
  bias = mean(mu - y) over the scored rows.
- A completed window that fails any condition is recorded FAILED_SCREEN.
  v2 is not frozen either way by this scorer: a pass earns only a separate
  owner freeze ruling, and no PLAY eligibility changes. Label:
  RESEARCH_ONLY / NOT_VALIDATED.

Usage:
  python3 score_nfl_passyds_v2_screen.py --data DIR --out results.json
      [--season 2026]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
EVALUATOR_PATH = (REPO_ROOT / "research" / "nfl_props_part2_20261018"
                  / "eval_nfl_props_calibration_v1.py")
# Same pin the Part 2 forward pricer uses for the frozen v1 evaluator.
EVALUATOR_SHA256 = "66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b"
PREREG_DRAFT = ("research/grok_nfl_passyds_v2_20261022/"
                "PREREG_DRAFT_NFL_PASSING_YARDS_V2.md")
PREREG_DRAFT_BRANCH_SHA = "7d6431ff816ce740fa537efdc1f39513afdc8e33"

K_SHRINKAGE = 200.0          # construction F constant, draft section 3
CV_FROZEN = 0.3496           # frozen v1 gamma shape for PASS_YDS, draft section 1
SCREEN_SEASON = 2026
WINDOW_FIRST_WEEK = 8
WINDOW_WEEKS = 4             # scoring stops after 4 full weeks: weeks 8-11
POOL_FIRST_WEEK = 4          # correction pool rows are weeks 4+ (draft section 3)


def load_evaluator():
    """Import the frozen v1 evaluator by path, after verifying its hash."""
    digest = hashlib.sha256(EVALUATOR_PATH.read_bytes()).hexdigest()
    if digest != EVALUATOR_SHA256:
        raise SystemExit(f"EVALUATOR_HASH_MISMATCH: {digest} != pinned {EVALUATOR_SHA256}")
    spec = importlib.util.spec_from_file_location("nfl_passyds_v2_v1_evaluator",
                                                  EVALUATOR_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def qualified_season_rows(ev, data: dict, season: int) -> list[dict]:
    """All PASS_YDS-qualified rows for one season, with frozen v1 mus.

    Uses the evaluator's own build/league_pool/mu_for, so the gate, the pool
    and the K = 3 shrinkage are v1 exactly (prior-season fallback included).
    """
    cfg = ev.MARKETS["PASS_YDS"]
    seasons = ev.build(data, cfg)
    rows = []
    for w, pid, prior, y in seasons.get(season, []):
        pool = ev.league_pool(seasons, season, w)
        rows.append({"season": season, "week": int(w), "pid": pid,
                     "y": float(y), "mu_v1": float(ev.mu_for(prior, pool))})
    return sorted(rows, key=lambda r: (r["week"], r["pid"]))


def correction_ratio(pool_rows: list[dict]) -> float:
    """Construction F ratio r for one game week (draft section 3)."""
    if not pool_rows:
        return 1.0
    sum_y = float(sum(r["y"] for r in pool_rows))
    sum_mu = float(sum(r["mu_v1"] for r in pool_rows))
    mbar = sum_mu / len(pool_rows)
    return (sum_y + K_SHRINKAGE * mbar) / (sum_mu + K_SHRINKAGE * mbar)


def ratio_for_week(rows: list[dict], week: int) -> float:
    """r from in-season qualified rows in weeks 4+ strictly before ``week``."""
    pool = [r for r in rows if POOL_FIRST_WEEK <= r["week"] < week]
    return correction_ratio(pool)


def decide_verdict(mean_dcrps: float, ci95_hi: float, bias_v1: float,
                   bias_v2: float, window_complete: bool) -> str:
    """The draft section 4 pass/fail rule, applied once the window closes."""
    if not window_complete:
        return "SCREEN_INCOMPLETE"
    if mean_dcrps < 0 and ci95_hi < 0 and abs(bias_v2) < abs(bias_v1):
        return "PASS_SCREEN"
    return "FAILED_SCREEN"


def score_screen(ev, rows: list[dict], season: int = SCREEN_SEASON) -> dict:
    """Score the forward screen over one season's qualified rows."""
    grid = np.arange(ev.GRID_LO, ev.GRID_HI + 1, dtype=float)
    cfg_count = ev.MARKETS["PASS_YDS"]["count"]
    window = list(range(WINDOW_FIRST_WEEK, WINDOW_FIRST_WEEK + WINDOW_WEEKS))
    scored, out_of_window = [], []
    for r in rows:
        if r["week"] < WINDOW_FIRST_WEEK:
            continue
        if r["week"] > window[-1]:
            out_of_window.append({"week": r["week"], "pid": r["pid"]})
            continue
        ratio = ratio_for_week(rows, r["week"])
        mu_v2 = r["mu_v1"] * ratio
        crps_v1 = ev.crps(ev.candidate_cdf(r["mu_v1"], CV_FROZEN, cfg_count, grid),
                          r["y"], grid)
        crps_v2 = ev.crps(ev.candidate_cdf(mu_v2, CV_FROZEN, cfg_count, grid),
                          r["y"], grid)
        scored.append({**r, "ratio": ratio, "mu_v2": mu_v2,
                       "crps_v1": crps_v1, "crps_v2": crps_v2,
                       "dcrps": crps_v2 - crps_v1,
                       "block": f"{season}-W{r['week']:02d}"})
    weeks_present = sorted({r["week"] for r in scored})
    window_complete = all(w in weeks_present for w in window)
    result = {
        "label": "RESEARCH_ONLY / NOT_VALIDATED (forward screen; not a freeze, not a PLAY)",
        "construction": "F (in-season ratio correction, K=200 shrinkage toward 1)",
        "prereg_draft": PREREG_DRAFT,
        "prereg_draft_branch_sha": PREREG_DRAFT_BRANCH_SHA,
        "evaluator_sha256": EVALUATOR_SHA256,
        "season": season,
        "window_weeks": window,
        "weeks_present": weeks_present,
        "window_complete": window_complete,
        "n_scored": len(scored),
        "n_out_of_window": len(out_of_window),
        "out_of_window_rows": out_of_window,
        "rows": scored,
    }
    if not scored:
        result.update({"mean_dcrps": None, "ci95_lo": None, "ci95_hi": None,
                       "bias_v1": None, "bias_v2": None,
                       "verdict": "SCREEN_INCOMPLETE",
                       "verdict_reason": "NO_SCORED_ROWS_IN_WINDOW"})
        return result
    boot = ev.boot([r["dcrps"] for r in scored], [r["block"] for r in scored])
    bias_v1 = float(np.mean([r["mu_v1"] - r["y"] for r in scored]))
    bias_v2 = float(np.mean([r["mu_v2"] - r["y"] for r in scored]))
    verdict = decide_verdict(boot["mean"], boot["ci95_hi"], bias_v1, bias_v2,
                             window_complete)
    result.update({
        "mean_dcrps": boot["mean"], "ci95_lo": boot["ci95_lo"],
        "ci95_hi": boot["ci95_hi"], "n_blocks": boot["n_blocks"],
        "bias_v1": bias_v1, "bias_v2": bias_v2,
        "mean_crps_v1": float(np.mean([r["crps_v1"] for r in scored])),
        "mean_crps_v2": float(np.mean([r["crps_v2"] for r in scored])),
        "verdict": verdict,
        "verdict_reason": ("WINDOW_COMPLETE" if window_complete
                           else "FEWER_THAN_4_FULL_WEEKS_PRESENT"),
        "on_pass": "NO FREEZE: a separate owner ruling is required (draft section 4)",
        "on_fail": "Recorded FAILED_SCREEN; v2 is not frozen (draft section 4)",
    })
    return result


def data_provenance(data_dir: Path, season: int) -> dict:
    """sha256 of the season's nflverse weekly files, if present (unpinned
    forward data: recorded, never assumed)."""
    out = {}
    for name in (f"ps_{season}.csv.gz", f"sp_{season}.csv.gz"):
        p = data_dir / name
        if p.exists():
            out[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def run(data_dir: Path, season: int = SCREEN_SEASON) -> dict:
    ev = load_evaluator()
    data = ev.load(data_dir)
    rows = qualified_season_rows(ev, data, season)
    result = score_screen(ev, rows, season)
    result["data_files"] = data_provenance(data_dir, season)
    result["n_qualified_rows_season"] = len(rows)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--season", type=int, default=SCREEN_SEASON)
    a = ap.parse_args()
    result = run(a.data, a.season)
    a.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    print(result["verdict"], "n_scored", result["n_scored"],
          "mean_dcrps", result.get("mean_dcrps"),
          "ci95_hi", result.get("ci95_hi"),
          "bias_v1", result.get("bias_v1"), "bias_v2", result.get("bias_v2"))


if __name__ == "__main__":
    main()
