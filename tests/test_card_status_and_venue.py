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

    def test_props_no_engine(self):
        row = cs.resolve_row_status(engine_exists=False, model_p=None, blockers=[], promoted=False)
        self.assertEqual(row["status"], cs.NO_ENGINE)

    def test_priced_but_unpromoted_is_blocked_not_pass(self):
        row = cs.resolve_row_status(engine_exists=True, model_p=0.52, blockers=[],
                                    promoted=False, edge=-0.01, edge_floor=0.03)
        self.assertEqual(row["status"], cs.BLOCKED)

    def test_missing_model_p_needs_reason(self):
        with self.assertRaises(ValueError):
            cs.resolve_row_status(engine_exists=True, model_p=None, blockers=[], promoted=True)

    def test_no_frozen_floor_blocks(self):
        row = cs.resolve_row_status(engine_exists=True, model_p=0.6, blockers=[],
                                    promoted=True, edge=0.05, edge_floor=None)
        self.assertEqual(row["reasons"], ["NO_FROZEN_EDGE_FLOOR"])

    def test_pass_and_official(self):
        kw = dict(engine_exists=True, model_p=0.6, blockers=[], promoted=True, edge_floor=0.03)
        self.assertEqual(cs.resolve_row_status(edge=0.01, **kw)["status"], cs.PASS)
        self.assertEqual(cs.resolve_row_status(edge=0.04, **kw)["status"], cs.OFFICIAL)

    def test_integrity_rejects_retracted_card_shape(self):
        bad = [{"status": "PASS", "model_p": None, "confidence": None}]
        with self.assertRaises(ValueError):
            cs.assert_card_integrity(bad)
        bad = [{"status": "BLOCKED", "reasons": ["NOT_PROMOTED"], "confidence": "72%"}]
        with self.assertRaises(ValueError):
            cs.assert_card_integrity(bad)

    def test_official_integrity_requires_model_p(self):
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([{"status": "OFFICIAL", "model_p": None}])


TRIAL_POLICY = cs.load_trial_policy(ROOT / "config/trial_policy_v1.json")
MODEL_SHA = "a" * 64
OLD_MODEL_SHA = "b" * 64
QUOTE = {"book": "fanduel", "price_american": -108, "retrieved_at": "2027-09-10T23:00:00Z",
         "model_artifact_sha": MODEL_SHA}


def ledger(base=1.0, slates=40, per=5, model_sha=MODEL_SHA, policy_sha=None):
    policy_sha = policy_sha or TRIAL_POLICY["_sha256"]
    return [{"slate_date": f"d{g}", "clv_pp": base + (0.5 if g % 2 == 0 else -0.5),
             "model_artifact_sha": model_sha, "trial_policy_sha256": policy_sha}
            for g in range(slates) for _ in range(per)]


def trial(**over):
    kw = dict(engine_exists=True, model_p=0.56, blockers=[], promoted=False,
              edge=0.035, trial_policy=TRIAL_POLICY, quote=QUOTE)
    kw.update(over)
    return cs.resolve_row_status(**kw)


def rendered_trial(**over):
    row = dict(trial(), model_p=0.56, edge=0.035, sport="NFL",
               slate_date="2026-09-13", market_id="m0")
    row.update(over)
    return row


