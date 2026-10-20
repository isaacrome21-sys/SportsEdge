"""NFL props Part 2B calibration evaluator v1 (PREREG_NFL_PROPS_PART2B_FORWARD_V1.md).

The Part 1 calibration construction (eval_nfl_props_calibration_v1.py,
frozen with Part 2) copied verbatim and extended ONLY in:
  (a) load() also reads the nflverse columns "completions" and
      "passing_tds" (present in the same weekly files; the Part 1 loader
      did not read them);
  (b) MARKETS names the Part 2B markets. Each market reuses the role
      population of the frozen market whose volume it counts:
      PASS_ATTEMPTS counts the PASS_YDS role stat (attempts, mean prior
      attempts >= 20.0, QB only); COMPLETIONS is a sub-count of attempts
      under the same role gate; RUSH_ATTEMPTS counts the RUSH_YDS role
      stat (carries, mean prior carries >= 8.0); PASS_TDS is the
      SHADOW-only market (same QB role gate), priced and recorded,
      labeled SHADOW, never counted toward any verdict or threshold.
      All four are counting stats (count=True: Poisson / negative
      binomial predictive, the construction's own count path — the same
      path RECEPTIONS uses in Part 1).
Every construction function (qualified_rows / build / league_pool /
mu_for / candidate_cdf / emp_cdf / crps / boot) and every constant
(K = 3.0, TRAIN = (2018, 2019), grid) is byte-identical to Part 1.
RESEARCH_EVIDENCE only.

Usage: python eval_nfl_props_part2b_v1.py --data DIR --out results.json
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
K = 3.0
SEED, RESAMPLES = 20261017, 2000
TRAIN, SCORED = (2018, 2019), tuple(range(2020, 2026))
MARKETS = {
    "RUSH_ATTEMPTS": {"stat": "carries", "role": "carries", "thr": 8.0, "qb": False, "count": True},
    "PASS_ATTEMPTS": {"stat": "attempts", "role": "attempts", "thr": 20.0, "qb": True, "count": True},
    "COMPLETIONS": {"stat": "completions", "role": "attempts", "thr": 20.0, "qb": True, "count": True},
    "PASS_TDS": {"stat": "passing_tds", "role": "attempts", "thr": 20.0, "qb": True, "count": True,
                 "shadow": True},
}
GRID_LO, GRID_HI = -60, 700


def check_hashes(data: Path) -> dict:
    want = {}
    for line in (HERE / "SPEC_HASHES.txt").read_text().splitlines():
        h, name = line.split()
        want[name] = h
    got = hashlib.sha256((HERE / "PREREG_NFL_PROPS_PART2B_FORWARD_V1.md").read_bytes()).hexdigest()
    if got != want["PREREG_NFL_PROPS_PART2B_FORWARD_V1.md"]:
        raise SystemExit("prereg hash mismatch")
    for name, h in want.items():
        if name.endswith(".gz") and hashlib.sha256((data / name).read_bytes()).hexdigest() != h:
            raise SystemExit(f"data hash mismatch {name}")
    return want


def f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load(data: Path) -> dict:
    """{season: {pid: [(week, position, row)]}} regular season only."""
    out: dict = defaultdict(lambda: defaultdict(list))
    files = sorted(data.glob("ps_*.csv.gz")) + sorted(data.glob("sp_*.csv.gz"))
    for p in files:
        with gzip.open(p, "rt") as fh:
            for r in csv.DictReader(fh):
                if r.get("season_type") != "REG":
                    continue
                s, w = int(r["season"]), int(r["week"])
                row = {k: f(r.get(k)) for k in ("attempts", "completions", "passing_tds",
                                                "passing_yards", "carries", "rushing_yards",
                                                "targets", "receptions", "receiving_yards")}
                out[s][r["player_id"]].append((w, r.get("position") or "", row))
    for s in out:
        for pid in out[s]:
            out[s][pid].sort(key=lambda t: t[0])
    return out


def qualified_rows(season_data: dict, cfg: dict):
    """Yield (week, pid, prior_values, outcome) for role-qualified player-weeks."""
    for pid, games in season_data.items():
        for i, (w, pos, row) in enumerate(games):
            prior = games[:i]
            if len(prior) < 3:
                continue
            if cfg["qb"] and pos != "QB":
                continue
            if np.mean([g[2][cfg["role"]] for g in prior]) < cfg["thr"]:
                continue
            yield w, pid, [g[2][cfg["stat"]] for g in prior], row[cfg["stat"]]


def build(data: dict, cfg: dict) -> dict:
    """Per season: list of qualified rows plus per-week league pools."""
    seasons = {}
    for s in sorted(data):
        rows = sorted(qualified_rows(data[s], cfg), key=lambda t: (t[0], t[1]))
        seasons[s] = rows
    return seasons


def league_pool(seasons: dict, s: int, w: int):
    earlier = [y for (wk, _, _, y) in seasons.get(s, []) if wk < w]
    if earlier:
        return earlier
    return [y for (_, _, _, y) in seasons.get(s - 1, [])]


def mu_for(prior, pool):
    g = float(np.mean(pool))
    return (sum(prior) + K * g) / (len(prior) + K)


def candidate_cdf(mu, cv, count, grid):
    mu = max(mu, 1e-6)
    sd = cv * mu
    if count:
        var = sd * sd
        if var <= mu:
            return stats.poisson.cdf(grid, mu)
        r = mu * mu / (var - mu)
        return stats.nbinom.cdf(grid, r, r / (r + mu))
    shape = 1.0 / (cv * cv)
    return stats.gamma.cdf(grid, shape, scale=mu / shape)


def emp_cdf(values, grid):
    v = np.sort(np.asarray(values, float))
    return np.searchsorted(v, grid, side="right") / len(v)


def crps(cdf, y, grid):
    ind = (grid >= y).astype(float)
    return float(np.sum((cdf - ind) ** 2))


def boot(vals, blocks):
    vals = np.asarray(vals, float)
    keys = sorted(set(blocks))
    idx = {k: n for n, k in enumerate(keys)}
    bi = np.array([idx[b] for b in blocks])
    sums, cnts = np.zeros(len(keys)), np.zeros(len(keys))
    np.add.at(sums, bi, vals)
    np.add.at(cnts, bi, 1)
    rng = np.random.default_rng(SEED)
    s = rng.integers(0, len(keys), size=(RESAMPLES, len(keys)))
    m = sums[s].sum(1) / cnts[s].sum(1)
    lo, hi = np.percentile(m, [2.5, 97.5])
    return {"mean": float(vals.mean()), "ci95_lo": float(lo), "ci95_hi": float(hi),
            "n": int(len(vals)), "n_blocks": len(keys)}


def evaluate(data: dict) -> dict:
    grid = np.arange(GRID_LO, GRID_HI + 1, dtype=float)
    out = {}
    for name, cfg in MARKETS.items():
        seasons = build(data, cfg)
        # c_m from training seasons only
        ratios = []
        for s in TRAIN:
            for w, _, prior, y in seasons.get(s, []):
                pool = league_pool(seasons, s, w)
                if not pool:
                    continue
                ratios.append(y / max(mu_for(prior, pool), 1e-6))
        ratios = np.asarray(ratios)
        cv = float(ratios.std() / ratios.mean())
        rows = []
        for s in SCORED:
            for w, pid, prior, y in seasons.get(s, []):
                if w < 4:
                    continue
                pool = league_pool(seasons, s, w)
                mu = mu_for(prior, pool)
                c_c = candidate_cdf(mu, cv, cfg["count"], grid)
                c_b1, c_b2 = emp_cdf(prior, grid), emp_cdf(pool, grid)
                line = np.floor(np.median(prior)) + 0.5
                p_over = 1.0 - float(np.interp(line, grid, c_c)) if not cfg["count"] else \
                    1.0 - float(c_c[int(line - 0.5) - GRID_LO])
                pit = float(np.interp(y, grid, c_c))
                rows.append({"block": f"{s}-W{w:02d}", "season": s, "week": w, "pid": pid,
                             "y": y, "mu": mu, "crps_c": crps(c_c, y, grid),
                             "crps_b1": crps(c_b1, y, grid), "crps_b2": crps(c_b2, y, grid),
                             "p_over_line": p_over, "over": float(y > line), "pit": pit})
        blocks = [r["block"] for r in rows]
        res = {"n": len(rows), "cv_train": cv, "n_train_ratios": int(len(ratios)),
               "crps": {a: float(np.mean([r[k] for r in rows]))
                        for a, k in (("CANDIDATE", "crps_c"), ("B1", "crps_b1"), ("B2", "crps_b2"))},
               "delta_vs_B1": boot([r["crps_c"] - r["crps_b1"] for r in rows], blocks),
               "delta_vs_B2": boot([r["crps_c"] - r["crps_b2"] for r in rows], blocks)}
        res["shadow"] = bool(cfg.get("shadow"))
        res["verdict"] = ("CALIBRATED_CANDIDATE"
                          if res["delta_vs_B1"]["ci95_hi"] < 0 and res["delta_vs_B2"]["ci95_hi"] < 0
                          else "NOT_FORWARD_ELIGIBLE")
        res["pit_hist"] = np.histogram([r["pit"] for r in rows], bins=10, range=(0, 1))[0].tolist()
        order = sorted(rows, key=lambda r: r["p_over_line"])
        res["over_line_deciles"] = [
            {"mean_p_over": float(np.mean([r["p_over_line"] for r in part])),
             "realized_over": float(np.mean([r["over"] for r in part])), "n": len(part)}
            for part in (order[k * len(order) // 10:(k + 1) * len(order) // 10] for k in range(10))]
        out[name] = res
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    hashes = check_hashes(a.data)
    res = {"label": "RESEARCH_EVIDENCE (calibration only; no market prices) — Part 2B markets",
           "prereg_sha256": hashes["PREREG_NFL_PROPS_PART2B_FORWARD_V1.md"], "K": K,
           "results": evaluate(load(a.data))}
    a.out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n")
    for m, r in res["results"].items():
        print(m, r["verdict"], r["n"], {k: round(v, 3) for k, v in r["crps"].items()},
              "vsB1", [round(r["delta_vs_B1"][k], 3) for k in ("mean", "ci95_lo", "ci95_hi")],
              "vsB2", [round(r["delta_vs_B2"][k], 3) for k in ("mean", "ci95_lo", "ci95_hi")],
              "cv", round(r["cv_train"], 3))


if __name__ == "__main__":
    main()
