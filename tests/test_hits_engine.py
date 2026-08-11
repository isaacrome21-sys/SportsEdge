import unittest

from sportsedge.hits_engine import (
    HitsEngineError,
    reset_frozen_mean_model,
    set_frozen_mean_model,
    simulate_hits,
)


def mk(build_hash="a" * 64, market="hits", lineup="CONFIRMED", b_rate=0.28,
       p_rate=0.24, req_conf=False):
    return {
        "build_hash": build_hash,
        "market": market,
        "lineup_status": lineup,
        "require_confirmed_lineup": req_conf,
        "features": {"b_rate": b_rate, "p_rate": p_rate, "pa_pool": [3, 4, 4, 5, 3, 4]},
    }


class HitsEngineTests(unittest.TestCase):
    def setUp(self):
        set_frozen_mean_model((-0.06, 0.70, 0.55))

    def tearDown(self):
        reset_frozen_mean_model()

    def test_same_candidate_is_reproducible(self):
        self.assertEqual(simulate_hits(mk()).probs, simulate_hits(mk()).probs)

    def test_different_candidates_get_different_streams(self):
        self.assertNotEqual(simulate_hits(mk("a" * 64)).probs, simulate_hits(mk("f" * 64)).probs)

    def test_order_invariant_per_candidate(self):
        first = simulate_hits(mk("1a" * 32)).probs
        simulate_hits(mk("2b" * 32))
        self.assertEqual(first, simulate_hits(mk("1a" * 32)).probs)

    def test_wrong_market_rejected(self):
        with self.assertRaises(HitsEngineError):
            simulate_hits(mk(market="runs"))

    def test_confirmed_lineup_gate(self):
        with self.assertRaises(HitsEngineError):
            simulate_hits(mk(lineup="PROJECTED", req_conf=True))

    def test_banned_sportsbook_probability_rejected(self):
        x = mk()
        x["features"]["dk_novig_prob"] = 0.55
        with self.assertRaises(HitsEngineError):
            simulate_hits(x)

    def test_p_rate_is_live_model_component(self):
        low = simulate_hits(mk("c" * 64, p_rate=0.20)).probs
        high = simulate_hits(mk("c" * 64, p_rate=0.35)).probs
        self.assertNotEqual(low, high)

    def test_nonfinite_rates_rejected(self):
        for value in (float("nan"), float("inf"), -0.1, 1.1):
            with self.subTest(value=value):
                with self.assertRaises(HitsEngineError):
                    simulate_hits(mk(b_rate=value))

    def test_zero_pa_historical_entry_is_supported(self):
        x = mk()
        x["features"]["pa_pool"] = [0, 3, 4, 5]
        out = simulate_hits(x, n_sim=100)
        self.assertTrue(all(0 <= p <= 1 for p in out.probs.values()))

    def test_invalid_mc_count_rejected(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(HitsEngineError):
                    simulate_hits(mk(), n_sim=value)


if __name__ == "__main__":
    unittest.main()
