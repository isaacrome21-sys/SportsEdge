#!/usr/bin/env python3
"""Authoritative fixture-backed Total Bases production-engine holdout.

Every holdout row calls sportsedge.total_bases_engine.simulate_total_bases.
The command accepts raw or gzip transport, but always verifies decompressed
canonical fixture bytes before scoring. Candidate identity is pregame-only:
game_id + player_id + market + feature-contract version. Outcome fields are
never allowed to influence the Monte Carlo seed.
"""
import argparse
import hashlib
import multiprocessing as mp
import pickle
from pathlib import Path

import numpy as np

from sportsedge.fixture_io import FixtureIOError, read_canonical_fixture_bytes
from sportsedge.total_bases_engine import (
    FEATURE_CONTRACT_VERSION,
    MAX_PA_SLOTS,
    TRAIN_PA_COUNTS,
    TRAIN_PA_POOL,
    TRAIN_SCALE,
    simulate_total_bases,
)

EXPECTED_FIXTURE_SHA256 = "1a816f5f46bf1042c2dcc13078092b6205b359a2ad49dca3fcfdb7b787914859"
EXPECTED_HOLDOUT_ROWS = 73036
FROZEN_REFERENCE_SE = 1.60
FROZEN_TOLERANCE_SE = 0.20
THRESHOLDS = (0.5, 1.5, 2.5)


def identity_hash(g: dict) -> str:
    if "game_id" not in g or "player_id" not in g:
        raise ValueError("fixture row missing pregame game_id/player_id identity")
    payload = {
        "market": "total_bases",
        "game_id": str(g["game_id"]),
        "player_id": str(g["player_id"]),
        "feature_contract_version": FEATURE_CONTRACT_VERSION,
    }
    identity_key = "|".join(f"{k}={v}" for k, v in sorted(payload.items()))
    return hashlib.sha256(identity_key.encode("utf-8")).hexdigest()


def _score(item):
    build_hash, g = item
    out = simulate_total_bases({
        "build_hash": build_hash,
        "market": "total_bases",
        "lineup_status": "CONFIRMED",
        "require_confirmed_lineup": False,
        "features": {
            "rates": g["rates"],
            "p_h": g["p_h"],
            "p_hr": g["p_hr"],
            "park": g["park"],
            "pa_pool": g["pa_pool"],
        },
    }, thresholds=THRESHOLDS, n_sim=2000)
    return tuple(out.probs[t] for t in THRESHOLDS), tuple(int(g["actual_tb"] > t) for t in THRESHOLDS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", type=Path, help="path to frozen tb_gameeffect_data.pkl or byte-preserving .gz transport")
    parser.add_argument("--workers", type=int, default=max(1, min(8, mp.cpu_count())))
    args = parser.parse_args()
    if args.workers <= 0:
        raise SystemExit("workers must be positive")

    try:
        raw = read_canonical_fixture_bytes(args.fixture, expected_sha256=EXPECTED_FIXTURE_SHA256)
    except FixtureIOError as exc:
        raise SystemExit(str(exc)) from exc
    data = pickle.loads(raw)
    dataset = data["dataset"]
    train = [x for x in dataset if x["season"] in ("2021", "2022")]
    holdout = [x for x in dataset if x["season"] in ("2023", "2024")]
    if len(holdout) != EXPECTED_HOLDOUT_ROWS:
        raise SystemExit(f"unexpected holdout rows: {len(holdout)}")
    if not all("game_id" in x and "player_id" in x for x in holdout):
        raise SystemExit("fixture missing pregame game_id/player_id identity")

    source_pool = np.asarray(data["train_pa_pool"], dtype=np.int64)
    source_counts = {int(k): int((source_pool == k).sum()) for k in sorted(TRAIN_PA_COUNTS)}
    if source_counts != TRAIN_PA_COUNTS or len(source_pool) != len(TRAIN_PA_POOL):
        raise SystemExit(f"train PA multiset mismatch: {source_counts}")

    own_pa = [int(v) for x in dataset for v in x["pa_pool"]]
    if not own_pa or min(own_pa) < 0 or max(own_pa) > MAX_PA_SLOTS:
        raise SystemExit(f"fixture PA pool exceeds production engine bound: max={max(own_pa) if own_pa else None}")

    LG_PH = 0.2258
    AH, AHR, KP = 0.7, 0.3, 0.5

    def scaled(x):
        ch = (x["p_h"] / LG_PH) ** AH
        chr_ = (x["p_hr"] / 0.03357) ** AHR
        pk = x["park"] ** KP
        return np.array([
            x["rates"]["s"] * ch,
            x["rates"]["d"] * ch,
            x["rates"]["t"] * ch,
            x["rates"]["hr"] * chr_ * pk,
        ])

    tr_pa = np.array([x["actual_pa"] for x in train], dtype=float)
    tr_tb = np.array([x["actual_tb"] for x in train], dtype=float)
    R = np.array([scaled(x) for x in train])
    fitted_scale = tr_tb.sum() / ((R * np.array([1, 2, 3, 4])).sum(axis=1) * tr_pa).sum()
    if abs(float(fitted_scale) - TRAIN_SCALE) > 1e-12:
        raise SystemExit(f"train-only scale mismatch: {fitted_scale} vs {TRAIN_SCALE}")

    identities = [identity_hash(g) for g in holdout]
    collisions = len(identities) - len(set(identities))
    if collisions:
        raise SystemExit(f"candidate identity collisions: {collisions}")

    sums = np.zeros(3, dtype=float)
    actual = np.zeros(3, dtype=np.int64)
    with mp.Pool(args.workers) as pool:
        for probs, outcomes in pool.imap_unordered(_score, zip(identities, holdout), chunksize=100):
            sums += probs
            actual += outcomes

    n = len(holdout)
    worst = 0.0
    print(f"fixture_sha256: {EXPECTED_FIXTURE_SHA256}")
    print(f"holdout_rows: {n}")
    print(f"identity_collisions: {collisions}")
    print(f"max_fixture_pa_pool: {max(own_pa)}")
    for i, t in enumerate(THRESHOLDS):
        p = sums[i] / n
        a = actual[i] / n
        gap = abs(p - a) * 100.0
        se = np.sqrt(a * (1 - a) / n) * 100.0
        z = gap / se
        worst = max(worst, z)
        print(f"{t}: sim={p:.4f} actual={a:.4f} gap={gap:.2f}pp ({z:.2f} SE)")
    print(f"WORST: {worst:.2f} SE")
    if abs(worst - FROZEN_REFERENCE_SE) >= FROZEN_TOLERANCE_SE:
        raise SystemExit(f"FAIL: {worst:.2f} SE not within {FROZEN_TOLERANCE_SE:.2f} of frozen {FROZEN_REFERENCE_SE:.2f}")
    print("PASS: full 73,036-row production Total Bases holdout")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
