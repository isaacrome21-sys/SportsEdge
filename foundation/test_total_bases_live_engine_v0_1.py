#!/usr/bin/env python3
from total_bases_live_engine_v0_1 import simulate_total_bases, TotalBasesEngineError

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

# Deterministic reference from the first 2023 holdout row, using 25k paths.
r1 = simulate_total_bases(MODEL_INPUT, line=1.5, n_paths=25_000, seed=3100)
r2 = simulate_total_bases(MODEL_INPUT, line=1.5, n_paths=25_000, seed=3100)
assert r1 == r2
assert r1["model_input_hash"] == MODEL_INPUT["build_hash"]
assert r1["mc_paths"] == 25_000 and r1["mc_status"] == "PASS"
assert r1["source_kind"] == "SPORTSEDGE_MC"
assert r1["shared_game_effect_sigma"] == 0.20
# Histogram re-encoding preserves the empirical baseline distribution but not
# byte/path identity with the original pickle order, so use a narrow numerical
# regression around the independently computed reference, not exact bytes.
assert abs(r1["model_p"] - 0.43744) < 0.01, r1
assert abs(r1["mean"] - 1.76208) < 0.03, r1

bad = dict(MODEL_INPUT); bad["lineup_status"] = "PROJECTED"
raises(lambda: simulate_total_bases(bad, line=1.5), "LINEUP_NOT_CONFIRMED")
raises(lambda: simulate_total_bases(MODEL_INPUT, line=3.5), "UNSUPPORTED_LINE")

print("total bases live engine v0.1 regression PASS")
