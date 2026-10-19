"""NFL props Part 2 — forward-test scoring (PREREG_NFL_PROPS_PART2_FORWARD_V1.md §3–§5).

Scores committed priced runs (price_nfl_props_part2.py output) against realized
nflverse outcomes. Implements the frozen readout: per-market rows / distinct
games / CLV_MISSING share, CLV (primary) with game-clustered bootstrap CI via
the evaluator's own boot(), win/loss (secondary), log loss vs the de-vigged DK
entry, CRPS vs the construction's B1/B2 baselines, calibration deciles incl.
the extreme decile, the #2388 stratified under-rate table, and the frozen
verdict gates (§4).

Usage:
  python3 score_nfl_props_part2.py --run-dir DIR [--run-dir DIR ...]
      --outcomes FILE --slates-completed N --out FILE

Outcomes JSON: {"results": [{"player_id": "...", "market": "PASS_YDS",
                              "value": 251.0}, ...]}
(one realized stat per priced player+market in the run being scored).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from price_nfl_props_part2 import load_evaluator  # noqa: E402  (hash-verified import)

EPS = 1e-12


def score_row(ev, row: dict, pool: list, value: float, grid) -> dict:
    line = row["line"]
    if value > line:
        outcome = "OVER"
    elif value < line:
        outcome = "UNDER"
    else:
        outcome = "PUSH"
    out = dict(row)
    out["realized_value"] = value
    out["outcome"] = outcome
    cfg_count = ev.MARKETS[row["market"]]["count"]
    cdf = ev.candidate_cdf(row["mu"], row["cv"], cfg_count, grid)
    out["crps_candidate"] = ev.crps(cdf, value, grid)
    out["crps_b1"] = ev.crps(ev.emp_cdf(row["prior_values"], grid), value, grid)
    out["crps_b2"] = ev.crps(ev.emp_cdf(pool, grid), value, grid)
    out["pit"] = float(np.interp(value, grid, cdf))
    sel = row["selected_side"]
    if outcome == "PUSH" or sel == "TIE":
        out["selected_result"] = None  # excluded from win/loss + CLV denominators
    else:
        out["selected_result"] = "WIN" if sel == outcome else "LOSS"
    if outcome != "PUSH":
        p_model = row["p_over"] if outcome == "OVER" else row["p_under"]
        p_dk = row["entry_novig_p_over"] if outcome == "OVER" else row["entry_novig_p_under"]
        out["logloss_model"] = float(-math.log(min(max(p_model, EPS), 1.0)))
        out["logloss_dk"] = float(-math.log(min(max(p_dk, EPS), 1.0)))
    else:
        out["logloss_model"] = None
        out["logloss_dk"] = None
    if row.get("close_status") == "READABLE" and sel in ("OVER", "UNDER"):
        close_p = row["close_novig_p_over"] if sel == "OVER" else row["close_novig_p_under"]
        entry_p = row["entry_novig_p_over"] if sel == "OVER" else row["entry_novig_p_under"]
        out["clv"] = float(close_p - entry_p)
    else:
        out["clv"] = None
    return out


def games_logged_bucket(n: int) -> str:
    if n <= 3:
        return "1-3"
    if n <= 5:
        return "4-5"
    if n <= 9:
        return "6-9"
    return "10+"


def shrink_bucket(w: float) -> str:
    if w >= 0.43:
        return "w>=0.43"
    if w >= 0.25:
        return "0.25<=w<0.43"
    return "w<0.25"


def under_rate(rows: list) -> dict:
    """#2388 under-rate over priced rows with a determinate selected side."""
    elig = [r for r in rows if r.get("selected_side") in ("OVER", "UNDER")]
    ties = sum(1 for r in rows if r.get("selected_side") == "TIE")

    def rate(sub: list) -> dict:
        if not sub:
            return {"n": 0, "under": 0, "under_rate": None}
        u = sum(1 for r in sub if r["selected_side"] == "UNDER")
        return {"n": len(sub), "under": u, "under_rate": u / len(sub)}

    by_games, by_shrink = {}, {}
    for b in ("1-3", "4-5", "6-9", "10+"):
        by_games[b] = rate([r for r in elig if games_logged_bucket(r["games_logged"]) == b])
    for b in ("w>=0.43", "0.25<=w<0.43", "w<0.25"):
        by_shrink[b] = rate([r for r in elig if shrink_bucket(r["shrink_weight"]) == b])
    return {"overall": rate(elig), "ties_excluded": ties,
            "by_games_logged": by_games, "by_shrink_weight": by_shrink}


