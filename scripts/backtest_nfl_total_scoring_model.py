"""Chronological OOS backtest for the NFL total scoring-rate model (Lane 2).

Input: nflverse/nfldata games.csv (free, public). Train/fit 2012-2020, test
2021+ regular season with a closing total. Writes the committed receipt.
Usage: python3 scripts/backtest_nfl_total_scoring_model.py games.csv
"""
import csv, hashlib, itertools, json, math, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sportsedge.sports.nfl import total_scoring_model as m  # noqa: E402

TRAIN = list(range(2012, 2021))


def load(path):
    rows = []
    for r in csv.DictReader(open(path)):
        s = int(r["season"])
        if s < 2012 or r["game_type"] != "REG":
            continue
        f = lambda k: float(r[k]) if r[k] not in ("", "NA") else None
        rows.append({"season": s, "week": int(r["week"]), "gameday": r["gameday"],
                     "gametime": r["gametime"], "home_team": r["home_team"],
                     "away_team": r["away_team"], "home_score": f("home_score"),
                     "away_score": f("away_score"), "roof": r["roof"], "wind": f("wind"),
                     "total_line": f("total_line"), "over_odds": f("over_odds"),
                     "under_odds": f("under_odds")})
    rows.sort(key=lambda g: (g["gameday"], g["gametime"], g["home_team"]))
    return rows


def imp(o):
    return 100 / (o + 100) if o > 0 else -o / (-o + 100)


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(c - h, 4), round(c + h, 4)]


def boot(x, B=2000, seed=7):
    rnd = random.Random(seed); n = len(x); ms = []
    for _ in range(B):
        ms.append(sum(x[rnd.randrange(n)] for _ in range(n)) / n)
    ms.sort()
    return [round(ms[int(.025 * B)], 5), round(ms[int(.975 * B)], 5)]


def evaluate(preds, seasons, sigma):
    rec = []
    for p in preds:
        if p["season"] not in seasons or p["home_score"] is None or p["total_line"] is None:
            continue
        actual = p["home_score"] + p["away_score"]; L = p["total_line"]
        if actual == L:
            continue
        pr = m.total_probabilities(p["proj_total"], L, sigma)
        pm = pr["p_over"] / (pr["p_over"] + pr["p_under"])
        if p["over_odds"] and p["under_odds"]:
            io, iu = imp(p["over_odds"]), imp(p["under_odds"]); qm = io / (io + iu)
        else:
            qm = 0.5
        y = 1.0 if actual > L else 0.0
        rec.append({"y": y, "pm": pm, "qm": qm, "proj": p["proj_total"], "L": L, "act": actual})
    return rec


def main(path):
    games = load(path)
    best = None
    for k, carry, kmu in itertools.product([0.04, 0.06, 0.08, 0.1, 0.12], [0.4, 0.6, 0.8], [0.005, 0.01, 0.02]):
        prm = dict(m.DEFAULT_PARAMS, k=k, carry=carry, k_mu=kmu)
        pr = [p for p in m.walk_forward(games, prm) if p["season"] in TRAIN[2:] and p["home_score"] is not None]
        mse = sum((p["home_score"] + p["away_score"] - p["proj_total"]) ** 2 for p in pr) / len(pr)
        if best is None or mse < best[0]:
            best = (mse, prm)
    prm = best[1]
    preds = m.walk_forward(games, prm)
    tr = [p for p in preds if p["season"] in TRAIN[2:] and p["home_score"] is not None]
    res = [p["home_score"] + p["away_score"] - p["proj_total"] for p in tr]
    prm["sigma"] = round(math.sqrt(sum(r * r for r in res) / len(res)), 3)
    test_seasons = sorted({p["season"] for p in preds if p["season"] > 2020})
    rec = evaluate(preds, set(test_seasons), prm["sigma"])
    n = len(rec)
    bd = [(r["pm"] - r["y"]) ** 2 - (r["qm"] - r["y"]) ** 2 for r in rec]
    md = [abs(r["proj"] - r["act"]) - abs(r["L"] - r["act"]) for r in rec]
    ll = lambda p, y: -(y * math.log(p) + (1 - y) * math.log(1 - p))
    picks = [r for r in rec if abs(r["proj"] - r["L"]) >= 0.5]
    hits = sum(1 for r in picks if (r["proj"] > r["L"]) == (r["y"] == 1))
    big = [r for r in rec if abs(r["proj"] - r["L"]) >= 3]
    bh = sum(1 for r in big if (r["proj"] > r["L"]) == (r["y"] == 1))
    evs = [max(r["pm"], 1 - r["pm"]) * (1 + 100 / 110) - 1 for r in rec]
    cal = []
    srt = sorted(rec, key=lambda r: r["pm"])
    for i in range(10):
        b = srt[i * n // 10:(i + 1) * n // 10]
        cal.append(round(sum(r["y"] for r in b) / len(b) - sum(r["pm"] for r in b) / len(b), 4))
    ci = boot(bd)
    out = {
        "model_id": m.MODEL_ID, "data_source": "nflverse/nfldata data/games.csv (free public)",
        "data_sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(),
        "train_seasons": TRAIN, "test_seasons": test_seasons,
        "fit_params": prm, "fit_note": "grid on 2014-2020 total MSE; 2012-13 burn-in; sigma from train residuals",
        "n_test": n, "pushes_excluded": True,
        "brier_model": round(sum((r["pm"] - r["y"]) ** 2 for r in rec) / n, 5),
        "brier_market": round(sum((r["qm"] - r["y"]) ** 2 for r in rec) / n, 5),
        "brier_diff_mean": round(sum(bd) / n, 5), "brier_diff_ci95": ci,
        "logloss_model": round(sum(ll(r["pm"], r["y"]) for r in rec) / n, 5),
        "logloss_market": round(sum(ll(r["qm"], r["y"]) for r in rec) / n, 5),
        "mae_model": round(sum(abs(r["proj"] - r["act"]) for r in rec) / n, 3),
        "mae_closing_total": round(sum(abs(r["L"] - r["act"]) for r in rec) / n, 3),
        "mae_diff_mean": round(sum(md) / n, 3), "mae_diff_ci95": boot(md),
        "ou_hit_rate_gap_ge_0_5": {"n": len(picks), "hits": hits, "rate": round(hits / len(picks), 4), "wilson95": wilson(hits, len(picks))},
        "ou_hit_rate_gap_ge_3": {"n": len(big), "hits": bh, "rate": round(bh / max(1, len(big)), 4), "wilson95": wilson(bh, len(big))},
        "calibration_obs_minus_pred_by_decile": cal,
        "max_abs_ev_at_minus110_raw_model": round(max(evs), 4),
        "passes": bool(ci[1] < 0 and n >= m.MIN_TEST_N),
        "research_only": True,
    }
    m.RECEIPT_PATH.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
