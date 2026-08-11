import unittest

from sportsedge.bb_engine import BBEngineError, simulate_bb
from sportsedge.engine_registry import engine_registry


def mi():
    return {
        "build_hash": "a" * 64,
        "market": "pitcher_walks",
        "features": {
            "own_bb": 20,
            "own_bfp": 220,
            "rolling_league_rate": .082,
            "pool": [22,24,25,27,28],
            "league_pool": [20,21,23,24,25,26,27,28,29],
        },
    }


def native_mi():
    return {
        "build_hash": "b" * 64,
        "market": "pitcher_walks",
        "features": {
            "recalibrated_rate": .086,
            "pool": [22,24,25,27,28],
            "league_pool": [20,21,23,24,25,26,27,28,29],
        },
    }


class BBEngineTests(unittest.TestCase):
    def test_engine_is_deterministic_and_bounded(self):
        a = simulate_bb(mi(), thresholds=(1.5,), n_sim=500)
        b = simulate_bb(mi(), thresholds=(1.5,), n_sim=500)
        self.assertEqual(a.probs, b.probs)
        self.assertGreaterEqual(a.probs[1.5], 0)
        self.assertLessEqual(a.probs[1.5], 1)
        self.assertEqual(a.window_days, 45)
        self.assertEqual(a.shrinkage, 400)

    def test_native_rate_path_is_deterministic_and_does_not_require_raw_rate_inputs(self):
        a = simulate_bb(native_mi(), thresholds=(1.5,), n_sim=500)
        b = simulate_bb(native_mi(), thresholds=(1.5,), n_sim=500)
        self.assertEqual(a.probs, b.probs)
        self.assertEqual(a.engine_version, "bb_engine_v1.1")

    def test_native_and_raw_rate_inputs_cannot_be_mixed(self):
        x = native_mi()
        x["features"]["own_bb"] = 20
        with self.assertRaises(BBEngineError):
            simulate_bb(x)

    def test_native_rate_still_requires_both_workload_pools(self):
        x = native_mi(); del x["features"]["league_pool"]
        with self.assertRaises(BBEngineError):
            simulate_bb(x)

    def test_missing_league_pool_fails_closed(self):
        x = mi(); del x["features"]["league_pool"]
        with self.assertRaises(BBEngineError):
            simulate_bb(x)

    def test_runtime_adapter_registered_but_deployment_gate_remains_external(self):
        adapter = engine_registry()["PITCHER_BB"]
        ext = {
            **mi(), "market": "PITCHER_BB", "game_id": "777", "entity_id": "42",
            "line": 1.5, "side": "OVER",
        }
        out = adapter(ext)
        self.assertEqual(out["market"], "PITCHER_BB")
        self.assertEqual(out["engine_version"], "bb_engine_v1.1")
        self.assertGreaterEqual(out["model_p"], 0)
        self.assertLessEqual(out["model_p"], 1)


if __name__ == "__main__":
    unittest.main()
