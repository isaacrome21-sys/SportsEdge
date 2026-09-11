import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sw = _load("ev_tracker_sweep_test", "scripts/ev_tracker_sweep.py")
tr = sw.tr
POLICY = tr.ev.load_active_policy(ROOT)


class FakeGH:
    token = "t"
    repo = "o/r"

    def __init__(self):
        self.comments = []
        self.closed = []

    def comment(self, n, text):
        self.comments.append((n, text))

    def close(self, n):
        self.closed.append(n)


class FakeClient:
    def events(self, sport):
        return [{
            "id": "e1",
            "commence_time": "2026-09-13T17:00:00Z",
            "away_team": "Denver Broncos",
            "home_team": "Kansas City Chiefs",
        }]


def body():
    fields = {
        "Source": "Odds Assist Pinnacle +EV", "Sport": "NFL", "Away team": "Broncos",
        "Home team": "Chiefs", "Game date": "_No response_", "Market": "Spread",
        "Pick": "Broncos", "Line": "+3.5", "Book": "FanDuel", "Price": "+102",
        "Stake (units)": "0.25", "Tool EV %": "2.4",
    }
    return "\n\n".join(f"### {k}\n\n{v}" for k, v in fields.items())


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tr.PLAYS_DIR = Path(self.tmp.name) / "plays"

    def tearDown(self):
        self.tmp.cleanup()

    def issue(self, number=7, updated="2026-09-13T16:00:00Z"):
        return {
            "number": number,
            "title": "[BET] Broncos +3.5",
            "user": {"login": "isaacrome21-sys"},
            "created_at": "2026-09-13T16:00:00Z",
            "updated_at": updated,
            "body": body(),
        }

    def test_recovery_action_preserves_issue_timing(self):
        self.assertEqual(sw.recovery_action(self.issue()), "opened")
        self.assertEqual(sw.recovery_action(self.issue(updated="2026-09-13T16:05:00Z")), "edited")

    def test_sweep_logs_unrecorded_open_bet(self):
        gh = FakeGH()
        out = sw.sweep_open_bets(POLICY, FakeClient(), gh, "isaacrome21-sys", issues=[self.issue()])
        self.assertEqual(out, [{"issue": 7, "outcome": "LOGGED"}])
        self.assertTrue((tr.PLAYS_DIR / "issue-7.json").exists())
        self.assertEqual(gh.closed, [7])

    def test_sweep_skips_existing_ledger_record(self):
        tr.PLAYS_DIR.mkdir(parents=True)
        (tr.PLAYS_DIR / "issue-7.json").write_text("{}\n")
        gh = FakeGH()
        self.assertEqual(sw.sweep_open_bets(POLICY, FakeClient(), gh, "isaacrome21-sys", issues=[self.issue()]), [])
        self.assertEqual(gh.closed, [])

    def test_edited_after_start_is_rejected(self):
        gh = FakeGH()
        out = sw.sweep_open_bets(
            POLICY, FakeClient(), gh, "isaacrome21-sys",
            issues=[self.issue(updated="2026-09-13T17:05:00Z")],
        )
        self.assertEqual(out[0]["outcome"], "REJECTED_LOGGED_AFTER_START")
        self.assertFalse((tr.PLAYS_DIR / "issue-7.json").exists())

    def test_workflow_keeps_global_lock_and_persists_swept_plays(self):
        text = (ROOT / ".github/workflows/ev-tracker.yml").read_text()
        self.assertEqual(text.count("group: sportsedge-paid-odds-api"), 2)
        close = text.split("  close:", 1)[1]
        self.assertIn("issues: write", close)
        self.assertIn("python scripts/ev_tracker_sweep.py", close)
        self.assertIn("GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}", close)
        self.assertIn("ledger/ev_plays ledger/ev_close_attempts", close)


if __name__ == "__main__":
    unittest.main()
