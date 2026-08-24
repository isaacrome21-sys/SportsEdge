import math
import unittest

from sportsedge.rbi_engine import price_rbi


def poisson_over(lam: float, line: float) -> float:
    k = math.floor(line)
    cdf = sum(math.exp(-lam) * lam**i / math.factorial(i) for i in range(k + 1))
    return 1.0 - cdf


class RBIBehavioralAcceptanceTests(unittest.TestCase):
    """Controlled shape fixture for RBI clustering without PA-binomial assumptions."""

    def _price(self, pool, line, side="OVER"):
        return price_rbi({
            "game_id": "fixture-rbi",
            "market": "RBI",
            "entity_id": "b1",
            "line": line,
            "side": side,
            "feature_source_hash": "e" * 64,
            "features": {"rbi_pool": pool},
        })

    def test_same_mean_can_have_materially_different_line_prices(self):
        # Mean = 0.8 with clustered multi-RBI games; one PA may create >1 RBI.
        pool = [0, 0, 0, 0, 0, 0, 1, 1, 3, 3]
        lam = 0.8
        c05 = self._price(pool, 0.5).model_p
        c15 = self._price(pool, 1.5).model_p
        self.assertAlmostEqual(c05, 0.4)
        self.assertAlmostEqual(c15, 0.2)
        self.assertNotAlmostEqual(c05, poisson_over(lam, 0.5), places=2)
        self.assertNotAlmostEqual(c15, poisson_over(lam, 1.5), places=2)

    def test_adjacent_over_lines_are_monotone(self):
        pool = [0, 0, 0, 0, 1, 1, 1, 2, 3, 4]
        p05 = self._price(pool, 0.5).model_p
        p15 = self._price(pool, 1.5).model_p
        p25 = self._price(pool, 2.5).model_p
        self.assertGreaterEqual(p05, p15)
        self.assertGreaterEqual(p15, p25)


if __name__ == "__main__":
    unittest.main()
