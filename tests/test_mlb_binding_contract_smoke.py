import unittest
from sportsedge.mlb_market_binding import MarketBindingSpec

class Smoke(unittest.TestCase):
    def test_domain_is_required(self):
        with self.assertRaises(TypeError):MarketBindingSpec("TOTALS")

if __name__=="__main__":unittest.main()
