import unittest
from unittest.mock import patch


class FootballSportAdapterContractTests(unittest.TestCase):
    def test_nfl_and_cfb_adapters_import_and_keep_design_methods_closed(self):
        from sportsedge.sports.nfl.adapter import NFLAdapter
        from sportsedge.sports.cfb.adapter import CFBAdapter

        nfl = NFLAdapter()
        self.assertEqual(nfl.sport, "nfl")
        with self.assertRaises(NotImplementedError):
            nfl.load_schedule([2025])
        with self.assertRaises(NotImplementedError):
            nfl.load_lines_history([2025])
        # NFL dispersion/HFA methods are implemented, but intentionally fail
        # closed unless their hash-bound environment profile is supplied.
        with self.assertRaisesRegex(ValueError, "NFL_ENVIRONMENT_PROFILE_REQUIRED"):
            nfl.margin_sigma({})
        with self.assertRaisesRegex(ValueError, "NFL_ENVIRONMENT_PROFILE_REQUIRED"):
            nfl.total_sigma({})
        with self.assertRaisesRegex(ValueError, "HISTORICAL_KEY_NUMBERS_ARE_VALIDATION_ONLY"):
            nfl.key_numbers()
        with self.assertRaisesRegex(ValueError, "NFL_ENVIRONMENT_PROFILE_REQUIRED"):
            nfl.hfa_prior(None, {})

        cfb = CFBAdapter()
        self.assertEqual(cfb.sport, "cfb")
        with self.assertRaises(NotImplementedError):
            cfb.load_schedule([2025])
        with self.assertRaises(NotImplementedError):
            cfb.load_lines_history([2025])
        with self.assertRaises(NotImplementedError):
            cfb.margin_sigma({})
        with self.assertRaises(NotImplementedError):
            cfb.total_sigma({})
        with self.assertRaises(NotImplementedError):
            cfb.key_numbers()
        with self.assertRaises(NotImplementedError):
            cfb.hfa_prior(None, {})

    def test_cfb_build_features_delegates_to_existing_m2_builder(self):
        from sportsedge.sports.cfb.adapter import CFBAdapter
        source = {"game_start_ts": "2026-09-01T00:00:00+00:00", "marker": 7}
        with patch("sportsedge.sports.cfb.adapter.build_cfb_m2_features", side_effect=lambda row: dict(row)) as build:
            out = CFBAdapter().build_features("2026-08-31T12:00:00+00:00", [source])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["feature_asof_ts"], "2026-08-31T12:00:00+00:00")
        self.assertEqual(out[0]["marker"], 7)
        build.assert_called_once()

    def test_nfl_build_features_delegates_to_existing_m2_builder(self):
        from sportsedge.sports.nfl.adapter import NFLAdapter
        source = {"game_start_ts": "2026-09-10T00:00:00+00:00", "marker": 9}
        with patch("sportsedge.sports.nfl.adapter.build_nfl_m2_features", side_effect=lambda row: dict(row)) as build:
            out = NFLAdapter().build_features("2026-09-09T12:00:00+00:00", source)
        self.assertEqual(out["feature_asof_ts"], "2026-09-09T12:00:00+00:00")
        self.assertEqual(out["marker"], 9)
        build.assert_called_once()

    def test_build_features_rejects_non_mapping_rows(self):
        from sportsedge.sports.nfl.adapter import NFLAdapter
        from sportsedge.sports.cfb.adapter import CFBAdapter
        for adapter in (NFLAdapter(), CFBAdapter()):
            with self.subTest(sport=adapter.sport):
                with self.assertRaises(TypeError):
                    adapter.build_features("2026-08-31T12:00:00+00:00", ["bad"])


if __name__ == "__main__":
    unittest.main()
