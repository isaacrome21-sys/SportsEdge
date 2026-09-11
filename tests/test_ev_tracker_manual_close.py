import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location("ev_tracker_manual_close_tested", ROOT / "scripts/ev_tracker_manual_close.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


manual = load_module()


def policy():
    p = json.loads((ROOT / "config/ev_tracker_policy_v2.json").read_text())
    p["_sha256"] = "a" * 64
    return p


def play(market="h2h", line=None, book="draftkings"):
    base = {
        "play_id": "issue-10",
        "record_type": "PLAY",
        "policy_id": "EV_TRACKER_POLICY_V2",
        "sport_key": "americanfootball_nfl",
        "event_id": "evt",
        "commence_time": "2026-09-12T00:00:00Z",
        "away_team": "Away Team",
        "home_team": "Home Team",
        "market": market,
        "pick": "Away Team" if market != "totals" else "Over",
        "line": line,
        "book": book,
        "price_american": -110,
        "price_decimal": 1.909091,
    }
    return base


def body(fields):
    out = []
    for key, value in fields.items():
        out += [f"### {key}", "", str(value), ""]
    return "\n".join(out)


def payload(fields, created="2026-09-11T23:00:00Z", action="opened", updated=None):
    return {
        "action": action,
        "issue": {
            "number": 99,
            "title": "[CLOSE] test",
            "body": body(fields),
            "created_at": created,
            "updated_at": updated or created,
        },
    }


class ManualCloseTests(unittest.TestCase):
    def test_pinnacle_pair_uses_same_grade_math_and_never_stages(self):
        rec = manual.build_manual_observation(payload({
            "Evidence reference": "https://example.test/screenshot",
            "Pinnacle pick price": "-105",
            "Pinnacle opposite price": "-105",
            "Pinnacle line": "",
        }), play(), policy(), {"GITHUB_REF": "refs/heads/main", "GITHUB_SHA": "b" * 40})
        self.assertEqual(rec["observation"]["status"], "GRADED")
        self.assertEqual(rec["observation"]["reference_label"], "PINNACLE_ONLY")
        self.assertAlmostEqual(rec["observation"]["prob_clv_pp"], -2.381, places=3)
        self.assertFalse(rec["staging_eligible"])
        self.assertEqual(rec["staging_exclusion_reason"], "MANUAL_CLOSE_NOT_AUTOMATED_PROVIDER_EVIDENCE")

    def test_spread_line_is_applied_to_pick_and_opposite(self):
        rec = manual.build_manual_observation(payload({
            "Evidence reference": "shot",
            "Pinnacle pick price": "-110",
            "Pinnacle opposite price": "-110",
            "Pinnacle line": "+4.5",
        }), play("spreads", 3.5), policy())
        obs = rec["observation"]
        self.assertEqual(obs["status"], "GRADED")
        self.assertEqual(obs["reference_line"], 4.5)
        self.assertEqual(obs["line_clv_pts"], -1.0)
        self.assertEqual(obs["prob_clv_method"], "NORMAL_APPROX_V1")

    def test_after_start_is_rejected(self):
        with self.assertRaises(manual.EVError) as ctx:
            manual.build_manual_observation(payload({
                "Evidence reference": "shot",
                "Pinnacle pick price": "-110",
                "Pinnacle opposite price": "-110",
                "Pinnacle line": "",
            }, created="2026-09-12T00:00:01Z"), play(), policy())
        self.assertEqual(ctx.exception.code, "MANUAL_CLOSE_AFTER_START")

    def test_edited_issue_uses_updated_at_and_fails_closed(self):
        with self.assertRaises(manual.EVError) as ctx:
            manual.build_manual_observation(payload({
                "Evidence reference": "shot",
                "Pinnacle pick price": "-110",
                "Pinnacle opposite price": "-110",
                "Pinnacle line": "",
            }, action="edited", updated="2026-09-12T00:00:01Z"), play(), policy())
        self.assertEqual(ctx.exception.code, "MANUAL_CLOSE_AFTER_START")

    def test_incomplete_pair_is_rejected(self):
        with self.assertRaises(manual.EVError) as ctx:
            manual.build_manual_observation(payload({
                "Evidence reference": "shot",
                "Pinnacle pick price": "-110",
                "Pinnacle opposite price": "",
                "Pinnacle line": "",
            }), play(), policy())
        self.assertEqual(ctx.exception.code, "MANUAL_CLOSE_QUOTE_INCOMPLETE")

    def test_same_book_is_not_used_as_sharp_reference(self):
        rec = manual.build_manual_observation(payload({
            "Evidence reference": "shot",
            "Pinnacle pick price": "-105",
            "Pinnacle opposite price": "-105",
            "Pinnacle line": "",
        }), play(book="pinnacle"), policy())
        self.assertEqual(rec["observation"]["status"], "UNAVAILABLE")
        self.assertEqual(rec["observation"]["reason"], "NO_FRESH_SHARP_QUOTE")

    def test_workflow_manual_job_has_no_paid_key_and_is_create_only(self):
        text = (ROOT / ".github/workflows/ev-tracker.yml").read_text()
        manual_job = text.split("  manual-close:\n", 1)[1].split("\n  close:\n", 1)[0]
        self.assertNotIn("ODDS_API_KEY", manual_job)
        self.assertIn("group: ev-tracker-manual-close-${{ github.event.issue.number }}", manual_job)
        self.assertIn("git add -A ledger/ev_manual_close_observations", manual_job)
        self.assertIn("--diff-filter=MDRT -- ledger/", manual_job)
        self.assertIn("MANUAL_PUSH_FAILED: manual observation was not persisted", manual_job)


if __name__ == "__main__":
    unittest.main()
