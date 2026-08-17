import unittest


class FootballSportAdapterContractTests(unittest.TestCase):
    def test_nfl_and_cfb_adapters_import_and_fail_closed(self):
        from sportsedge.sports.nfl.adapter import NFLAdapter
        from sportsedge.sports.cfb.adapter import CFBAdapter

        for adapter_cls, sport in ((NFLAdapter, "nfl"), (CFBAdapter, "cfb")):
            adapter = adapter_cls()
            self.assertEqual(adapter.sport, sport)
            with self.assertRaises(NotImplementedError):
                adapter.load_schedule([2025])
            with self.assertRaises(NotImplementedError):
                adapter.load_lines_history([2025])
            with self.assertRaises(NotImplementedError):
                adapter.build_features(None, [])
            with self.assertRaises(NotImplementedError):
                adapter.margin_sigma({})
            with self.assertRaises(NotImplementedError):
                adapter.total_sigma({})
            with self.assertRaises(NotImplementedError):
                adapter.key_numbers()
            with self.assertRaises(NotImplementedError):
                adapter.hfa_prior(None, {})


if __name__ == "__main__":
    unittest.main()
