import math
import unittest

from sportsedge.pitcher_outs_engine import price_pitcher_outs


def poisson_tail(lam: float, line: float) -> float:
    k = math.floor(line)
    cdf = sum(math.exp(-lam) * lam**i / math.factorial(i) for i in range(k + 1))
    return 1.0 - cdf


class PitcherOutsBehavioralAcceptanceTests(unittest.TestCase):
    """Controlled fixture proving the candidate repairs the measured support defect."""

    def test_candidate_removes_impossible_mass_and_changes_high_line_price(self):
        pool = [18, 19, 20, 21, 22, 23, 24, 25, 26, 27]
        lam = sum(pool) / len(pool)
        incumbent_impossible_mass = poisson_tail(lam, 27.0)
        self.assertGreater(incumbent_impossible_mass, 0.0)

        candidate = price_pitcher_outs({
            "game_id": "fixture-outs",
            "market": "PITCHER_OUTS",
            "entity_id": "ace",
            "line": 27.0,
            "side": "OVER",
            "feature_source_hash": "b" * 64,
            "features": {"workload_pool": pool},
        })
        self.assertEqual(candidate.model_p, 0.0)
        self.assertEqual(candidate.push_p, 0.1)

    def test_candidate_probability_is_monotone_across_half_run_lines(self):
        pool = [12, 15, 17, 18, 18, 19, 20, 21, 23, 24]
        probs = []
        for line in (14.5, 16.5, 18.5, 20.5, 22.5):
            probs.append(price_pitcher_outs({
                "game_id": "fixture-outs",
                "market": "PITCHER_OUTS",
                "entity_id": "p1",
                "line": line,
                "side": "OVER",
                "feature_source_hash": "c" * 64,
                "features": {"workload_pool": pool},
            }).model_p)
        self.assertEqual(probs, sorted(probs, reverse=True))


if __name__ == "__main__":
    unittest.main()
