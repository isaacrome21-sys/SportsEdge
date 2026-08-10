#!/usr/bin/env python3
import hashlib
from hits_live_engine_v0_1 import simulate_hits, HitsEngineError, MEAN_MODEL_COEF

BASE = {
    "market": "hits",
    "entity_id": "fixture_player",
    "game_id": "fixture_game",
    "lineup_status": "CONFIRMED",
    "build_hash": hashlib.sha256(b"fixture-hits-candidate").hexdigest(),
    "features": {
        "b_rate": 0.29,
        "p_rate": 0.26,
        "pa_pool": [3,4,4,5,4,5,4,4,5,3,4,5],
    },
}


def raises(fn, text):
    try:
        fn()
    except HitsEngineError as exc:
        assert text in str(exc), (text, str(exc))
        return
    raise AssertionError(f"expected {text}")


# Reproducible candidate identity.
a = simulate_hits(BASE, n_paths=5_000)
b = simulate_hits(BASE, n_paths=5_000)
assert a == b
assert a.model_input_hash == BASE["build_hash"]
assert a.shared_effect_sigma == 0.20
assert a.seed_policy == "sha256_build_hash_seedsequence_v1"

# Different immutable identity must alter stream/output.
other = dict(BASE)
other["build_hash"] = hashlib.sha256(b"fixture-hits-candidate-2").hexdigest()
c = simulate_hits(other, n_paths=5_000)
assert c.probs != a.probs

# Order independence: running a second candidate cannot perturb the first.
again = simulate_hits(BASE, n_paths=5_000)
assert again == a

# Regression for the bug found in the local handoff: p_rate must influence Model_P.
low = {**BASE, "build_hash": hashlib.sha256(b"p-rate-low").hexdigest(), "features": {**BASE["features"], "p_rate": 0.05}}
high = {**BASE, "build_hash": low["build_hash"], "features": {**BASE["features"], "p_rate": 0.50}}
lo = simulate_hits(low, n_paths=10_000)
hi = simulate_hits(high, n_paths=10_000)
assert lo.probs != hi.probs, (MEAN_MODEL_COEF, lo, hi)

bad = dict(BASE); bad["market"] = "runs"
raises(lambda: simulate_hits(bad), "WRONG_MARKET")
bad = dict(BASE); bad["lineup_status"] = "PROJECTED"
raises(lambda: simulate_hits(bad), "LINEUP_NOT_CONFIRMED")
bad = dict(BASE); bad.pop("build_hash")
raises(lambda: simulate_hits(bad), "MODEL_INPUT_HASH_MISSING")
bad = {**BASE, "features": {**BASE["features"], "b_rate": 2.0}}
raises(lambda: simulate_hits(bad), "INVALID_FEATURE:b_rate")
raises(lambda: simulate_hits(BASE, thresholds=(3.5,)), "UNSUPPORTED_LINE")

print("hits live engine v0.1 structural regression PASS")
