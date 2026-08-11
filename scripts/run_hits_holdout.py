#!/usr/bin/env python3
"""Run the authoritative full Hits production-engine holdout.

The command accepts raw or gzip transport, but always verifies the decompressed
canonical fixture bytes against the frozen SHA-256. Candidate RNG identity is
pregame-only: game_id + player_id + market + feature contract. Outcome fields
never influence the simulation stream.
"""
import argparse
import hashlib
import pickle
from pathlib import Path

import numpy as np

from sportsedge.fixture_io import FixtureIOError, read_canonical_fixture_bytes
from sportsedge.hits_engine import (
    FEATURE_CONTRACT_VERSION,
    FROZEN_MEAN_MODEL_COEF,
    reset_frozen_mean_model,
    set_frozen_mean_model,
    simulate_hits,
)

EXPECTED_FIXTURE_SHA256 = "aaa006155de8078057fae0bd764a6aebca7e06057d9e83669d816536c5471776"
EXPECTED_HOLDOUT_ROWS = 83769
FROZEN_TOLERANCE_SE = 2.63


def candidate_identity(g: dict) -> str:
    game_id = str(g.get("game_id", "")).strip()
    player_id = str(g.get("player_id", "")).strip()
    if not game_id or not player_id:
        raise SystemExit("fixture row missing pregame game_id/player_id identity")
    material = "|".join(("market=HITS", f"game_id={game_id}", f"player_id={player_id}", f"feature_version={FEATURE_CONTRACT_VERSION}"))
    return hashlib.sha256(material.encode()).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("fixture", type=Path, help="path to frozen rebuilt bb_hits_data.pkl or byte-preserving .gz transport")
    args = p.parse_args()
    try:
        raw = read_canonical_fixture_bytes(args.fixture, expected_sha256=EXPECTED_FIXTURE_SHA256)
    except FixtureIOError as exc:
        raise SystemExit(str(exc)) from exc

    data = pickle.loads(raw)
    train = [x for x in data["dataset"] if x["season"] in ("2021", "2022")]
    holdout = [x for x in data["dataset"] if x["season"] in ("2023", "2024")]
    if len(holdout) != EXPECTED_HOLDOUT_ROWS:
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
            build_hash = candidate_identity(g)
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

    if len(seen) != EXPECTED_HOLDOUT_ROWS:
        raise SystemExit("identity cardinality mismatch")
    print(f"holdout rows: {len(holdout)}")
    print("identity collisions in holdout: 0")
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
