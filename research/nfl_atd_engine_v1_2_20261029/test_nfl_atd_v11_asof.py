"""v1.1 rulings (Oct 22, 23:04): review(now) treats records pushed after now
as non-existent; proof_source excluded from the re-derivation comparison;
all four FREEZE pins checked. RED first.
"""
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import atd_provenance as pv
import score_nfl_atd_forward as sc
from fake_github_api import (FakeGitHub, fake_replayers, ledger_to_branch, publish_close,
                             publish_settlements, records_worktree)
from test_nfl_atd_v11_scorer import _ledger

BR = pv.RECORDS_BRANCH
HERE = Path(__file__).resolve().parent
NOW = datetime(2026, 11, 30, tzinfo=timezone.utc)
LATE = "2026-12-01T00:00:00Z"


class Env(unittest.TestCase):
    def setUp(self):
        for p in (mock.patch.object(pv, "replayers", fake_replayers),
                  mock.patch.object(sc, "_review_env_guard", lambda: None),
                  mock.patch.object(sc, "_utcnow", lambda: NOW)):
            p.start()
            self.addCleanup(p.stop)

    def reviewed(self, **kw):
        api = FakeGitHub(**kw)
        ids = ledger_to_branch(api, _ledger(4, 14, 3, clv=0.02))
        wt = records_worktree()
        sc.review(ids, records_worktree=wt, api=api)
        body = (Path(wt) / sc.VERDICT_PATH).read_text()
        return api, ids, body

    def push(self, api, body):
        api.commit(BR, {sc.VERDICT_PATH: body}, "2026-11-30T01:00:00Z")


class TestAsOf(Env):
    def test_late_conflicting_settlement_ignored(self):
        api, ids, body = self.reviewed()
        self.push(api, body)
        publish_settlements(api, {("w0g0", "w0g0y0"): 1, ("w0g0", "w0g0y1"): 1}, LATE, week=1)
        publish_settlements(api, {}, LATE, week=1, rows=[{"bad": 1}])
        r = sc.verify_verdict(api)
        self.assertTrue(r["counts"], r)

    def test_late_settlement_absent_from_lists(self):
        api = FakeGitHub()
        ledger_to_branch(api, _ledger(1, 2, 1))
        publish_settlements(api, {}, LATE, week=1, rows=[{"bad": 1}])
        games = {"w0g0": {"kickoff": "2026-10-25T17:00:00Z", "season": 2026, "week": 1}}
        s = pv.load_settlements(api, games, NOW)
        self.assertFalse(any("bad" in json.dumps(x) for x in s["refused"]))
        self.assertEqual(len(s["refused"]), 0, s["refused"])

    def test_on_time_refused_still_listed(self):
        api = FakeGitHub()
        ledger_to_branch(api, _ledger(1, 2, 1))
        publish_settlements(api, {}, "2026-11-01T00:00:00Z", week=1, rows=[{"bad": 1}])
        games = {"w0g0": {"kickoff": "2026-10-25T17:00:00Z", "season": 2026, "week": 1}}
        self.assertEqual(len(pv.load_settlements(api, games, NOW)["refused"]), 1)

    def test_late_close_ignored(self):
        api = FakeGitHub()
        games = {"g1": {"kickoff": "2026-10-25T17:00:00Z", "season": 2026, "week": 8}}
        publish_close(api, "g1", "2026-10-25T17:00:00Z", "2026-10-25T16:30:00Z",
                      [{"player_id": "a", "yes_price": 150, "captured_at": "2026-10-25T16:30:00Z"}],
                      LATE)
        c = pv.load_closes(api, games, now=NOW)
        self.assertEqual(c["captures"], [])
        self.assertEqual(c["unproven_records"], [])
        self.assertEqual(c["records"], [])

    def test_late_unattributable_close_ignored(self):
        api = FakeGitHub()
        publish_close(api, "g1", "2026-10-25T17:00:00Z", "2026-10-25T16:30:00Z", [],
                      LATE, raw="{not json")
        pv.load_closes(api, {}, now=NOW)        # must not refuse

    def test_run_record_after_now_nonexistent(self):
        api = FakeGitHub()
        ids = ledger_to_branch(api, _ledger(1, 2, 1))
        st = pv.load_slate(api, ids[0], now=datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc))
        self.assertIn("RUN_RECORD_NOT_ON_BRANCH", st["reasons"])


class TestProofSource(Env):
    def test_proof_source_excluded_from_comparison(self):
        api, ids, body = self.reviewed()
        v = json.loads(body)
        for p in v["run_proofs"].values():
            p["proof_source"] = "stored_event_commit_checked"
        self.push(api, json.dumps(v))
        self.assertTrue(sc.verify_verdict(api)["counts"])

    def test_other_proof_fields_still_compared(self):
        api, ids, body = self.reviewed()
        v = json.loads(body)
        next(iter(v["run_proofs"].values()))["commit"] = "0" * 40
        self.push(api, json.dumps(v))
        self.assertEqual(sc.verify_verdict(api)["code"], "VERDICT_UNVERIFIED")


class TestAllPins(Env):
    def test_verdict_records_all_pins(self):
        api, ids, body = self.reviewed()
        v = json.loads(body)
        loc = sc.local_shas()
        for k in pv.FREEZE_KEYS:
            self.assertEqual(v[k], loc[k])

    def test_provenance_pin_mismatch(self):
        api, ids, body = self.reviewed(freeze_shas={"provenance_sha256": "0" * 64})
        self.push(api, body)
        self.assertEqual(sc.verify_verdict(api)["code"], "VERDICT_UNVERIFIED")

    def test_prereg_local_mismatch(self):
        api, ids, body = self.reviewed()
        self.push(api, body)
        real = sc.local_shas()
        with mock.patch.object(sc, "local_shas", lambda: dict(real, prereg_sha256="2" * 64)):
            self.assertEqual(sc.verify_verdict(api)["code"], "VERDICT_UNVERIFIED")


class TestPrereg(unittest.TestCase):
    def test_2b(self):
        t = (HERE / "PREREG_NFL_ATD_ENGINE_V1_1_DRAFT.md").read_text()
        s2b = t[t.index("## 2b."):t.index("## 3.")]
        self.assertIn("pushed by Grok under the owner's delegation", s2b)
        self.assertIn("after now", s2b)
        self.assertIn("proof_source", s2b)


if __name__ == "__main__":
    unittest.main()
