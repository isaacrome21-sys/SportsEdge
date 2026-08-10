#!/usr/bin/env python3
from copy import deepcopy
from total_bases_live_engine_v0_1 import simulate_total_bases, TotalBasesEngineError, SEED_POLICY

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

# Property 1: same immutable candidate identity => exact reproducibility.
r1 = simulate_total_bases(MODEL_INPUT, line=1.5, n_paths=25_000)
r2 = simulate_total_bases(MODEL_INPUT, line=1.5, n_paths=25_000)
assert r1 == r2
assert r1["seed_policy"] == SEED_POLICY
assert r1["model_input_hash"] == MODEL_INPUT["build_hash"]
assert r1["mc_paths"] == 25_000 and r1["mc_status"] == "PASS"
assert r1["source_kind"] == "SPORTSEDGE_MC"
assert r1["shared_game_effect_sigma"] == 0.20

# Property 2: distinct candidate identities => distinct deterministic streams.
MI_B = deepcopy(MODEL_INPUT)
MI_B["build_hash"] = "fixture-build-hash-B"
r_b = simulate_total_bases(MI_B, line=1.5, n_paths=25_000)
assert r_b["seed_fingerprint"] != r1["seed_fingerprint"]
assert (r_b["model_p"], r_b["mean"], r_b["variance"]) != (r1["model_p"], r1["mean"], r1["variance"])

# Property 3: order/batch position cannot affect candidate output.
first_order = [
    simulate_total_bases(MODEL_INPUT, line=1.5, n_paths=5_000),
    simulate_total_bases(MI_B, line=1.5, n_paths=5_000),
]
second_order = [
    simulate_total_bases(MI_B, line=1.5, n_paths=5_000),
    simulate_total_bases(MODEL_INPUT, line=1.5, n_paths=5_000),
]
assert first_order[0] == second_order[1]
assert first_order[1] == second_order[0]

# Explicit integer seeds remain available for research-only replay and must be deterministic.
rex1 = simulate_total_bases(MODEL_INPUT, line=1.5, n_paths=25_000, seed=3100)
rex2 = simulate_total_bases(MODEL_INPUT, line=1.5, n_paths=25_000, seed=3100)
assert rex1 == rex2
assert rex1["seed_policy"] == "explicit_integer_seed_research_only"

bad = dict(MODEL_INPUT); bad["lineup_status"] = "PROJECTED"
raises(lambda: simulate_total_bases(bad, line=1.5), "LINEUP_NOT_CONFIRMED")
raises(lambda: simulate_total_bases(MODEL_INPUT, line=3.5), "UNSUPPORTED_LINE")
raises(lambda: simulate_total_bases(MODEL_INPUT, line=1.5, seed=True), "INVALID_SEED")

print("total bases live engine v0.1 seed-policy regression PASS")
