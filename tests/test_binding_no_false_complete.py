import unittest
from sportsedge.mlb_market_binding import binding_spec_for_market, BindingError

class NoFalseCompleteTests(unittest.TestCase):
    def test_unknown_market_cannot_inherit_threshold_domain(self):
        with self.assertRaises(BindingError):binding_spec_for_market("FUTURE_MARKET_NOT_DECLARED")

if __name__=="__main__":unittest.main()
