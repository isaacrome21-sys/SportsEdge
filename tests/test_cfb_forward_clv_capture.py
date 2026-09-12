import importlib.util
import json
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("cfb_forward_clv_capture", ROOT / "scripts/cfb_forward_clv_capture.py")
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(mod)


class Resp:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode()
        self.headers = {"x-requests-remaining": "999", "x-requests-used": "1", "x-requests-last": "1"}
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


class Clock:
    def __init__(self, now): self.now = now
    def get(self): return self.now
    def sleep(self, seconds): self.now += timedelta(seconds=seconds)


class CFBForwardCLVCaptureTests(unittest.TestCase):
    def setUp(self):
        self.policy_path = ROOT / "config/cfb_forward_clv_policy_v1.json"
        self.policy = mod.load_policy(self.policy_path)

    def test_policy_fail_closed(self):
        self.assertEqual(self.policy["status"], "FROZEN")
        self.assertEqual(self.policy["first_admissible_slate_ct"], "2026-09-19")
        self.assertTrue(self.policy["row_admissibility"]["model_p_required"])
        self.assertTrue(self.policy["row_admissibility"]["layer_b_rows_prohibited"])
        self.assertTrue(self.policy["row_admissibility"]["backfill_prohibited"])
        self.assertTrue(self.policy["clv_definition"]["alternate_line_capture_required"])
        self.assertFalse(self.policy["clv_definition"]["normal_approx_v1"]["permitted_for_promotion_evidence"])

    def test_sep12_opener_cannot_be_admissible(self):
        now = datetime.fromisoformat("2026-09-07T09:05:00-05:00").astimezone(timezone.utc)
        self.assertIsNone(mod.opener_window(now, self.policy))

    def test_first_admissible_opener_is_sep14_for_sep19_slate(self):
        now = datetime.fromisoformat("2026-09-14T09:05:00-05:00").astimezone(timezone.utc)
        start, end = mod.opener_window(now, self.policy)
        self.assertEqual(start.astimezone(mod.CT).date().isoformat(), "2026-09-19")
        self.assertEqual((end - start).days, 3)

    def test_close_candidates_never_backfill_sep12(self):
        start = datetime.fromisoformat("2026-09-12T19:30:00+00:00")
        now = start - timedelta(minutes=10)
        events = [{"id": "old", "commence_time": mod.iso(start), "home_team": "A", "away_team": "B"}]
        self.assertEqual(mod.close_candidates(events, now, self.policy), [])

    def test_close_candidate_inside_frozen_window(self):
        start = datetime.fromisoformat("2026-09-19T19:30:00+00:00")
        now = start - timedelta(minutes=10)
        events = [{"id": "e1", "commence_time": mod.iso(start), "home_team": "A", "away_team": "B"}]
        self.assertEqual([e["id"] for e in mod.close_candidates(events, now, self.policy)], ["e1"])

    def test_unknown_limit_status_is_never_promotion_grade(self):
        event = {"bookmakers": [{"key": "draftkings", "last_update": "2026-09-19T19:28:00Z", "markets": [{
            "key": "spreads", "last_update": "2026-09-19T19:28:00Z",
            "outcomes": [{"name": "A", "point": -3.0, "price": -110}, {"name": "B", "point": 3.0, "price": -110}],
        }]}]}
        rows = mod.market_rows(event, datetime.fromisoformat("2026-09-19T19:28:30+00:00"))
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["book_limit_status"] == "UNKNOWN_PROVIDER_NOT_EXPOSED" for r in rows))
        self.assertTrue(all(r["promotion_grade_quote_eligible"] is False for r in rows))

    def test_close_requests_alt_ladders_and_stays_pregame(self):
        kickoff = datetime.now(timezone.utc) + timedelta(minutes=2)
        clock = Clock(kickoff - timedelta(minutes=2))
        urls = []
        payload = {"id": "evt", "commence_time": mod.iso(kickoff), "home_team": "Home", "away_team": "Away",
                   "bookmakers": [{"key": "draftkings", "last_update": mod.iso(clock.get()), "markets": [
                       {"key": "spreads", "last_update": mod.iso(clock.get()), "outcomes": [
                           {"name": "Home", "point": -2.5, "price": -110}, {"name": "Away", "point": 2.5, "price": -110}]},
                       {"key": "alternate_spreads", "last_update": mod.iso(clock.get()), "outcomes": [
                           {"name": "Home", "point": -3.0, "price": 105}, {"name": "Away", "point": 3.0, "price": -125}]},
                   ]}]}
        def opener(req, timeout=30):
            urls.append(req.full_url)
            return Resp(payload)
        event = {"id": "evt", "commence_time": mod.iso(kickoff), "home_team": "Home", "away_team": "Away"}
        with tempfile.TemporaryDirectory() as td:
            result = mod.capture_close_event(event=event, now_fn=clock.get, sleep_fn=clock.sleep,
                policy_path=self.policy_path, policy=self.policy, out_dir=Path(td), keys=["k"], opener=opener)
            self.assertEqual(result["status"], "TARGET_T_MINUS_60")
            saved = json.loads(Path(result["path"]).read_text())
            self.assertTrue(saved["exact_contract_alt_ladders_requested"])
            self.assertIn("alternate_spreads", saved["requested_markets"])
            self.assertIn("alternate_totals", saved["requested_markets"])
            self.assertLess(datetime.fromisoformat(saved["captured_at_utc"].replace("Z", "+00:00")), kickoff)
            self.assertTrue(any("alternate_spreads" in urllib.parse.unquote(u) for u in urls))

    def test_small_cluster_reference_is_frozen(self):
        se = self.policy["evidence_requirements_per_market"]["standard_errors"]
        self.assertEqual(se["small_sample_reference"], "STUDENT_T_DF_G_MINUS_1")
        self.assertEqual(se["two_sided_95_critical_rule"], "MAX_OF_T_STAT_MIN_AND_T_0.975_DF_G_MINUS_1")


if __name__ == "__main__":
    unittest.main()
