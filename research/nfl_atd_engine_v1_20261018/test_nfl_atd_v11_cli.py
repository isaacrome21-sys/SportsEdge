"""v1.1 rulings (Oct 22, 22:50): scorer CLI in a fresh process, interpreter
match against run records, env guard on every public scoring entry point,
env-only test switch that can never produce a binding verdict. RED first.
"""
import inspect
import json
import os
import pickle
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import atd_provenance as pv
import score_nfl_atd_forward as sc
from fake_github_api import FakeGitHub, ledger_to_branch, records_worktree
from test_nfl_atd_v11_scorer import _ledger

HERE = Path(__file__).resolve().parent
SCORER = HERE / "score_nfl_atd_forward.py"


def run_cli(api, ids, wt, extra_env=None, switch=True):
    d = tempfile.mkdtemp()
    st = Path(d) / "fake_state.pickle"
    st.write_bytes(pickle.dumps(api))
    env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
    env["PYTHONPATH"] = str(HERE)
    if switch:
        env.update(ATD_TEST_FAKE_STATE=str(st), ATD_TEST_NOW="2026-11-30T00:00:00+00:00")
    env.update(extra_env or {})
    p = subprocess.run([sys.executable, str(SCORER), "--records-worktree", str(wt), *ids],
                       capture_output=True, text=True, env=env, cwd=d, timeout=300)
    return p


def last_json(p):
    return json.loads(p.stdout.strip().splitlines()[-1])


class TestCLI(unittest.TestCase):
    def world(self, **kw):
        api = FakeGitHub()
        ids = ledger_to_branch(api, _ledger(4, 14, 3, clv=0.02), **kw)
        return api, ids, records_worktree()

    def test_cli_test_switch_is_non_binding(self):
        api, ids, wt = self.world()
        p = run_cli(api, ids, wt)
        out = last_json(p)
        self.assertEqual(out["refusal"], "REVIEW_NOT_BINDING_TEST_SWITCH", p.stderr)
        self.assertFalse(out["binding"])
        self.assertNotEqual(p.returncode, 0)
        vp = Path(out["verdict_path"])
        self.assertTrue(vp.exists())
        self.assertNotEqual(vp, Path(wt) / sc.VERDICT_PATH)
        self.assertFalse((Path(wt) / sc.VERDICT_PATH).exists())
        v = json.loads(vp.read_text())
        self.assertIs(v["binding"], False)
        self.assertEqual(v["verdict"], "BEATS_MARKET")

    def test_cli_interpreter_mismatch(self):
        api, ids, wt = self.world(python_version="2.7.18")
        p = run_cli(api, ids, wt)
        self.assertEqual(last_json(p)["refusal"], "REVIEW_INTERPRETER_MISMATCH", p.stderr)
        self.assertEqual(p.returncode, 2)
        self.assertFalse((Path(wt) / sc.VERDICT_PATH).exists())

    def test_cli_without_switch_needs_token(self):
        api, ids, wt = self.world()
        p = run_cli(api, ids, wt, switch=False)
        self.assertEqual(last_json(p)["refusal"], "GITHUB_TOKEN_MISSING", p.stderr)
        self.assertEqual(p.returncode, 2)

    def test_switch_requires_env_not_argv(self):
        src = inspect.getsource(sc.main)
        self.assertIn("ATD_TEST_FAKE_STATE", src)
        self.assertNotIn("--test", src)

    def test_cli_never_prints_token(self):
        src = inspect.getsource(sc.main)
        self.assertNotIn("print(token", src)
        self.assertNotIn("GITHUB_TOKEN\"]", src)


class TestBindingCount(unittest.TestCase):
    def test_non_binding_verdict_never_counts(self):
        api = FakeGitHub()
        api.commit(pv.RECORDS_BRANCH, {sc.VERDICT_PATH: json.dumps({"binding": False})},
                   "2026-11-30T00:00:00Z")
        with mock.patch.object(sc, "_review_env_guard", lambda: None):
            self.assertFalse(sc.verdict_counts(api))

    def test_binding_verdict_counts(self):
        api = FakeGitHub()
        api.commit(pv.RECORDS_BRANCH, {sc.VERDICT_PATH: json.dumps({"binding": True})},
                   "2026-11-30T00:00:00Z")
        with mock.patch.object(sc, "_review_env_guard", lambda: None):
            self.assertTrue(sc.verdict_counts(api))


class TestGuardEverywhere(unittest.TestCase):
    """No fixtures here: fake_github_api is loaded, so every public entry
    point must refuse."""
    def test_score_slate_rows_guarded(self):
        with self.assertRaises(sc.ReviewEnvUntrusted):
            sc.score_slate_rows(FakeGitHub(), "S1")

    def test_verdict_counts_guarded(self):
        with self.assertRaises(sc.ReviewEnvUntrusted):
            sc.verdict_counts(FakeGitHub())

    def test_review_guarded(self):
        with self.assertRaises(sc.ReviewEnvUntrusted):
            sc.review([], records_worktree="/x", api=FakeGitHub())


class TestPricerRecordsInterpreter(unittest.TestCase):
    def test_run_record_has_python_version_and_platform(self):
        import price_nfl_atd_board_v11 as pr
        src = inspect.getsource(pr.main)
        self.assertIn("python_version=platform.python_version()", src)
        self.assertIn("platform=platform.platform()", src)


if __name__ == "__main__":
    unittest.main()