def calibration_deciles(rows: list) -> list:
    """Part 1 convention: deciles of model P(over) vs realized over rate
    (pushes excluded). The last entry is the extreme (top) decile."""
    elig = [r for r in rows if r["outcome"] != "PUSH"]
    if not elig:
        return []
    order = sorted(elig, key=lambda r: r["p_over"])
    out = []
    for k in range(10):
        part = order[k * len(order) // 10:(k + 1) * len(order) // 10]
        if not part:
            continue
        out.append({"mean_p_over": float(np.mean([r["p_over"] for r in part])),
                    "realized_over": float(np.mean([1.0 if r["outcome"] == "OVER" else 0.0 for r in part])),
                    "n": len(part)})
    return out


def market_verdict(*, slates_completed: int, passing_graded_rows: int,
                   graded_rows: int, distinct_games: int,
                   clv_missing_share: float, clv_ci_lo: float | None) -> str:
    """Frozen verdict gates (prereg §4), in order."""
    if graded_rows < 100:
        return "INSUFFICIENT_SAMPLE"
    if slates_completed < 4 or passing_graded_rows < 50 or distinct_games < 40:
        return "REVIEW_NOT_OPEN"
    if clv_missing_share > 0.20:
        return "INSUFFICIENT_CLOSE_DATA"
    if clv_ci_lo is not None and clv_ci_lo > 0:
        return "BEATS_MARKET"
    return "DOES_NOT_BEAT_MARKET"


def aggregate_market(ev, rows: list, *, slates_completed: int,
                     passing_graded_rows: int) -> dict:
    graded = [r for r in rows if r.get("outcome") is not None]
    clv_rows = [r for r in graded if r.get("clv") is not None]
    missing = [r for r in graded if r.get("close_status") == "CLV_MISSING"]
    n = len(graded)
    share_missing = (len(missing) / n) if n else 0.0
    clv_stats = None
    if clv_rows:
        clv_stats = ev.boot([r["clv"] for r in clv_rows],
                            [r["game_id"] for r in clv_rows])  # clustered by game
    wins = sum(1 for r in graded if r.get("selected_result") == "WIN")
    losses = sum(1 for r in graded if r.get("selected_result") == "LOSS")
    pushes = sum(1 for r in graded if r["outcome"] == "PUSH")
    ll = [r for r in graded if r.get("logloss_model") is not None]
    verdict = market_verdict(
        slates_completed=slates_completed,
        passing_graded_rows=passing_graded_rows,
        graded_rows=n,
        distinct_games=len({r["game_id"] for r in graded}),
        clv_missing_share=share_missing,
        clv_ci_lo=(clv_stats["ci95_lo"] if clv_stats else None),
    )
    return {
        "graded_rows": n,
        "distinct_games": len({r["game_id"] for r in graded}),
        "clv_missing_rows": len(missing),
        "clv_missing_share": share_missing,
        "clv_missing_by_reason": {
            reason: sum(1 for r in missing
                        if (r.get("clv_missing_reason") or "UNSPECIFIED") == reason)
            for reason in sorted({r.get("clv_missing_reason") or "UNSPECIFIED" for r in missing})
        },
        "clv": ({"mean": clv_stats["mean"], "ci95_lo": clv_stats["ci95_lo"],
                 "ci95_hi": clv_stats["ci95_hi"], "n": clv_stats["n"],
                 "n_games_clustered": clv_stats["n_blocks"]} if clv_stats else None),
        "win_loss": {"wins": wins, "losses": losses, "pushes": pushes,
                     "win_rate_ex_pushes": (wins / (wins + losses)) if (wins + losses) else None},
        "logloss_model": (float(np.mean([r["logloss_model"] for r in ll])) if ll else None),
        "logloss_dk": (float(np.mean([r["logloss_dk"] for r in ll])) if ll else None),
        "crps_candidate": (float(np.mean([r["crps_candidate"] for r in graded])) if graded else None),
        "crps_b1": (float(np.mean([r["crps_b1"] for r in graded])) if graded else None),
        "crps_b2": (float(np.mean([r["crps_b2"] for r in graded])) if graded else None),
        "calibration_deciles": calibration_deciles(graded),
        "verdict": verdict,
    }


def score_runs(ev, run_dirs: list[Path], outcomes: dict) -> tuple[list, dict]:
    grid = np.arange(ev.GRID_LO, ev.GRID_HI + 1, dtype=float)
    realized = {(r["player_id"], r["market"]): float(r["value"]) for r in outcomes["results"]}
    scored: list = []
    unscored: list = []
    for run_dir in run_dirs:
        payload = json.loads((run_dir / "priced_rows.json").read_text())
        pools = json.loads((run_dir / "pools.json").read_text())
        for row in payload["rows"]:
            if row["status"] != "PRICED":
                continue
            key = (row["player_id"], row["market"])
            if key not in realized:
                unscored.append(row["row_id"])
                continue
            scored.append(score_row(ev, row, pools[row["market"]], realized[key], grid))
    return scored, {"unscored_priced_rows": unscored}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", action="append", required=True)
    ap.add_argument("--outcomes", required=True)
    ap.add_argument("--slates-completed", required=True, type=int)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    ev = load_evaluator()
    outcomes = json.loads(Path(args.outcomes).read_text())
    scored, notes = score_runs(ev, [Path(d) for d in args.run_dir], outcomes)
    passing_graded = sum(1 for r in scored if r["market"] == "PASS_YDS")
    readout = {
        "label": "NFL PROPS PART 2 FORWARD TEST — readout (frozen prereg §4.7)",
        "slates_completed": args.slates_completed,
        "passing_graded_rows": passing_graded,
        "markets": {},
        "under_rate_part2_sample": under_rate(scored),
        **notes,
    }
    for market in ev.MARKETS:
        readout["markets"][market] = aggregate_market(
            ev, [r for r in scored if r["market"] == market],
            slates_completed=args.slates_completed,
            passing_graded_rows=passing_graded)
    out_path = Path(args.out)
    if out_path.exists():
        raise SystemExit(f"REFUSING_TO_OVERWRITE_READOUT: {out_path}")
    out_path.write_text(json.dumps(readout, indent=1, sort_keys=True) + "\n")
    print(json.dumps({m: {"rows": v["graded_rows"], "verdict": v["verdict"],
                          "clv_missing_share": round(v["clv_missing_share"], 4)}
                      for m, v in readout["markets"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