class TrialTier(unittest.TestCase):
    def test_unpromoted_real_price_over_threshold_is_paper_trial(self):
        row = trial()
        self.assertEqual(row["status"], cs.TRIAL)
        self.assertEqual(row["stake_units"], 0.0)
        self.assertEqual(row["trial_stage"], cs.PAPER)
        self.assertFalse(row["confidence_allowed"])
        self.assertEqual(row["trial_policy_sha256"], TRIAL_POLICY["_sha256"])
        self.assertEqual(row["model_artifact_sha"], QUOTE["model_artifact_sha"])
        self.assertEqual(row["trial_stage_evidence"]["settled"], 0)

    def test_below_threshold_blocked(self):
        row = trial(edge=0.029)
        self.assertEqual(row["status"], cs.BLOCKED)
        self.assertIn("BELOW_TRIAL_THRESHOLD", row["reasons"])

    def test_data_blocker_prevents_trial(self):
        row = trial(blockers=["VENUE_SENSITIVITY"])
        self.assertEqual(row["reasons"], ["VENUE_SENSITIVITY", "NOT_PROMOTED"])
        self.assertEqual(row["status"], cs.BLOCKED)

    def test_no_model_p_never_trial(self):
        row = trial(model_p=None, blockers=["VENUE_EXCLUDED"])
        self.assertEqual(row["status"], cs.BLOCKED)

    def test_no_engine_never_trial(self):
        self.assertEqual(trial(engine_exists=False)["status"], cs.NO_ENGINE)

    def test_missing_quote_fields_blocked(self):
        q = dict(QUOTE, model_artifact_sha="")
        row = trial(quote=q)
        self.assertIn("TRIAL_ROW_INCOMPLETE", row["reasons"])

    def test_invalid_model_artifact_sha_blocks(self):
        q = dict(QUOTE, model_artifact_sha="abc123")
        row = trial(quote=q)
        self.assertEqual(row["status"], cs.BLOCKED)
        self.assertIn("TRIAL_MODEL_ARTIFACT_SHA_INVALID", row["reasons"])

    def test_promoted_without_floor_stays_blocked(self):
        row = trial(promoted=True, edge_floor=None)
        self.assertEqual(row["status"], cs.BLOCKED)
        self.assertEqual(row["reasons"], ["NO_FROZEN_EDGE_FLOOR"])

    def test_micro_stage_is_derived_from_settled_ledger(self):
        row = trial(settled_trial_rows=ledger(1.0))
        self.assertEqual(row["trial_stage"], cs.MICRO)
        self.assertEqual(row["stake_units"], 0.25)
        self.assertGreaterEqual(row["trial_stage_evidence"]["settled"], 200)
        self.assertGreaterEqual(row["trial_stage_evidence"]["slate_clusters"], 20)

    def test_insufficient_or_stale_evidence_stays_paper(self):
        self.assertEqual(trial(settled_trial_rows=ledger(1.0, slates=10))["trial_stage"], cs.PAPER)
        self.assertEqual(trial(settled_trial_rows=ledger(1.0, model_sha=OLD_MODEL_SHA))["trial_stage"], cs.PAPER)

    def test_cap_keeps_top_edges_per_sport(self):
        rows = []
        for k in range(7):
            r = trial(edge=0.03 + k / 1000)
            r.update(sport="NFL", slate_date="2026-09-13", market_id=f"m{k}", edge=0.03 + k / 1000)
            rows.append(r)
        mlb = trial()
        mlb.update(sport="MLB", slate_date="2026-09-13", market_id="x", edge=0.031)
        capped = cs.apply_trial_cap(rows + [mlb], TRIAL_POLICY)
        kept = [r["market_id"] for r in capped if r["status"] == cs.TRIAL]
        self.assertEqual(kept, ["m2", "m3", "m4", "m5", "m6", "x"])
        dropped = [r for r in capped if "TRIAL_CAP_EXCEEDED" in r["reasons"]]
        self.assertEqual(len(dropped), 2)
        self.assertIsNone(dropped[0]["stake_units"])

    def test_cap_is_per_sport_per_slate(self):
        rows = []
        for slate in ("2026-09-13", "2026-09-20"):
            for k in range(6):
                r = trial(edge=0.04 + k / 1000)
                r.update(sport="NFL", slate_date=slate, market_id=f"{slate}-m{k}", edge=0.04 + k / 1000)
                rows.append(r)
        capped = cs.apply_trial_cap(rows, TRIAL_POLICY)
        self.assertEqual(sum(r["status"] == cs.TRIAL for r in capped), 10)
        self.assertEqual(sum("TRIAL_CAP_EXCEEDED" in r["reasons"] for r in capped), 2)

    def test_stage_needs_sample_and_clv(self):
        good = cs.trial_stage_for_market(ledger(1.0), TRIAL_POLICY, model_artifact_sha=MODEL_SHA)
        self.assertEqual(good["stage"], cs.MICRO)
        self.assertAlmostEqual(good["clv_t_stat"], 1.0 / ((40 / 39) * 250 / 40000) ** 0.5, places=6)
        self.assertEqual(cs.trial_stage_for_market(ledger(0.3), TRIAL_POLICY, model_artifact_sha=MODEL_SHA)["stage"], cs.PAPER)
        self.assertEqual(cs.trial_stage_for_market(ledger(1.0, slates=39), TRIAL_POLICY, model_artifact_sha=MODEL_SHA)["stage"], cs.PAPER)
        self.assertEqual(cs.trial_stage_for_market([], TRIAL_POLICY, model_artifact_sha=MODEL_SHA)["stage"], cs.PAPER)

    def test_stage_evidence_clock_rejects_stale_model_and_policy(self):
        rows = ledger(2.0, model_sha=OLD_MODEL_SHA) + ledger(2.0, model_sha=MODEL_SHA, policy_sha="c" * 64)
        result = cs.trial_stage_for_market(rows, TRIAL_POLICY, model_artifact_sha=MODEL_SHA)
        self.assertEqual(result["stage"], cs.PAPER)
        self.assertEqual(result["settled"], 0)

    def test_stage_requires_current_model_hash(self):
        with self.assertRaises(ValueError):
            cs.trial_stage_for_market([], TRIAL_POLICY, model_artifact_sha="")
        with self.assertRaises(ValueError):
            cs.trial_stage_for_market([], TRIAL_POLICY, model_artifact_sha="abc123")

    def test_integrity_checks_trial_rows(self):
        row = rendered_trial()
        cs.assert_card_integrity([row], TRIAL_POLICY)
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([dict(row, stake_units=1.0)], TRIAL_POLICY)
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([dict(row, confidence="70%")], TRIAL_POLICY)
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([dict(row, trial_policy_sha256="stale")], TRIAL_POLICY)
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([dict(row, reasons=["VENUE_SENSITIVITY", "NOT_PROMOTED"])], TRIAL_POLICY)
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([dict(row, edge=0.01)], TRIAL_POLICY)
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([dict(row, kelly_fraction=0.25)], TRIAL_POLICY)
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([dict(row, sport="")], TRIAL_POLICY)
        missing_slate = dict(row)
        missing_slate.pop("slate_date")
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([missing_slate], TRIAL_POLICY)
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([{"status": "BLOCKED", "reasons": ["X"], "stake_units": 0.25}])

    def test_integrity_checks_micro_evidence_snapshot(self):
        micro = trial(settled_trial_rows=ledger(1.0))
        row = dict(micro, model_p=0.56, edge=0.035, sport="NFL",
                   slate_date="2026-09-13", market_id="m0")
        cs.assert_card_integrity([row], TRIAL_POLICY)
        bad_evidence = dict(row["trial_stage_evidence"], settled=199)
        with self.assertRaises(ValueError):
            cs.assert_card_integrity([dict(row, trial_stage_evidence=bad_evidence)], TRIAL_POLICY)

    def test_integrity_enforces_rendered_trial_cap(self):
        rows = []
        for k in range(6):
            rows.append(rendered_trial(market_id=f"m{k}"))
        with self.assertRaises(ValueError):
            cs.assert_card_integrity(rows, TRIAL_POLICY)


if __name__ == "__main__":
    unittest.main()
