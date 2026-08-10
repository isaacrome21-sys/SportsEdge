#!/usr/bin/env python3
"""TB shared-game-effect CI smoke test -- NOT VALIDATION.

Fast functional regression guard only. The full 2,000-path acceptance test
remains the only calibration/promotion gate.
"""
import pickle
import sys
import numpy as np

sys.path.insert(0, "foundation")
from sportsedge_shared_game_effect import SIGMA_GAME_EFFECT, apply_shared_game_effect

SMOKE_SEED = 42
SMOKE_N_SIM = 200
SMOKE_N_GAMES = 25
LG_PH = 0.2258
FAILS = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}: {name} {detail}")
    if not cond:
        FAILS.append(name)


def scaled(x):
    ch = (x['p_h'] / LG_PH) ** 0.7
    chr_ = (x['p_hr'] / 0.03357) ** 0.3
    return np.array([
        x['rates']['s'] * ch,
        x['rates']['d'] * ch,
        x['rates']['t'] * ch,
        x['rates']['hr'] * chr_,
    ])


def main():
    print("=== TB SHARED-GAME-EFFECT SMOKE TEST (NOT VALIDATION) ===\n")
    check("production sigma imported", SIGMA_GAME_EFFECT == 0.20, f"got {SIGMA_GAME_EFFECT}")

    with open("tb_gameeffect_data.pkl", "rb") as f:
        d = pickle.load(f)
    holdout = [x for x in d['dataset'] if x['season'] in ('2023', '2024')]
    subset = holdout[:SMOKE_N_GAMES]
    check("fixed subset size", len(subset) == SMOKE_N_GAMES, f"got {len(subset)}")

    rng = np.random.default_rng(SMOKE_SEED)
    schema_ok = True
    active_games = 0
    shared_factor_ok = True

    for x in subset:
        base = np.clip(scaled(x), 1e-5, 0.5)
        shared = apply_shared_game_effect(base, SMOKE_N_SIM, rng)
        indep = np.tile(base, (SMOKE_N_SIM, 1))

        if not (
            shared.shape == (SMOKE_N_SIM, 4)
            and np.all(np.isfinite(shared))
            and np.all((shared >= 0) & (shared <= 1))
        ):
            schema_ok = False

        # Wiring test: for the SAME game, independent path has no path-to-path
        # variance while the shared-effect production path must vary.
        shared_path_mean = shared.mean(axis=1)
        indep_path_mean = indep.mean(axis=1)
        if np.std(shared_path_mean) > 1e-6 and np.std(indep_path_mean) < 1e-12:
            active_games += 1

        # Common-factor test: away from clipping, all TB components must be
        # scaled by the same multiplicative game draw. Their ratios therefore
        # stay fixed across simulation paths.
        unclipped = (shared > 1e-4).all(axis=1) & (shared < 0.89).all(axis=1)
        if np.any(unclipped):
            ratios = shared[unclipped, 1] / shared[unclipped, 0]
            expected = base[1] / base[0]
            if not np.allclose(ratios, expected, rtol=1e-10, atol=1e-12):
                shared_factor_ok = False

    check("schema/bounds", schema_ok)
    check(
        "shared path varies while independent path does not",
        active_games == SMOKE_N_GAMES,
        f"{active_games}/{SMOKE_N_GAMES}",
    )
    check("same multiplicative factor shared across TB components", shared_factor_ok)

    if FAILS:
        print("SMOKE TEST FAILED:", FAILS)
        print("Functional/wiring failure only -- run full acceptance for calibration.")
        return 1

    print("SMOKE TEST PASSED (functional only -- not calibration)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
