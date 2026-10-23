"""v1.1 re-audit of 65e27e20: FREEZE record pins; verdict_counts re-derives
the verdict (dry review) instead of trusting a self-asserted flag; JSON
test-switch state; interpreter check only on COUNTS slates. RED first.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import atd_provenance as pv
import score_nfl_atd_forward as sc
from fake_github_api import FakeGitHub, fake_replayers, ledger_to_branch, records_worktree
from test_nfl_atd_v11_scorer import _ledger

BR = pv.RECORDS_BRANCH
HERE = Path(__file__).resolve().parent
NOW = datetime(2026, 11, 30, tzinfo=timezone.utc)


def patched():
    return [mock.patch.object(pv, "replayers", fake_replayers),
            mock.patch.object(sc, "_review_env_guard", lambda: None),
            mock.patch.object(sc, "_utcnow", lambda: NOW)]


class Env(unittest.TestCase):
    def setUp(self):
        for p in patched():
            p.start()
            self.addCleanup(p.stop)

    def reviewed(self, **kw):
        api = FakeGitHub(**kw)
        ids = ledger_to_branch(api, _ledger(4, 14, 3, clv=0.02))
        wt = records_worktree()
        sc.review(ids, records_worktree=wt, api=api)
        body = (Path(wt) / sc.VERDICT_PATH).read_text()
        return api, ids, body


class TestFreeze(Env):
    def test_freeze_record(self):
        self.assertEqual(pv.FREEZE_PATH, "nfl_atd_v1_1/FREEZE.json")
        f = pv.load_freeze(FakeGitHub())
        for k in ("pricer_sha256", "scorer_sha256", "provenance_sha256", "prereg_sha256"):
            self.assertEqual(f[k], sc.local_shas()[k])

    def test_freeze_missing(self):
        with self.assertRaises(pv.ProvenanceFailed) as cm:
            pv.load_freeze(FakeGitHub(freeze=False))
        self.assertEqual(cm.exception.code, "FREEZE_NOT_ON_BRANCH")

    def test_not_hardcoded_in_scorer(self):
        src = (HERE / "score_nfl_atd_forward.py").read_text()
        self.assertNotRegex(src, r"FROZEN_[A-Z_]*SHA\w*\s*=\s*['\"][0-9a-f]{64}")

    def test_run_before_freeze_is_screen(self):
        api = FakeGitHub(freeze=False)
        ids = ledger_to_branch(api, _ledger(1, 2, 1))
        api.publish_freeze(pushed_at="2026-10-28T00:00:00Z")
        st = pv.load_slate(api, ids[0])
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("RUN_PUSH_NOT_AFTER_FREEZE", st["reasons"])

    def test_no_freeze_is_screen(self):
        api = FakeGitHub(freeze=False)
        ids = ledger_to_branch(api, _ledger(1, 2, 1))
        self.assertIn("FREEZE_NOT_ON_BRANCH", pv.load_slate(api, ids[0])["reasons"])


class TestVerdictCounts(Env):
    def push(self, api, body):
        api.commit(BR, {sc.VERDICT_PATH: body}, "2026-11-30T01:00:00Z")

    def test_honest_verdict_counts(self):
        api, ids, body = self.reviewed()
        self.assertIn('"slate_ids"', body)
        self.push(api, body)
        r = sc.verify_verdict(api)
        self.assertTrue(r["counts"], r)
        self.assertTrue(sc.verdict_counts(api))

    def test_self_asserted_flag_does_not_count(self):
        api, ids, body = self.reviewed()
        self.push(api, json.dumps({"binding": True}))
        r = sc.verify_verdict(api)
        self.assertFalse(r["counts"])
        self.assertEqual(r["code"], "VERDICT_UNVERIFIED")

    def test_forged_numbers_do_not_count(self):
        api, ids, body = self.reviewed()
        v = json.loads(body)
        v["n_picked"] += 1
        self.push(api, json.dumps(v))
        self.assertEqual(sc.verify_verdict(api)["code"], "VERDICT_UNVERIFIED")

    def test_verdict_shas_must_equal_freeze(self):
        api, ids, body = self.reviewed(freeze_shas={"scorer_sha256": "0" * 64})
        self.push(api, body)
        self.assertEqual(sc.verify_verdict(api)["code"], "VERDICT_UNVERIFIED")

    def test_local_shas_must_equal_freeze(self):
        api, ids, body = self.reviewed()
        self.push(api, body)
        real = sc.local_shas()
        with mock.patch.object(sc, "local_shas", lambda: dict(real, pricer_sha256="1" * 64)):
            self.assertEqual(sc.verify_verdict(api)["code"], "VERDICT_UNVERIFIED")

    def test_dry_review_writes_nothing(self):
        api = FakeGitHub()
        ids = ledger_to_branch(api, _ledger(4, 14, 3, clv=0.02))
        before = set(os.listdir(tempfile.gettempdir()))
        v = sc.review(ids, records_worktree=None, api=api, _dry=True, _now=NOW)
        self.assertEqual(v["verdict"], "BEATS_MARKET")
        self.assertEqual(before, set(os.listdir(tempfile.gettempdir())))

    def test_no_verdict(self):
        self.assertFalse(sc.verify_verdict(FakeGitHub())["counts"])


class TestInterpreterOnCounts(Env):
    def test_screen_slate_version_ignored_counts_slate_checked(self):
        api = FakeGitHub()
        ids = ledger_to_branch(api, _ledger(4, 14, 3, clv=0.02), python_version="2.7.18")
        with self.assertRaises(sc.ReviewInterpreterMismatch):
            sc.review(ids, records_worktree=records_worktree(), api=api,
                      _check_interpreter=True)
        # same bad version on a SCREEN-only slate list: no interpreter refusal
        v = sc.review(["missing-slate"], records_worktree=records_worktree(), api=api,
                      _check_interpreter=True)
        self.assertEqual(v["status"], "NO_REVIEW_GATES_NOT_MET")


class TestCliJsonState(unittest.TestCase):
    def test_roundtrip(self):
        api = FakeGitHub()
        ledger_to_branch(api, _ledger(1, 2, 1))
        b = FakeGitHub.from_json(api.to_json())
        self.assertEqual(b.heads, api.heads)
        self.assertEqual(b.trees, api.trees)

    def test_cli_reads_json_not_pickle(self):
        src = (HERE / "score_nfl_atd_forward.py").read_text()
        self.assertNotIn("pickle", src)
        api = FakeGitHub()
        ids = ledger_to_branch(api, _ledger(4, 14, 3, clv=0.02))
        d = Path(tempfile.mkdtemp())
        (d / "state.json").write_text(api.to_json())
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        env.update(PYTHONPATH=str(HERE), ATD_TEST_FAKE_STATE=str(d / "state.json"),
                   ATD_TEST_NOW=NOW.isoformat())
        wt = records_worktree()
        p = subprocess.run([sys.executable, str(HERE / "score_nfl_atd_forward.py"),
                            "--records-worktree", str(wt), *ids], capture_output=True,
                           text=True, env=env, cwd=d, timeout=300)
        out = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(out["refusal"], "REVIEW_NOT_BINDING_TEST_SWITCH", p.stderr)

    def test_cli_pushes_nothing(self):
        import inspect
        src = inspect.getsource(sc.main)
        for bad in ("git push", "\"push\"", "commit(", "push_files"):
            self.assertNotIn(bad, src)


class TestPrereg(unittest.TestCase):
    def test_2b(self):
        t = (HERE / "PREREG_NFL_ATD_ENGINE_V1_1_DRAFT.md").read_text()
        s2b = t[t.index("## 2b."):t.index("## 3.")]
        for k in ("FREEZE.json", "VERDICT_UNVERIFIED", "fail-closed", "pushes nothing",
                  "owner ruling"):
            self.assertIn(k, s2b)


if __name__ == "__main__":
    unittest.main()
