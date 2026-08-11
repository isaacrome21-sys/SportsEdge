#!/usr/bin/env python3
"""Run the authoritative full Hits production-engine holdout.

The historical fixture is intentionally external until fixture portability is
solved. This command refuses to run against bytes other than the frozen fixture
hash and refuses promotion on identity collision or calibration > 2.63 SE.
"""
import argparse
import hashlib
import pickle
from pathlib import Path

import numpy as np

from sportsedge.hits_engine import (
    FROZEN_MEAN_MODEL_COEF,
    reset_frozen_mean_model,
    set_frozen_mean_model,
    simulate_hits,
)

EXPECTED_FIXTURE_SHA256 = "8c15e196efa5fc7ef979d0a9cf5ec113cba54cd756482babc256c44d53642409"
FROZEN_TOLERANCE_SE = 2.63


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("fixture", type=Path, help="path to frozen bb_hits_data.pkl")
    args = p.parse_args()
    raw = args.fixture.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_FIXTURE_SHA256:
        raise SystemExit(f"fixture hash mismatch: {digest}")

    data = pickle.loads(raw)
    train = [x for x in data["dataset"] if x["season"] in ("2021", "2022")]
    holdout = [x for x in data["dataset"] if x["season"] in ("2023", "2024")]
    if len(holdout) != 83769:
        raise SystemExit(f"unexpected holdout row count: {len(holdout)}")

    X = np.column_stack([
        np.ones(len(train)),
        [x["b_rate"] for x in train],
        [x["p_rate"] for x in train],
    ])
    y = np.array([x["actual_h"] / max(x["actual_pa"], 1) for x in train])
    w = np.array([max(x["actual_pa"], 1) for x in train], dtype=float)
    coef, *_ = np.linalg.lstsq(X * np.sqrt(w)[:, None], y * np.sqrt(w), rcond=None)
    if not np.allclose(coef, FROZEN_MEAN_MODEL_COEF, rtol=0, atol=1e-12):
        raise SystemExit(f"frozen coefficient mismatch: fit={tuple(coef)} frozen={FROZEN_MEAN_MODEL_COEF}")
    set_frozen_mean_model(tuple(coef))

    thresholds = (0.5, 1.5, 2.5)
    pred = {t: [] for t in thresholds}
    actual = {t: [] for t in thresholds}
    seen = set()
    try:
        for g in holdout:
            identity_fields = {
                "market": "hits",
                "season": g["season"],
                "date": g.get("date", ""),
                "line": 0.5,
                "side": "over",
                "b_rate": round(g["b_rate"], 12),
                "p_rate": round(g["p_rate"], 12),
                "actual_pa": g["actual_pa"],
                "pa_pool_hash": hashlib.sha256(str(g["pa_pool"]).encode()).hexdigest(),
            }
            identity_key = "|".join(f"{k}={v}" for k, v in sorted(identity_fields.items()))
            build_hash = hashlib.sha256(identity_key.encode()).hexdigest()
            if build_hash in seen:
                raise SystemExit("candidate identity collision in holdout")
            seen.add(build_hash)
            out = simulate_hits({
                "build_hash": build_hash,
                "market": "hits",
                "lineup_status": "CONFIRMED",
                "require_confirmed_lineup": False,
                "features": {"b_rate": g["b_rate"], "p_rate": g["p_rate"], "pa_pool": g["pa_pool"]},
            }, thresholds=thresholds, n_sim=2000)
            for t in thresholds:
                pred[t].append(out.probs[t])
                actual[t].append(1 if g["actual_h"] > t else 0)
    finally:
        reset_frozen_mean_model()

    worst = 0.0
    for t in thresholds:
        s = np.asarray(pred[t]); a = np.asarray(actual[t])
        gap_pp = abs(s.mean() - a.mean()) * 100
        se_pp = np.sqrt(a.mean() * (1 - a.mean()) / len(a)) * 100
        gap_se = gap_pp / se_pp
        worst = max(worst, gap_se)
        print(f"{t}: sim={s.mean():.4f} actual={a.mean():.4f} gap={gap_pp:.2f}pp ({gap_se:.2f} SE)")
    print(f"worst={worst:.2f} SE")
    if worst > FROZEN_TOLERANCE_SE:
        raise SystemExit(f"FAIL: {worst:.2f} SE > frozen {FROZEN_TOLERANCE_SE:.2f} SE")
    print("PASS: full 83,769-row production Hits holdout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
