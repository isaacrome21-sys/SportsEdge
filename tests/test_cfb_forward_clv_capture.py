import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cfb_forward_clv_capture", ROOT / "scripts/cfb_forward_clv_capture.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


class CFBForwardCLVCaptureTests(unittest.TestCase):
    def setUp(self):
        self.policy_path = ROOT / "config/cfb_forward_clv_policy_v1.json"
        self.policy = mod.load_policy(self.policy_path)

    def test_policy_is_fail_closed_and_first_slate_is_sep19(self):
        self.assertEqual(self.policy["version"], "1.0.2")
        self.assertEqual(self.policy["first_admissible_slate_ct"], "2026-09-19")
        self.assertTrue(self.policy["row_admissibility"]["model_p_required"])
        self.assertTrue(self.policy["row_admissibility"]["layer_b_rows_prohibited"])
        self.assertTrue(self.policy["row_admissibility"]["backfill_prohibited"])
        close = self.policy["capture_schedule"]["close"]
        self.assertEqual(close["selection_rule"], "LAST_SUCCESSFUL_VALID_CAPTURE")
        self.assertTrue(close["post_start_capture_prohibited"])

    def test_first_opener_is_monday_before_sep19_slate(self):
        old = datetime.fromisoformat("2026-09-07T09:00:00-05:00").astimezone(timezone.utc)
        self.assertIsNone(mod.opener_window(old, self.policy))
        valid = datetime.fromisoformat("2026-09-14T09:00:00-05:00").astimezone(timezone.utc)
        start, end = mod.opener_window(valid, self.policy)
        self.assertEqual(start.astimezone(mod.CT).date().isoformat(), "2026-09-19")
        self.assertEqual((end - start).days, 3)

    def test_team_match_requires_unique_home_and_away(self):
        odds = {"home_team": "Kentucky Wildcats", "away_team": "Alabama Crimson Tide"}
        espn = [{"espn_event_id": "1", "home_aliases": {mod.norm("Kentucky Wildcats")}, "away_aliases": {mod.norm("Alabama Crimson Tide")}}]
        self.assertEqual(mod.match_espn(odds, espn)["espn_event_id"], "1")
        self.assertIsNone(mod.match_espn(odds, espn + [dict(espn[0], espn_event_id="2")]))

    def test_status_unknown_inprogress_and_postponed_fail_closed(self):
        received = datetime.now(timezone.utc)
        pre = {"status_state": "pre", "status_name": "STATUS_SCHEDULED", "completed": False}
        self.assertTrue(mod.status_is_pre(pre, received, self.policy)[0])
        self.assertFalse(mod.status_is_pre({"status_state": "in", "status_name": "STATUS_IN_PROGRESS", "completed": False}, received, self.policy)[0])
        ok, reason = mod.status_is_pre({"status_state": "pre", "status_name": "STATUS_POSTPONED", "completed": False}, received, self.policy)
        self.assertFalse(ok)
        self.assertEqual(reason, "VOID_POSTPONED")

    def test_market_timestamp_does_not_fake_two_sided_synchronization(self):
        now = datetime.now(timezone.utc)
        event = {"bookmakers": [{"key": "draftkings", "last_update": mod.iso(now), "markets": [{"key": "spreads", "last_update": mod.iso(now), "outcomes": [{"name": "A", "point": -3, "price": -110}, {"name": "B", "point": 3, "price": -110}]}]}]}
        rows = mod.market_rows(event, now, self.policy)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["two_sided_skew_seconds"] is None for r in rows))
        self.assertTrue(all(r["two_sided_synchronization_status"] == "PROVIDER_MARKET_LEVEL_TIMESTAMP_ONLY_UNVERIFIED" for r in rows))
        self.assertTrue(all(r["promotion_grade_quote_eligible"] is False for r in rows))
        self.assertTrue(all("BOOK_LIMIT_STATUS_UNKNOWN" in r["promotion_grade_blockers"] for r in rows))
        self.assertTrue(all("TWO_SIDED_SYNC_UNVERIFIED" in r["promotion_grade_blockers"] for r in rows))

    def test_exact_contract_alt_ladders_are_frozen(self):
        self.assertIn("alternate_spreads", mod.CLOSE_MARKETS)
        self.assertIn("alternate_totals", mod.CLOSE_MARKETS)
        clv = self.policy["clv_definition"]
        self.assertEqual(clv["basis"], "EXACT_ORIGINAL_CONTRACT")
        self.assertTrue(clv["alternate_line_capture_required"])
        self.assertFalse(clv["normal_approx_v1"]["permitted_for_promotion_evidence"])

    def test_first_play_attestation_selects_last_valid_pre_start_snapshot(self):
        first_play = datetime.fromisoformat("2026-09-19T19:30:10+00:00")
        payload = {"drives": {"previous": [{"plays": [{"wallclock": mod.iso(first_play)}]}]}}
        self.assertEqual(mod.first_play_from_summary(payload), first_play)

    def test_selected_path_is_separate_append_only_artifact(self):
        p = Path("root/cfb_forward_clv/captures/2026-09-19/close_raw/evt/20260919T192900000000Z.json")
        self.assertEqual(mod.selected_path_for(p), Path("root/cfb_forward_clv/captures/2026-09-19/close_selected/evt.json"))

    def test_write_once_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.json"
            mod.write_once(p, {"a": 1})
            with self.assertRaises(mod.CaptureError):
                mod.write_once(p, {"a": 2})

    def test_small_cluster_reference_is_not_iid(self):
        req = self.policy["evidence_requirements_per_market"]
        self.assertEqual(req["minimum_slate_clusters"], 12)
        se = req["standard_errors"]
        self.assertTrue(se["iid_fallback_prohibited"])
        self.assertEqual(se["small_sample_reference"], "STUDENT_T_DF_G_MINUS_1")
        self.assertEqual(se["two_sided_95_critical_rule"], "MAX_OF_T_STAT_MIN_AND_T_0.975_DF_G_MINUS_1")


if __name__ == "__main__":
    unittest.main()
