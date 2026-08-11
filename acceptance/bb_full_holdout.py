#!/usr/bin/env python3
"""Fail-closed full-holdout acceptance gate for the production BB engine.

This gate is intentionally expected to remain non-green while the measured
worst calibration is above the frozen 2.18 SE ceiling. It exists so the
remaining residual cannot be hidden by an interactive or partial run.
"""
from __future__ import annotations

import argparse
import hashlib
import pickle

import numpy as np

from sportsedge.bb_engine import ENGINE_VERSION, simulate_bb

EXPECTED_FIXTURE_SHA256 = "1570375d0f3d8f48fec658571edd84f55e20b3789daa22cc35f6f91841890eb5"
FROZEN_TOLERANCE_SE = 2.18
THRESHOLDS = (0.5, 1.5, 2.5, 3.5)
N_SIM = 2000


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("fixture")
    p.add_argument("--paths", type=int, default=N_SIM)
    args = p.parse_args()

    raw = open(args.fixture, "rb").read()
    fixture_hash = hashlib.sha256(raw).hexdigest()
    if fixture_hash != EXPECTED_FIXTURE_SHA256:
        raise AssertionError(f"fixture hash mismatch: expected {EXPECTED_FIXTURE_SHA256}, got {fixture_hash}")
    data = pickle.loads(raw)
    rows = [x for x in data["dataset"] if x["season"] == "2024"]
    league_pool = data["train_pool"]

    sim = {t: [] for t in THRESHOLDS}
    actual = {t: [] for t in THRESHOLDS}
    identities: set[str] = set()

    for row in rows:
        identity_fields = {
            "market": "pitcher_walks",
            "date": row["date"],
            "recalibrated_rate": round(row["recalibrated_rate"], 12),
            "pool_hash": hashlib.sha256(str(row["pool"]).encode()).hexdigest(),
            "actual_bfp": row["actual_bfp"],
        }
        material = "|".join(f"{k}={v}" for k, v in sorted(identity_fields.items()))
        build_hash = hashlib.sha256(material.encode()).hexdigest()
        if build_hash in identities:
            raise AssertionError(f"identity collision: {build_hash}")
        identities.add(build_hash)

        out = simulate_bb({
            "build_hash": build_hash,
            "market": "pitcher_walks",
            "features": {
                "recalibrated_rate": row["recalibrated_rate"],
                "pool": row["pool"],
                "league_pool": league_pool,
            },
        }, thresholds=THRESHOLDS, n_sim=args.paths)
        for t in THRESHOLDS:
            sim[t].append(out.probs[t])
            actual[t].append(1 if row["actual_bb"] > t else 0)

    worst = 0.0
    for t in THRESHOLDS:
        s = np.asarray(sim[t], dtype=float)
        a = np.asarray(actual[t], dtype=float)
        gap_pp = abs(float(s.mean()) - float(a.mean())) * 100.0
        se_pp = float(np.sqrt(a.mean() * (1.0 - a.mean()) / len(a)) * 100.0)
        ratio = gap_pp / se_pp
        worst = max(worst, ratio)
        print(f"{t}: sim={s.mean():.4f} act={a.mean():.4f} gap={gap_pp:.2f}pp ({ratio:.2f} SE)")

    print(f"fixture={fixture_hash} engine={ENGINE_VERSION} rows={len(rows)} collisions=0 paths={args.paths} worst_se={worst:.4f}")
    if worst > FROZEN_TOLERANCE_SE:
        raise AssertionError(f"worst calibration {worst:.4f} SE exceeds frozen ceiling {FROZEN_TOLERANCE_SE:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
