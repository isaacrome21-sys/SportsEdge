import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


vc = _load("venue_contract", "sportsedge/sports/nfl/venue_contract.py")
cs = _load("card_status", "sportsedge/core/card_status.py")
POLICY = vc.load_policy(ROOT / "config/nfl_venue_policy_v1.json")
HFA = 1.8  # stand-in for the M2 prior; tests only check relative behavior


def mcg_game(**over):
    g = {
        "home_team": "LA", "away_team": "SF", "neutral_site": True,
        "venue_country": "AU", "venue_id": "MCG",
        "kickoff_utc": "2026-09-11T00:35:00Z",
        "weather_observed_at": "2026-09-10T23:00:00Z",
    }
    g.update(over)
    return g


class VenueGate(unittest.TestCase):
    def test_tonight_mcg_not_retroactive(self):
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
        g = {"home_team": "KC", "away_team": "DEN", "neutral_site": False,
             "venue_country": "US", "kickoff_utc": "2026-09-13T17:00:00Z"}
        out = vc.evaluate_venue_gate(g, HFA, POLICY)
        self.assertTrue(out["priceable"])
        self.assertEqual(out["governed_hfa"], HFA)
        self.assertTrue(out["in_primary_confirmation_test"])

    def test_invalid_hfa_prior_blocks_instead_of_crashing(self):
        out = vc.evaluate_venue_gate(mcg_game(), "bad", POLICY)
        self.assertEqual(out["blockers"], ["M2_HFA_PRIOR_INVALID"])
        self.assertFalse(out["priceable"])

    def test_missing_neutral_flag_blocks(self):
        out = vc.evaluate_venue_gate(mcg_game(neutral_site=None), HFA, POLICY)
        self.assertEqual(out["blockers"], ["VENUE_CLASS_UNRESOLVED"])

    def test_non_neutral_abroad_is_inconsistent(self):
        out = vc.evaluate_venue_gate(mcg_game(neutral_site=False), HFA, POLICY)
        self.assertEqual(out["blockers"], ["VENUE_CLASS_INCONSISTENT"])

    def test_unregistered_venue_blocks(self):
        out = vc.evaluate_venue_gate(
            mcg_game(venue_id="WEMBLEY", venue_country="GB", kickoff_utc="2027-10-10T13:30:00Z"), HFA, POLICY)
        self.assertEqual(out["blockers"], ["ENVIRONMENT_PROFILE_MISSING"])

    def test_outdoor_without_weather_blocks(self):
        out = vc.evaluate_venue_gate(
            mcg_game(kickoff_utc="2027-09-10T00:35:00Z", weather_observed_at=None), HFA, POLICY)
        self.assertIn("ENVIRONMENT_WEATHER_MISSING", out["blockers"])
        self.assertFalse(out["priceable"])

    def test_tz_shift_wraps(self):
        self.assertEqual(vc.tz_shift_hours("SF", "Australia/Melbourne", "2026-09-11T00:35:00Z"), -7.0)
        d = vc.travel_differential("JAX", "SEA", "Europe/London", "2026-10-11T13:30:00Z")
        self.assertEqual((d["home_tz_shift_hours"], d["away_tz_shift_hours"]), (5.0, 8.0))
        self.assertEqual(d["tz_shift_abs_differential"], -3.0)


class Sensitivity(unittest.TestCase):
    def test_no_flip_passes(self):
        r = vc.venue_sensitivity_check(lambda h: 0.60 + 0.02 * h, (0.0, 0.9), 0.55)
        self.assertIsNone(r["blocker"])
        self.assertEqual(r["governed_model_p"], 0.60)

    def test_flip_blocks(self):
        r = vc.venue_sensitivity_check(lambda h: 0.54 + 0.02 * h, (0.0, 0.9), 0.55)
        self.assertEqual(r["blocker"], "VENUE_SENSITIVITY")


class CardStatus(unittest.TestCase):
    def test_tonight_game_rows(self):
        row = cs.resolve_row_status(engine_exists=True, model_p=None,
                                    blockers=["VENUE_EXCLUDED"], promoted=False)
        self.assertEqual(row["status"], cs.BLOCKED)
        self.assertEqual(row["reasons"], ["VENUE_EXCLUDED", "NOT_PROMOTED"])
        self.assertFalse(row["confidence_allowed"])
        self.assertFalse(row["stake_allowed"])

    def test_props_no_engine(self):
        row = cs.resolve_row_status(engine_exists=False, model_p=None, blockers=[], promoted=False)
        self.assertEqual(row["status"], cs.NO_ENGINE)

    def test_priced_positive_edge_unpromoted_is_trial_not_bet(self):
        row = cs.resolve_row_status(engine_exists=True, model_p=0.56, blockers=[],
                                    promoted=False, edge=0.02, edge_floor=None)
        self.assertEqual(row["status"], cs.TRIAL)
        self.assertTrue(row["paper_only"])
        self.assertFalse(row["stake_allowed"])

    def test_not_promoted_marker_is_not_a_hard_blocker_for_trial(self):
        row = cs.resolve_row_status(engine_exists=True, model_p=0.56,
                                    blockers=["NOT_PROMOTED"], promoted=False,
                                    edge=0.02, edge_floor=None)
        self.assertEqual(row["status"], cs.TRIAL)

    def test_unpromoted_nonpositive_edge_is_not_trial(self):
        row = cs.resolve_row_status(engine_exists=True, model_p=0.52, blockers=[],
                                    promoted=False, edge=-0.01, edge_floor=None)
        self.assertEqual(row["status"], cs.BLOCKED)
        self.assertIn("NO_POSITIVE_MODEL_EDGE", row["reasons"])

    def test_missing_model_p_needs_reason(self):
        with self.assertRaises(ValueError):
            cs.resolve_row_status(engine_exists=True, model_p=None, blockers=[], promoted=True)

    def test_no_frozen_floor_blocks_promoted_row(self):
        row = cs.resolve_row_status(engine_exists=True, model_p=0.6, blockers=[],
                                    promoted=True, edge=0.05, edge_floor=None)
        self.assertEqual(row["reasons"], ["NO_FROZEN_EDGE_FLOOR"])

    def test_pass_and_official(self):
        kw = dict(engine_exists=True, model_p=0.6, blockers=[], promoted=True, edge_floor=0.03)
        self.assertEqual(cs.resolve_row_status(edge=0.01, **kw)["status"], cs.PASS)
        self.assertEqual(cs.resolve_row_status(edge=0.04, **kw)["status"], cs.OFFICIAL)

    def test_integrity_rejects_retracted_card_shape_and_trial_stake(self):
        bad = [{"status": "PASS", "model_p": None, "confidence": None}]
        with self.assertRaises(ValueError):
            cs.assert_card_integrity(bad)
        bad = [{"status": "BLOCKED", "reasons": ["NOT_PROMOTED"], "confidence": "72%"}]
        with self.assertRaises(ValueError):
            cs.assert_card_integrity(bad)
        bad = [{"status": "TRIAL", "model_p": 0.57, "edge": 0.02,
                "paper_only": True, "units": 0.5}]
        with self.assertRaises(ValueError):
            cs.assert_card_integrity(bad)
        good = [{"status": "TRIAL", "model_p": 0.57, "edge": 0.02,
                 "paper_only": True, "units": None, "stake": None,
                 "confidence": None}]
        cs.assert_card_integrity(good)


if __name__ == "__main__":
    unittest.main()
