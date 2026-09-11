import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("venue_contract_tested", ROOT / "sportsedge/sports/nfl/venue_contract.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


vc = _load()
POLICY = vc.load_policy(ROOT / "config/nfl_venue_policy_v1.json")
HFA = 1.8


def mcg_game(**over):
    row = {
        "home_team": "LA",
        "away_team": "SF",
        "neutral_site": True,
        "venue_country": "AU",
        "venue_id": "MCG",
        "kickoff_utc": "2026-09-11T00:35:00Z",
        "weather_observed_at": "2026-09-10T23:00:00Z",
    }
    row.update(over)
    return row


class VenueGate(unittest.TestCase):
    def test_mcg_not_retroactive(self):
        out = vc.evaluate_venue_gate(mcg_game(), HFA, POLICY)
        self.assertEqual(out["blockers"], ["VENUE_POLICY_NOT_EFFECTIVE"])
        self.assertFalse(out["priceable"])

    def test_future_mcg_priceable_and_segmented(self):
        out = vc.evaluate_venue_gate(mcg_game(kickoff_utc="2027-09-10T00:35:00Z"), HFA, POLICY)
        self.assertTrue(out["priceable"], out["blockers"])
        self.assertEqual(out["venue_class"], vc.NEUTRAL_INTERNATIONAL)
        self.assertEqual(out["governed_hfa"], 0.0)
        self.assertEqual(out["sensitivity_band"], (0.0, 0.9))
        self.assertEqual(out["ledger_segment"], "NEUTRAL_INTL")
        self.assertFalse(out["in_primary_confirmation_test"])
        self.assertEqual(out["travel"]["tz_shift_abs_differential"], 0.0)
        self.assertEqual(out["policy_sha256"], POLICY["_sha256"])

    def test_home_game_unchanged(self):
        game = {
            "home_team": "KC", "away_team": "DEN", "neutral_site": False,
            "venue_country": "US", "kickoff_utc": "2026-09-13T17:00:00Z",
        }
        out = vc.evaluate_venue_gate(game, HFA, POLICY)
        self.assertTrue(out["priceable"])
        self.assertEqual(out["governed_hfa"], HFA)
        self.assertTrue(out["in_primary_confirmation_test"])

    def test_missing_neutral_flag_blocks(self):
        out = vc.evaluate_venue_gate(mcg_game(neutral_site=None), HFA, POLICY)
        self.assertEqual(out["blockers"], ["VENUE_CLASS_UNRESOLVED"])

    def test_non_neutral_abroad_is_inconsistent(self):
        out = vc.evaluate_venue_gate(mcg_game(neutral_site=False), HFA, POLICY)
        self.assertEqual(out["blockers"], ["VENUE_CLASS_INCONSISTENT"])

    def test_unregistered_venue_blocks(self):
        out = vc.evaluate_venue_gate(
            mcg_game(venue_id="WEMBLEY", venue_country="GB", kickoff_utc="2027-10-10T13:30:00Z"), HFA, POLICY
        )
        self.assertEqual(out["blockers"], ["ENVIRONMENT_PROFILE_MISSING"])

    def test_outdoor_without_weather_blocks(self):
        out = vc.evaluate_venue_gate(
            mcg_game(kickoff_utc="2027-09-10T00:35:00Z", weather_observed_at=None), HFA, POLICY
        )
        self.assertIn("ENVIRONMENT_WEATHER_MISSING", out["blockers"])
        self.assertFalse(out["priceable"])

    def test_tz_shift_wraps(self):
        self.assertEqual(vc.tz_shift_hours("SF", "Australia/Melbourne", "2026-09-11T00:35:00Z"), -7.0)
        d = vc.travel_differential("JAX", "SEA", "Europe/London", "2026-10-11T13:30:00Z")
        self.assertEqual((d["home_tz_shift_hours"], d["away_tz_shift_hours"]), (5.0, 8.0))
        self.assertEqual(d["tz_shift_abs_differential"], -3.0)

    def test_invalid_kickoff_fails_closed_not_crash(self):
        out = vc.evaluate_venue_gate(mcg_game(kickoff_utc="not-a-time"), HFA, POLICY)
        self.assertFalse(out["priceable"])
        self.assertEqual(out["blockers"], ["KICKOFF_TIME_INVALID"])

    def test_boolean_or_nonfinite_hfa_is_invalid(self):
        for bad in (True, False, float("nan"), float("inf"), -1.0):
            with self.subTest(value=bad):
                out = vc.evaluate_venue_gate(mcg_game(kickoff_utc="2027-09-10T00:35:00Z"), bad, POLICY)
                self.assertFalse(out["priceable"])
                self.assertEqual(out["blockers"], ["M2_HFA_PRIOR_INVALID"])


class Sensitivity(unittest.TestCase):
    def test_no_flip_passes(self):
        result = vc.venue_sensitivity_check(lambda h: 0.60 + 0.02 * h, (0.0, 0.9), 0.55)
        self.assertIsNone(result["blocker"])
        self.assertEqual(result["governed_model_p"], 0.60)

    def test_flip_blocks(self):
        result = vc.venue_sensitivity_check(lambda h: 0.54 + 0.02 * h, (0.0, 0.9), 0.55)
        self.assertEqual(result["blocker"], "VENUE_SENSITIVITY")


if __name__ == "__main__":
    unittest.main()
