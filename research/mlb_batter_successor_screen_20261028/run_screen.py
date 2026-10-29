"""MLB_BATTER_RATES_V1 — historical design screen (one run, declared config).

Executes DESIGN.md in this packet against the SmartStake MLB player-props
dataset admitted by PR #2888 (DESIGN/SCREEN ONLY; no validation credit, no
clock credit, no play eligibility; market comparisons are "vs-close
(timestamped, per book)", never verified CLV).

Configuration is frozen by DESIGN.md: shrinkage K=20, fit window
2026-03-21..2026-05-31, validation window 2026-06-01..2026-07-05 (graded
rows only — the source grades no July games), DraftKings close, main-line
rule, cluster bootstrap by game (2,000 reps, seed 20261028).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

CONSTRUCTION = "MLB_BATTER_RATES_V1"
SOURCE_REVISION = "7cedfd3fe29f2de4f675039410a48160739323fc"
CLOSE_BOOK = "draftkings"
MARKETS = [
    "player bases",
    "player hits",
    "player rbis",
    "player home runs",
    "player strikeouts",
    "player batting walks",
]
SHRINKAGE_K = 20.0
PHI_CAP = 2.5
PHI_POISSON_THRESHOLD = 1.02
MIN_N = 300
CALIBRATION_BOUND = 0.04
BOOTSTRAP_REPS = 2000
SEED = 20261028
FIT_START = pd.Timestamp("2026-03-21")
FIT_END = pd.Timestamp("2026-06-01")
VAL_END = pd.Timestamp("2026-07-06")
EPS = 1e-9
QUOTE_COLUMNS = ["game_id", "start_time", "player", "market", "line",
                 "side", "ts", "odds", "result"]


# --------------------------------------------------------------------------
# Pure helpers (unit-tested)
# --------------------------------------------------------------------------

def devig_over(odds_over: float, odds_under: float) -> float:
    """De-vigged over probability from a decimal-odds over/under pair."""
    q_over = 1.0 / odds_over
    q_under = 1.0 / odds_under
    return q_over / (q_over + q_under)


def shrunk_rate(prior_sum: float, prior_n: float, mu: float,
                k: float = SHRINKAGE_K) -> float:
    """Player rate shrunk toward the league mean with prior weight k."""
    return (prior_sum + k * mu) / (prior_n + k)


def count_sf(lam: float, phi: float, line: float) -> float:
    """P(X > line) for a Poisson / negative-binomial count law.

    Mean ``lam``; variance ``phi * lam`` (phi <= PHI_POISSON_THRESHOLD is
    treated as Poisson). Computed by PMF recurrence up to floor(line);
    the counts and lines in this family are small, so this is exact and
    stable. Push mass (integer line) is NOT carved out here — callers
    handle pushes before scoring.
    """
    k_max = int(math.floor(line))
    if k_max < 0:
        return 1.0
    if lam <= 0:
        return 0.0
    if phi <= PHI_POISSON_THRESHOLD:
        pmf = math.exp(-lam)
        cdf = pmf
        for k in range(1, k_max + 1):
            pmf *= lam / k
            cdf += pmf
    else:
        r = lam / (phi - 1.0)
        p = r / (r + lam)
        pmf = p ** r
        cdf = pmf
        q = 1.0 - p
        for k in range(1, k_max + 1):
            pmf *= (k - 1 + r) / k * q
            cdf += pmf
    return min(1.0, max(0.0, 1.0 - cdf))


def select_main_line(lines: pd.DataFrame) -> pd.DataFrame:
    """Apply the DESIGN §2 main-line rule.

    Input: one row per (game_id, player, market, line) with columns
    n_quotes (over+under quote rows), p_over_close (de-vigged close).
    Rule: most quotes; tie -> de-vigged close closest to 0.50; then the
    lower line. Returns one row per (game_id, player, market).
    """
    df = lines.copy()
    df["_balance"] = (df["p_over_close"] - 0.5).abs()
    df = df.sort_values(
        ["game_id", "player", "market", "n_quotes", "_balance", "line"],
        ascending=[True, True, True, False, True, True],
        kind="mergesort",
    )
    out = df.drop_duplicates(["game_id", "player", "market"], keep="first")
    return out.drop(columns=["_balance"])


def log_loss(p: np.ndarray, y: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPS, 1.0 - EPS)
    return -(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))


def cluster_bootstrap_ci(games: np.ndarray, delta_sum: np.ndarray,
                         n_sel: np.ndarray, reps: int = BOOTSTRAP_REPS,
                         seed: int = SEED) -> tuple[float, float, float]:
    """Mean per-selection delta with a game-cluster bootstrap 95% CI.

    games/delta_sum/n_sel are per-game aggregates. Returns
    (point_estimate, ci_low, ci_high) for the selection-weighted mean.
    """
    rng = np.random.default_rng(seed)
    g = len(games)
    point = float(delta_sum.sum() / n_sel.sum())
    idx = rng.integers(0, g, size=(reps, g))
    sums = delta_sum[idx].sum(axis=1)
    ns = n_sel[idx].sum(axis=1)
    means = sums / ns
    lo, hi = np.percentile(means, [2.5, 97.5])
    return point, float(lo), float(hi)


def verdict_rule(market_rows: list[dict]) -> str:
    """DESIGN §7 verdict rule, applied in order."""
    any_fail = any(
        r["n"] >= MIN_N and not (
            r["c2_vs_market_pass"] and r["c3_vs_simple_pass"]
            and r["c4_calibration_pass"]
        )
        for r in market_rows
    )
    if any_fail:
        return "FAILED_SCREEN"
    if any(r["n"] < MIN_N for r in market_rows):
        return "NOT_EXECUTABLE"
    return "DESIGN_PASS"


# --------------------------------------------------------------------------
# Data build (pin-verified staged partitions)
# --------------------------------------------------------------------------

def verify_pins(pulls_dir: Path, manifest_path: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text())
    checked = []
    for part in manifest["partitions"]:
        f = pulls_dir / part["path"]
        if not f.exists():
            raise FileNotFoundError(f"staged partition missing: {f}")
        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                h.update(chunk)
        digest = h.hexdigest()
        if digest != part["sha256"] or f.stat().st_size != part["bytes"]:
            raise ValueError(f"PIN MISMATCH on {part['path']}")
        checked.append({"path": part["path"], "sha256": digest,
                        "pin_status": "PIN_MATCH"})
    return checked


def build_frames(pulls_dir: Path, manifest_path: Path):
    """Return (appearances, line_closes, dk_rows_scanned).

    appearances: one row per (game_id, player, market) with start_time and
    result (result constant per group per the admission's join proof).
    line_closes: one row per (game_id, player, market, line) with closing
    decimal odds per side and total quote count.
    """
    import pyarrow.parquet as pq

    manifest = json.loads(manifest_path.read_text())
    app_parts, close_parts = [], []
    dk_rows = 0
    for part in manifest["partitions"]:
        f = pulls_dir / part["path"]
        table = pq.read_table(f, columns=QUOTE_COLUMNS,
                              filters=[("book", "=", CLOSE_BOOK)])
        df = table.to_pandas()
        dk_rows += len(df)
        app_parts.append(
            df[["game_id", "start_time", "player", "market", "result"]]
            .drop_duplicates(["game_id", "player", "market"])
        )
        ordered = df.sort_values("ts", kind="mergesort")
        last = ordered.drop_duplicates(
            ["game_id", "player", "market", "line", "side"], keep="last")
        closes = last[["game_id", "player", "market", "line", "side",
                       "odds", "ts"]].copy()
        counts = (df.groupby(["game_id", "player", "market", "line", "side"])
                  .size().rename("n_side").reset_index())
        closes = closes.merge(counts, on=["game_id", "player", "market",
                                          "line", "side"], how="left")
        close_parts.append(closes)
        del df, ordered, last

    appearances = (pd.concat(app_parts, ignore_index=True)
                   .drop_duplicates(["game_id", "player", "market"]))
    all_closes = pd.concat(close_parts, ignore_index=True)
    # Resolve across partitions: latest ts wins per side; quote counts add.
    all_closes = all_closes.sort_values("ts", kind="mergesort")
    side_close = all_closes.drop_duplicates(
        ["game_id", "player", "market", "line", "side"], keep="last")
    counts = (all_closes.groupby(["game_id", "player", "market", "line"])
              .agg(n_quotes=("n_side", "sum")).reset_index())
    wide = side_close.pivot_table(
        index=["game_id", "player", "market", "line"],
        columns="side", values="odds", aggfunc="first").reset_index()
    wide = wide.rename(columns={"over": "odds_over", "under": "odds_under"})
    line_closes = wide.merge(counts, on=["game_id", "player", "market",
                                         "line"], how="left")
    return appearances, line_closes, dk_rows


# --------------------------------------------------------------------------
# Screen
# --------------------------------------------------------------------------

def fit_league_constants(appearances: pd.DataFrame) -> dict:
    fit = appearances[
        (appearances["start_time"] >= FIT_START)
        & (appearances["start_time"] < FIT_END)
        & appearances["result"].notna()
    ]
    params = {}
    for market in MARKETS:
        vals = fit.loc[fit["market"] == market, "result"].to_numpy(float)
        mu = float(vals.mean())
        var = float(vals.var(ddof=1)) if len(vals) > 1 else mu
        phi = min(PHI_CAP, max(1.0, var / mu)) if mu > 0 else 1.0
        params[market] = {"mu": mu, "phi": float(phi), "fit_n": int(len(vals))}
    return params


def add_prior_features(appearances: pd.DataFrame) -> pd.DataFrame:
    """Expanding strictly-prior (sum, n) of graded results per player/market."""
    graded = appearances[appearances["result"].notna()].copy()
    graded = graded.sort_values(["player", "market", "start_time", "game_id"],
                                kind="mergesort")
    g = graded.groupby(["player", "market"], sort=False)["result"]
    graded["prior_sum"] = g.cumsum() - graded["result"]
    graded["prior_n"] = g.cumcount().astype(float)
    return graded


def run_screen(pulls_dir: Path, manifest_path: Path) -> dict:
    pins = verify_pins(pulls_dir, manifest_path)
    appearances, line_closes, dk_rows = build_frames(pulls_dir, manifest_path)
    params = fit_league_constants(appearances)
    graded = add_prior_features(appearances)

    val = graded[(graded["start_time"] >= FIT_END)
                 & (graded["start_time"] < VAL_END)].copy()
    lines = line_closes.dropna(subset=["odds_over", "odds_under"]).copy()
    lines["p_over_close"] = [devig_over(o, u) for o, u in
                             zip(lines["odds_over"], lines["odds_under"])]
    main = select_main_line(lines)
    ev = val.merge(main[["game_id", "player", "market", "line",
                         "odds_over", "odds_under", "p_over_close"]],
                   on=["game_id", "player", "market"], how="inner")
    n_no_close = int(len(val) - len(ev))
    ev["push"] = (ev["result"] == ev["line"])
    n_push = int(ev["push"].sum())
    ev = ev[~ev["push"]].copy()
    ev["y"] = (ev["result"] > ev["line"]).astype(float)

    def _model_p(row):
        prm = params[row["market"]]
        lam = shrunk_rate(row["prior_sum"], row["prior_n"], prm["mu"])
        return count_sf(lam, prm["phi"], row["line"])

    def _simple_p(row):
        prm = params[row["market"]]
        return count_sf(prm["mu"], prm["phi"], row["line"])

    ev["p_model"] = [_model_p(r) for _, r in ev.iterrows()]
    ev["p_simple"] = [_simple_p(r) for _, r in ev.iterrows()]
    ev["p_market"] = ev["p_over_close"]
    ev["ll_model"] = log_loss(ev["p_model"].to_numpy(), ev["y"].to_numpy())
    ev["ll_simple"] = log_loss(ev["p_simple"].to_numpy(), ev["y"].to_numpy())
    ev["ll_market"] = log_loss(ev["p_market"].to_numpy(), ev["y"].to_numpy())
    ev["dll_vs_market"] = ev["ll_model"] - ev["ll_market"]
    ev["dll_vs_simple"] = ev["ll_model"] - ev["ll_simple"]

    market_rows = []
    for market in MARKETS:
        sub = ev[ev["market"] == market]
        n = int(len(sub))
        row = {"market": market, "n": n,
               "fit": params[market],
               "strikeouts_population": (
                   "pitcher (DraftKings posts this market on pitchers; "
                   "DESIGN §2)" if market == "player strikeouts" else
                   "batter")}
        if n > 0:
            agg = sub.groupby("game_id").agg(
                s_mkt=("dll_vs_market", "sum"),
                s_smp=("dll_vs_simple", "sum"),
                n=("dll_vs_market", "size")).reset_index()
            d_mkt = cluster_bootstrap_ci(agg["game_id"].to_numpy(),
                                         agg["s_mkt"].to_numpy(float),
                                         agg["n"].to_numpy(float))
            d_smp = cluster_bootstrap_ci(agg["game_id"].to_numpy(),
                                         agg["s_smp"].to_numpy(float),
                                         agg["n"].to_numpy(float))
            row.update({
                "observed_over_rate": float(sub["y"].mean()),
                "mean_p_model": float(sub["p_model"].mean()),
                "calibration_diff": float(sub["p_model"].mean()
                                          - sub["y"].mean()),
                "logloss_model": float(sub["ll_model"].mean()),
                "logloss_market_close": float(sub["ll_market"].mean()),
                "logloss_simple": float(sub["ll_simple"].mean()),
                "brier_model": float(((sub["p_model"] - sub["y"]) ** 2).mean()),
                "brier_market_close": float(((sub["p_market"] - sub["y"]) ** 2).mean()),
                "brier_simple": float(((sub["p_simple"] - sub["y"]) ** 2).mean()),
                "delta_logloss_vs_market": d_mkt[0],
                "delta_logloss_vs_market_ci": [d_mkt[1], d_mkt[2]],
                "delta_logloss_vs_simple": d_smp[0],
                "delta_logloss_vs_simple_ci": [d_smp[1], d_smp[2]],
                "distinct_games": int(sub["game_id"].nunique()),
            })
        row["c1_min_n_pass"] = n >= MIN_N
        row["c2_vs_market_pass"] = bool(
            n > 0 and row.get("delta_logloss_vs_market_ci", [0, 1])[1] < 0)
        row["c3_vs_simple_pass"] = bool(
            n > 0 and row.get("delta_logloss_vs_simple_ci", [0, 1])[1] < 0)
        row["c4_calibration_pass"] = bool(
            n > 0 and abs(row.get("calibration_diff", 1.0)) <= CALIBRATION_BOUND)
        market_rows.append(row)

    results = {
        "construction": CONSTRUCTION,
        "design": "research/mlb_batter_successor_screen_20261028/DESIGN.md",
        "source": {
            "dataset": "SmartStake/mlb-player-props (Hugging Face)",
            "revision": SOURCE_REVISION,
            "admission": "PR #2888 — ADMITTED DESIGN/SCREEN ONLY",
            "labels": "vs-close (timestamped, per book); no validation "
                      "credit, no clock credit, no play eligibility",
            "attribution": "CC BY 4.0 — SmartStake",
        },
        "pins_verified": pins,
        "config": {
            "shrinkage_k": SHRINKAGE_K, "phi_cap": PHI_CAP,
            "min_n": MIN_N, "calibration_bound": CALIBRATION_BOUND,
            "bootstrap_reps": BOOTSTRAP_REPS, "seed": SEED,
            "fit_window": [str(FIT_START.date()), str(FIT_END.date())],
            "validation_window": [str(FIT_END.date()), str(VAL_END.date())],
            "close_book": CLOSE_BOOK,
        },
        "data_used": {
            "draftkings_rows_scanned": int(dk_rows),
            "appearances_graded_total": int(appearances["result"].notna().sum()),
            "validation_selections_scored": int(len(ev)),
            "validation_graded_without_two_sided_close": n_no_close,
            "validation_pushes_excluded": n_push,
            "validation_distinct_games": int(ev["game_id"].nunique()),
        },
        "markets": market_rows,
        "verdict": verdict_rule(market_rows),
    }
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pulls-dir", type=Path,
                    default=Path.home() / "workspace"
                    / "smartstake_admission_20261028" / "pulls")
    ap.add_argument("--manifest", type=Path,
                    default=Path(__file__).resolve().parents[1]
                    / "mlb_smartstake_props_admission_20261028"
                    / "admission_manifest.json")
    ap.add_argument("--out", type=Path,
                    default=Path(__file__).resolve().parent
                    / "screen_results.json")
    args = ap.parse_args()
    results = run_screen(args.pulls_dir, args.manifest)
    args.out.write_text(json.dumps(results, indent=1))
    print(json.dumps({"verdict": results["verdict"],
                      "data_used": results["data_used"]}, indent=1))


if __name__ == "__main__":
    main()
