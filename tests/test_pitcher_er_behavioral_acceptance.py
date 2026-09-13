import math
import unittest

from sportsedge.pitcher_er_engine import price_pitcher_er


def poisson_over(lam: float, line: float) -> float:
    k = math.floor(line)
    cdf = sum(math.exp(-lam) * lam**i / math.factorial(i) for i in range(k + 1))
    return 1.0 - cdf


class PitcherERBehavioralAcceptanceTests(unittest.TestCase):
    """Shape-sensitive fixture: equal mean, different crooked-inning distribution."""

    def _price(self, pool, line, side="OVER"):
        return price_pitcher_er({
            "game_id": "fixture-er",
            "market": "PITCHER_ER",
            "entity_id": "p1",
            "line": line,
            "side": side,
            "feature_source_hash": "d" * 64,
            "features": {"earned_runs_pool": pool},
        })

    def test_equal_mean_does_not_force_poisson_shape(self):
        # Mean = 2.0, but mass is deliberately clustered at 0 and 4 ER.
        pool = [0, 0, 0, 0, 0, 4, 4, 4, 4, 4]
        lam = 2.0
        candidate_25 = self._price(pool, 2.5).model_p
        candidate_35 = self._price(pool, 3.5).model_p
        self.assertAlmostEqual(candidate_25, 0.5)
        self.assertAlmostEqual(candidate_35, 0.5)
        self.assertNotAlmostEqual(candidate_25, poisson_over(lam, 2.5), places=2)
        self.assertNotAlmostEqual(candidate_35, poisson_over(lam, 3.5), places=2)

    def test_integer_line_conserves_push_mass(self):
        pool = [0, 1, 2, 2, 2, 3, 4, 4, 5, 6]
        over = self._price(pool, 2.0, "OVER")
        under = self._price(pool, 2.0, "UNDER")
        self.assertAlmostEqual(over.model_p + under.model_p + over.push_p, 1.0)


if __name__ == "__main__":
    unittest.main()
