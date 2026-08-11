#!/usr/bin/env python3
"""Authoritative fixture-backed Total Bases production-engine holdout.

Every holdout row calls sportsedge.total_bases_engine.simulate_total_bases.
The reducer only sums integer/float candidate results; workers cannot change
identity, fixture, engine constants, or acceptance target.
"""
import argparse
import hashlib
import json
import multiprocessing as mp
import pickle
from pathlib import Path

import numpy as np

from sportsedge.total_bases_engine import TRAIN_PA_COUNTS, TRAIN_PA_POOL, TRAIN_SCALE, simulate_total_bases

EXPECTED_FIXTURE_SHA256 = "3abd596ae720529f5354f724c02c11e284a5044ac5842207599c27f4cb562e82"
EXPECTED_HOLDOUT_ROWS = 73036
FROZEN_REFERENCE_SE = 1.60
FROZEN_TOLERANCE_SE = 0.20
THRESHOLDS = (0.5, 1.5, 2.5)


def identity_hash(g: dict) -> str:
    payload = {
        "market": "TOTAL_BASES",
        "season": g["season"],
        "p_h": round(g["p_h"], 15),
        "p_hr": round(g["p_hr"], 15),
        "park": round(g["park"], 15),
        "rates": {k: round(g["rates"][k], 15) for k in ("s", "d", "t", "hr")},
        "pa_pool": [int(x) for x in g["pa_pool"]],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _score(item):
    build_hash, g = item
    out = simulate_total_bases({
        "build_hash": build_hash,
        "market": "total_bases",
        "lineup_status": "CONFIRMED",
        "require_confirmed_lineup": False,
        "features": {
            "rates": g["rates"], "p_h": g["p_h"], "p_hr": g["p_hr"],
            "park": g["park"], "pa_pool": g["pa_pool"],
        },
    }, thresholds=THRESHOLDS, n_sim=2000)
    return tuple(out.probs[t] for t in THRESHOLDS), tuple(int(g["actual_tb"] > t) for t in THRESHOLDS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--workers", type=int, default=max(1, min(8, mp.cpu_count())))
    args = parser.parse_args()
    if args.workers <= 0:
        raise SystemExit("workers must be positive")

    raw = args.fixture.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED_FIXTURE_SHA256:
        raise SystemExit(f"fixture hash mismatch: {digest}")
    data = pickle.loads(raw)
    dataset = data["dataset"]
    train = [x for x in dataset if x["season"] in ("2021", "2022")]
    holdout = [x for x in dataset if x["season"] in ("2023", "2024")]
    if len(holdout) != EXPECTED_HOLDOUT_ROWS:
        raise SystemExit(f"unexpected holdout rows: {len(holdout)}")

    source_pool = np.asarray(data["train_pa_pool"], dtype=np.int64)
    source_counts = {int(k): int((source_pool == k).sum()) for k in sorted(TRAIN_PA_COUNTS)}
    if source_counts != TRAIN_PA_COUNTS or len(source_pool) != len(TRAIN_PA_POOL):
        raise SystemExit(f"train PA multiset mismatch: {source_counts}")

    LG_PH=0.2258; AH=0.7; AHR=0.3; KP=0.5
    def scaled(x):
        ch=(x["p_h"]/LG_PH)**AH; chr_=(x["p_hr"]/0.03357)**AHR; pk=x["park"]**KP
        return np.array([x["rates"]["s"]*ch,x["rates"]["d"]*ch,x["rates"]["t"]*ch,x["rates"]["hr"]*chr_*pk])
    tr_pa=np.array([x["actual_pa"] for x in train],dtype=float)
    tr_tb=np.array([x["actual_tb"] for x in train],dtype=float)
    R=np.array([scaled(x) for x in train])
    fitted_scale=tr_tb.sum()/((R*np.array([1,2,3,4])).sum(axis=1)*tr_pa).sum()
    if abs(float(fitted_scale)-TRAIN_SCALE) > 1e-12:
        raise SystemExit(f"train-only scale mismatch: {fitted_scale} vs {TRAIN_SCALE}")

    identities = [identity_hash(g) for g in holdout]
    if len(set(identities)) != len(identities):
        raise SystemExit(f"candidate identity collisions: {len(identities)-len(set(identities))}")

    sums=np.zeros(3,dtype=float); actual=np.zeros(3,dtype=np.int64)
    with mp.Pool(args.workers) as pool:
        for probs, outcomes in pool.imap_unordered(_score, zip(identities, holdout), chunksize=100):
            sums += probs
            actual += outcomes

    n=len(holdout); worst=0.0
    for i,t in enumerate(THRESHOLDS):
        p=sums[i]/n; a=actual[i]/n
        gap=abs(p-a)*100.0
        se=np.sqrt(a*(1-a)/n)*100.0
        z=gap/se
        worst=max(worst,z)
        print(f"{t}: sim={p:.4f} actual={a:.4f} gap={gap:.2f}pp ({z:.2f} SE)")
    print(f"WORST: {worst:.2f} SE")
    if abs(worst-FROZEN_REFERENCE_SE) >= FROZEN_TOLERANCE_SE:
        raise SystemExit(f"FAIL: {worst:.2f} SE not within {FROZEN_TOLERANCE_SE:.2f} of frozen {FROZEN_REFERENCE_SE:.2f}")
    print("PASS: full 73,036-row production Total Bases holdout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
