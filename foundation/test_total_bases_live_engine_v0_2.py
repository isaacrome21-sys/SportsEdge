#!/usr/bin/env python3
from total_bases_live_engine_v0_2 import (
    simulate_total_bases, seed_from_build_hash, TotalBasesEngineError,
    SEED_POLICY,
)

MODEL_INPUT = {
    "market": "total_bases",
    "entity_id": "fixture_player",
    "game_id": "fixture_game",
    "lineup_status": "CONFIRMED",
    "build_hash": "fixture-build-hash",
    "features": {
        "rates_s": 0.15233357186499186,
        "rates_d": 0.05016898623594384,
        "rates_t": 0.006164786092418761,
        "rates_hr": 0.03404513968208001,
        "p_h": 0.2393846153846154,
        "p_hr": 0.028971883502457607,
        "park": 0.9036757938976787,
        "pa_pool": [5,5,4,4,4,5,4,5,4,5,4,4,4,5,4,5,5,3,5,4,4,5,5,6,5,5,5,3,5,3],
    },
}


def raises(fn, text):
    try:
        fn()
    except TotalBasesEngineError as e:
        assert text in str(e), (text, str(e))
        return
    raise AssertionError(f"expected {text}")

# Same immutable input => same full-width seed and exact same MC output.
s1 = seed_from_build_hash(MODEL_INPUT["build_hash"])
s2 = seed_from_build_hash(MODEL_INPUT["build_hash"])
assert s1 == s2
assert s1.bit_length() > 64  # guard against accidental low-width truncation
r1 = simulate_total_bases(MODEL_INPUT, line=1.5, n_paths=25_000)
r2 = simulate_total_bases(MODEL_INPUT, line=1.5, n_paths=25_000)
assert r1 == r2
assert r1["seed_policy"] == SEED_POLICY
assert r1["model_input_hash"] == MODEL_INPUT["build_hash"]
assert r1["mc_paths"] == 25_000 and r1["mc_status"] == "PASS"
assert r1["source_kind"] == "SPORTSEDGE_MC"
assert r1["shared_game_effect_sigma"] == 0.20
assert abs(r1["model_p"] - 0.4456) < 0.01, r1
assert abs(r1["mean"] - 1.79676) < 0.03, r1

# Different immutable candidate identity must not reuse the same random stream.
OTHER = dict(MODEL_INPUT)
OTHER["build_hash"] = "fixture-build-hash-other-candidate"
assert seed_from_build_hash(OTHER["build_hash"]) != s1
r3 = simulate_total_bases(OTHER, line=1.5, n_paths=25_000)
assert r3["seed_fingerprint"] != r1["seed_fingerprint"]
assert r3 != r1

bad = dict(MODEL_INPUT); bad["lineup_status"] = "PROJECTED"
raises(lambda: simulate_total_bases(bad, line=1.5), "LINEUP_NOT_CONFIRMED")
raises(lambda: simulate_total_bases(MODEL_INPUT, line=3.5), "UNSUPPORTED_LINE")
raises(lambda: seed_from_build_hash(""), "MODEL_INPUT_HASH_MISSING")

print("total bases live engine v0.2 seed-policy regression PASS")
