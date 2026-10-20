"""NFL props Part 2B — forward-test scoring (PREREG_NFL_PROPS_PART2B_FORWARD_V1.md §2–§4).

Scores committed priced runs (price_nfl_props_part2b.py output) against
realized nflverse outcomes. Mirrors the Part 2 readout with the 2B rules:
  * verdict gates are §4 AS RULED 2026-10-20 (option (a)): no market-
    specific row floor — a market needs >= 100 graded rows,
    >= 4 full slates, and exactly >= 40 distinct games before review;
    there is NO 50-row market gate (that was Part 2's passing-yards rule);
  * CLV (no-vig) is the primary verdict basis with game-clustered
    bootstrap CIs via the evaluator's own boot(); win/loss secondary;
    >20% CLV_MISSING in a market is INSUFFICIENT_CLOSE_DATA;
  * §3 QB-clustered sensitivity: PASS_ATTEMPTS and COMPLETIONS readouts
    also report CLV with intervals clustered by QB (player_id). If the
    two clusterings disagree on the verdict, the market's verdict is the
    WEAKER of the two reads and the disagreement is stated;
  * PASS_TDS is SHADOW (§1): its rows are scored onto the record only
    and never enter any market aggregate, sample count, or verdict.

Usage:
  python3 score_nfl_props_part2b.py --run-dir DIR [--run-dir DIR ...]
      --outcomes FILE --slates-completed N --out FILE

Outcomes JSON: {"results": [{"player_id": "...", "market": "PASS_ATTEMPTS",
                              "value": 34.0}, ...]}
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
from price_nfl_props_part2b import load_evaluator  # noqa: E402  (hash-verified import)

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


def market_verdict(*, slates_completed: int, graded_rows: int,
                   distinct_games: int, clv_missing_share: float,
                   clv_ci_lo_game: float | None,
                   clv_ci_lo_qb: float | None) -> tuple[str, str | None]:
    """2B verdict gates (prereg §4 as ruled 2026-10-20, option (a)), in
    order. Returns (verdict, disagreement_note)."""
    if graded_rows < 100:
        return "INSUFFICIENT_SAMPLE", None
    if slates_completed < 4 or distinct_games < 40:
        return "REVIEW_NOT_OPEN", None
    if clv_missing_share > 0.20:
        return "INSUFFICIENT_CLOSE_DATA", None
    game_beats = clv_ci_lo_game is not None and clv_ci_lo_game > 0
    qb_beats = clv_ci_lo_qb is None or clv_ci_lo_qb > 0
    if game_beats and not qb_beats:
        # §3: a verdict may not rest on treating one busy QB's repeated
        # rows as independent evidence — report the weaker read.
        return ("DOES_NOT_BEAT_MARKET",
                "QB_CLUSTERED_CI_INCLUDES_ZERO_WHILE_GAME_CLUSTERED_CI_POSITIVE")
    if game_beats and qb_beats:
        return "BEATS_MARKET", None
    return "DOES_NOT_BEAT_MARKET", None


def aggregate_market(ev, rows: list, *, slates_completed: int) -> dict:
    graded = [r for r in rows if r.get("outcome") is not None]
    clv_rows = [r for r in graded if r.get("clv") is not None]
    missing = [r for r in graded if r.get("close_status") == "CLV_MISSING"]
    n = len(graded)
    share_missing = (len(missing) / n) if n else 0.0
    clv_stats = None
    if clv_rows:
        clv_stats = ev.boot([r["clv"] for r in clv_rows],
                            [r["game_id"] for r in clv_rows])  # clustered by game
    market = rows[0]["market"] if rows else None
    clv_qb_stats = None
    if market in ("PASS_ATTEMPTS", "COMPLETIONS") and clv_rows:
        # §3 sensitivity: the same CLV values, intervals clustered by QB.
        clv_qb_stats = ev.boot([r["clv"] for r in clv_rows],
                               [r["player_id"] for r in clv_rows])
    wins = sum(1 for r in graded if r.get("selected_result") == "WIN")
    losses = sum(1 for r in graded if r.get("selected_result") == "LOSS")
    pushes = sum(1 for r in graded if r["outcome"] == "PUSH")
    ll = [r for r in graded if r.get("logloss_model") is not None]
    verdict, disagreement = market_verdict(
        slates_completed=slates_completed,
        graded_rows=n,
        distinct_games=len({r["game_id"] for r in graded}),
        clv_missing_share=share_missing,
        clv_ci_lo_game=(clv_stats["ci95_lo"] if clv_stats else None),
        clv_ci_lo_qb=(clv_qb_stats["ci95_lo"] if clv_qb_stats else None),
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
        "clv_qb_clustered": ({"mean": clv_qb_stats["mean"],
                              "ci95_lo": clv_qb_stats["ci95_lo"],
                              "ci95_hi": clv_qb_stats["ci95_hi"],
                              "n": clv_qb_stats["n"],
                              "n_qbs_clustered": clv_qb_stats["n_blocks"]}
                             if clv_qb_stats else None),
        "verdict_cluster_disagreement": disagreement,
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
    shadow_scored: list = []
    unscored: list = []
    for run_dir in run_dirs:
        payload = json.loads((run_dir / "priced_rows.json").read_text())
        pools = json.loads((run_dir / "pools.json").read_text())
        for row in payload["rows"]:
            if row["status"] != "PRICED":
                continue
            key = (row["player_id"], row["market"])
            if ev.MARKETS[row["market"]].get("shadow"):
                # §1 SHADOW: scored onto the record, never aggregated.
                if key not in realized:
                    continue
                full = score_row(ev, row, pools[row["market"]], realized[key], grid)
                shadow_scored.append({
                    "row_id": row["row_id"], "market": row["market"],
                    "label": "SHADOW", "realized_value": full["realized_value"],
                    "outcome": full["outcome"], "p_over": row["p_over"],
                })
                continue
            if key not in realized:
                unscored.append(row["row_id"])
                continue
            scored.append(score_row(ev, row, pools[row["market"]], realized[key], grid))
    return scored, {"unscored_priced_rows": unscored,
                    "shadow_rows_scored_for_record": shadow_scored}


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
    readout = {
        "label": "NFL PROPS PART 2B FORWARD TEST — readout (frozen prereg §4)",
        "slates_completed": args.slates_completed,
        "markets": {},
        "shadow_pass_tds": {
            "n_scored_for_record": len(notes["shadow_rows_scored_for_record"]),
            "rows": notes["shadow_rows_scored_for_record"],
            "note": "SHADOW (§1): recorded only — excluded from every market "
                    "aggregate, sample threshold, and verdict.",
        },
        "unscored_priced_rows": notes["unscored_priced_rows"],
    }
    for market, cfg in ev.MARKETS.items():
        if cfg.get("shadow"):
            continue
        readout["markets"][market] = aggregate_market(
            ev, [r for r in scored if r["market"] == market],
            slates_completed=args.slates_completed)
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
