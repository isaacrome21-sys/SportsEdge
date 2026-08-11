import unittest

from sportsedge.engine_registry import total_bases_engine_adapter
from sportsedge.total_bases_engine import (
    TRAIN_PA_COUNTS,
    TRAIN_PA_POOL,
    TotalBasesEngineError,
    simulate_total_bases,
)


def mk(build_hash="b" * 64, market="total_bases", lineup="CONFIRMED"):
    return {
        "build_hash": build_hash,
        "market": market,
        "lineup_status": lineup,
        "require_confirmed_lineup": False,
        "features": {
            "rates": {"s": 0.15, "d": 0.045, "t": 0.005, "hr": 0.035},
            "p_h": 0.23,
            "p_hr": 0.034,
            "park": 1.02,
            "pa_pool": [3, 4, 4, 5, 4, 3],
        },
    }


class TotalBasesEngineTests(unittest.TestCase):
    def test_frozen_train_pa_multiset_exact(self):
        self.assertEqual(len(TRAIN_PA_POOL), 53205)
        got = {int(k): int((TRAIN_PA_POOL == k).sum()) for k in sorted(TRAIN_PA_COUNTS)}
        self.assertEqual(got, TRAIN_PA_COUNTS)

    def test_same_candidate_reproducible(self):
        self.assertEqual(simulate_total_bases(mk()).probs, simulate_total_bases(mk()).probs)

    def test_cross_candidate_streams_diverge(self):
        self.assertNotEqual(simulate_total_bases(mk("a" * 64)).probs, simulate_total_bases(mk("f" * 64)).probs)

    def test_order_invariant_candidate_identity(self):
        a = simulate_total_bases(mk("12" * 32)).probs
        simulate_total_bases(mk("34" * 32))
        self.assertEqual(a, simulate_total_bases(mk("12" * 32)).probs)

    def test_shared_game_effect_is_recorded(self):
        self.assertEqual(simulate_total_bases(mk(), n_sim=100).shared_effect_module_sigma, 0.20)

    def test_sportsbook_probability_is_banned(self):
        x = mk(); x["features"]["implied_prob"] = 0.5
        with self.assertRaises(TotalBasesEngineError):
            simulate_total_bases(x)

    def test_projected_lineup_can_be_hard_gated(self):
        x = mk(lineup="PROJECTED"); x["require_confirmed_lineup"] = True
        with self.assertRaises(TotalBasesEngineError):
            simulate_total_bases(x)

    def test_adapter_under_is_complement(self):
        ext = mk(); ext.update({"market":"TOTAL_BASES","game_id":"g1","entity_id":"b1","line":1.5,"side":"OVER"})
        over = total_bases_engine_adapter(ext)["model_p"]
        ext["side"] = "UNDER"
        under = total_bases_engine_adapter(ext)["model_p"]
        self.assertAlmostEqual(over + under, 1.0, places=12)

    def test_bad_feature_shapes_fail_closed(self):
        x = mk(); x["features"]["rates"].pop("hr")
        with self.assertRaises(TotalBasesEngineError):
            simulate_total_bases(x)

    def test_invalid_mc_count_fails_closed(self):
        for value in (0, -1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(TotalBasesEngineError):
                    simulate_total_bases(mk(), n_sim=value)


if __name__ == "__main__":
    unittest.main()
