from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from sportsedge.core.clv.football_forward_v2 import (
    CLOSE_DEFINITION_ID,
    FootballForwardV2Error,
    SPORT_KEYS,
    build_close_record,
    coverage,
    plan_due_bulk_sports,
    power_fair_pair,
)

ROOT = Path(__file__).resolve().parents[1]


class FootballForwardV2Tests(unittest.TestCase):
    def candidate(self, *, sport="CFB", decision_id="d1", start="2026-09-12T00:00:00Z"):
        return {
            "decision_id": decision_id,
            "evidence_unit_id": "e" * 64,
            "sport": sport,
            "game_id": f"g-{decision_id}",
            "game_start_ts": start,
            "market": "spreads",
            "side": "HOME",
            "book": "draftkings",
            "selected_price": -110,
            "opposite_price": -110,
            "price_observed_at": "2026-09-11T22:30:00Z",
            "qualifies_for_evidence": True,
        }

    def test_policy_covers_nfl_and_cfb_and_is_not_activated(self):
        p = json.loads((ROOT / "config/football_forward_capture_policy_v2.json").read_text())
        self.assertEqual(SPORT_KEYS["NFL"], "americanfootball_nfl")
        self.assertEqual(SPORT_KEYS["CFB"], "americanfootball_ncaaf")
        self.assertEqual(p["close_definition_id"], CLOSE_DEFINITION_ID)
        self.assertEqual(p["devig_method"], "POWER_V1")
        self.assertEqual(p["status"], "PROSPECTIVE_UNACTIVATED")
        self.assertFalse(p["promotion_authority"])
        self.assertFalse(p["evidence_clock_authority"])

    def test_bulk_plan_costs_one_call_per_due_sport_not_per_game(self):
        now = datetime(2026, 9, 11, 23, 45, tzinfo=timezone.utc)
        rows = [
            self.candidate(sport="CFB", decision_id="c1"),
            self.candidate(sport="CFB", decision_id="c2"),
            self.candidate(sport="NFL", decision_id="n1"),
        ]
        plan = plan_due_bulk_sports(rows, [], now=now)
        self.assertEqual(plan["provider_request_count"], 2)
        self.assertEqual(plan["due_sports"], ["CFB", "NFL"])
        self.assertEqual(plan["due_decision_ids"]["CFB"], ["c1", "c2"])

    def test_power_devig_is_not_proportional_when_prices_are_asymmetric(self):
        p1, p2 = power_fair_pair(-150, +125)
        raw1 = (150 / 250) / ((150 / 250) + (100 / 225))
        self.assertAlmostEqual(p1 + p2, 1.0, places=12)
        self.assertNotAlmostEqual(p1, raw1, places=8)

    def test_close_record_is_separate_and_window_bound(self):
        row = self.candidate()
        close = build_close_record(
            candidate=row,
            observed_at="2026-09-11T23:50:00Z",
            selected_price=-108,
            opposite_price=-112,
            snapshot_sha256="a" * 64,
        )
        self.assertEqual(close["decision_id"], "d1")
        self.assertEqual(close["devig_method"], "POWER_V1")
        self.assertEqual(close["close_definition_id"], CLOSE_DEFINITION_ID)
        with self.assertRaisesRegex(FootballForwardV2Error, "CLOSE_OUTSIDE_WINDOW"):
            build_close_record(
                candidate=row,
                observed_at="2026-09-11T23:30:00Z",
                selected_price=-108,
                opposite_price=-112,
                snapshot_sha256="b" * 64,
            )

    def test_coverage_keeps_misses_in_denominator(self):
        rows = [self.candidate(decision_id="d1"), self.candidate(decision_id="d2")]
        report = coverage(rows, [{"decision_id": "d1"}])
        self.assertEqual(report["eligible_candidates"], 2)
        self.assertEqual(report["captured_closes"], 1)
        self.assertEqual(report["missed_closes"], 1)
        self.assertEqual(report["coverage"], 0.5)

    def test_one_sided_candidate_is_rejected_from_v2_capture(self):
        row = self.candidate()
        row["opposite_price"] = None
        with self.assertRaisesRegex(FootballForwardV2Error, "FIELDS_MISSING"):
            plan_due_bulk_sports([row], [], now=datetime(2026, 9, 11, 23, 45, tzinfo=timezone.utc))


if __name__ == "__main__":
    unittest.main()
