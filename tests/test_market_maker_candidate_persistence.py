import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.recheck_market_maker_candidate_persistence import classify_candidate


UTC = timezone.utc
POLICY_PATH = Path("config/market_maker_radar_v2.json")


def policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def candidate(**overrides):
    base = {
        "candidate_id": "cand-1",
        "source_family_id": "PINNACLE_TO_FANDUEL_STALE_PRICE_H2H_V1",
        "candidate_created_at": "2026-09-14T10:00:00Z",
        "event_id": "americanfootball_nfl:2026-09-20:seahawks@cardinals",
        "market": "h2h",
        "outcome": "seahawks",
        "soft_book": "fanduel",
        "point": None,
        "offered_price_american": 150,
    }
    base.update(overrides)
    return base


def fanduel_event(price=150, point=None, market="h2h"):
    return {
        "book": "fanduel",
        "provider_event_id": 123,
        "home_team": "Arizona Cardinals",
        "away_team": "Seattle Seahawks",
        "commence_time": "2026-09-20T20:05:00Z",
        "raw_sha256": "a" * 64,
        "quotes": [
            {
                "market": market,
                "designation": "away" if market != "totals" else "over",
                "outcome": "Seattle Seahawks" if market != "totals" else "Over",
                "point": point,
                "american_price": price,
            }
        ],
    }


class PolicyTests(unittest.TestCase):
    def test_roi_clv_and_checkpoint_roles_are_frozen(self):
        p = policy()
        self.assertEqual(p["grading"]["primary_metric"], "REALIZED_ROI_ON_FILLED_WAGERS")
        self.assertEqual(p["grading"]["process_metric"], "CLV")
        self.assertEqual(p["grading"]["clv_role"], "DETECTOR_PROCESS_CHECK_NOT_EDGE_VALIDATION")
        self.assertEqual(p["grading"]["offered_price_roi_role"], "OPTIMISTIC_DIAGNOSTIC_ONLY_NOT_PRIMARY")
        checkpoints = p["grading"]["evaluation_checkpoints"]
        self.assertEqual(checkpoints["candidate_n"], [100, 250, 500, 1000])
        self.assertEqual(checkpoints["persisted_n"], [100, 250, 500, 1000])
        self.assertEqual(checkpoints["filled_n"], [100, 250, 500, 1000])
        self.assertTrue(checkpoints["no_optional_looks"])

    def test_run_it_price_signals_are_one_independence_class(self):
        rule = policy()["run_it_independence"]
        self.assertFalse(rule["counts_as_independent_context_class"])
        self.assertEqual(rule["independence_group_id"], "HARD_MARKET_PRICE_MOVEMENT_V1")
        self.assertIn("MARKET_MAKER_LEAD", rule["dedupe_signal_classes"])
        self.assertIn("STALE_SOFT_PRICE", rule["dedupe_signal_classes"])


class PersistenceTests(unittest.TestCase):
    def _classify(self, cand, events, seconds=30):
        created = datetime(2026, 9, 14, 10, 0, 0, tzinfo=UTC)
        rechecked = created + timedelta(seconds=seconds)
        return classify_candidate(
            cand,
            events,
            rechecked_at=rechecked,
            request_started_at=rechecked - timedelta(seconds=1),
            retrieved_at=rechecked,
            policy=policy(),
        )

    def test_exact_price_persists_at_frozen_offset(self):
        record = self._classify(candidate(), [fanduel_event(price=150)])
        self.assertEqual(record["persistence_status"], "PERSISTED_EXACT_PRICE")
        self.assertTrue(record["persisted_exact_contract"])
        self.assertTrue(record["persisted_price_grade_eligible"])
        self.assertFalse(record["fill_proof"])

    def test_worse_price_is_recorded_not_backfilled_to_offer(self):
        record = self._classify(candidate(), [fanduel_event(price=140)])
        self.assertEqual(record["persistence_status"], "MOVED_WORSE_PRICE")
        self.assertEqual(record["offered_price_american"], 150)
        self.assertEqual(record["persisted_price_american"], 140)
        self.assertTrue(record["persisted_price_grade_eligible"])

    def test_changed_line_is_not_treated_as_same_contract(self):
        cand = candidate(
            source_family_id="PINNACLE_TO_FANDUEL_STALE_PRICE_SPREADS_V1",
            market="spreads",
            point=4.5,
        )
        event = fanduel_event(price=-110, point=3.5, market="spreads")
        record = self._classify(cand, [event])
        self.assertEqual(record["persistence_status"], "EXACT_CONTRACT_NOT_AVAILABLE_AT_RECHECK")
        self.assertFalse(record["persisted_price_grade_eligible"])

    def test_outside_fixed_offset_tolerance_is_not_grade_eligible(self):
        record = self._classify(candidate(), [fanduel_event(price=150)], seconds=45)
        self.assertFalse(record["within_offset_tolerance"])
        self.assertFalse(record["persisted_price_grade_eligible"])


if __name__ == "__main__":
    unittest.main()
