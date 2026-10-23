"""ATD v1.2 items (Grok rulings under owner delegation t234u/t235u, Oct 23):
(1) review `now` truncated to whole seconds; (2) verdict re-derivation no
longer depends on the exact platform string (the interpreter check is kept
and stays fail-closed); (3) review() refuses BEFORE writing unless the
running pricer/scorer/provenance(/prereg) hashes equal FREEZE.json.
Targets score_nfl_atd_forward_v12.py only; v1.1 is frozen. RED first.
"""
import json
import os
import platform
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import atd_provenance_v12 as pv          # t236: v1.2 has its own records area
import fake_github_api as fk
import score_nfl_atd_forward_v12 as sc
from fake_github_api import FakeGitHub, fake_replayers, ledger_to_branch, records_worktree
from test_nfl_atd_v11_scorer import _ledger

BR = pv.RECORDS_BRANCH
HERE = Path(__file__).resolve().parent
NOW_US = datetime(2026, 11, 30, 0, 0, 0, 654321, tzinfo=timezone.utc)
NOW_S = NOW_US.replace(microsecond=0)
_OLD = []


def setUpModule():
    _OLD.append(fk.use_modules("atd_provenance_v12", "score_nfl_atd_forward_v12"))


def tearDownModule():
    fk.use_modules(*_OLD.pop())


def v12_world(freeze_override=None, freeze=True):
    api = FakeGitHub(freeze=False)
    if freeze:
        api.publish_freeze(dict(sc.local_shas(), **(freeze_override or {})))
    ids = ledger_to_branch(api, _ledger(4, 14, 3, clv=0.02))
    return api, ids, records_worktree()


class Env(unittest.TestCase):
    now = NOW_US

    def setUp(self):
        for p in (mock.patch.object(pv, "replayers", fake_replayers),
                  mock.patch.object(sc, "_review_env_guard", lambda: None),
                  mock.patch.object(sc, "_utcnow", lambda: self.now)):
            p.start()
            self.addCleanup(p.stop)

    def reviewed(self, **kw):
        api, ids, wt = v12_world(**kw)
        sc.review(ids, records_worktree=wt, api=api)
        return api, ids, (Path(wt) / sc.VERDICT_PATH).read_text()

    def push(self, api, body):
        api.commit(BR, {sc.VERDICT_PATH: body}, "2026-11-30T01:00:00Z")


class TestWholeSeconds(Env):
    def test_reviewed_at_whole_seconds(self):
        api, ids, body = self.reviewed()
        v = json.loads(body)
        self.assertEqual(v["reviewed_at"], NOW_S.isoformat())
        self.assertNotIn(".", v["reviewed_at"])

    def test_explicit_now_truncated(self):
        api, ids, wt = v12_world()
        v = sc.review(ids, records_worktree=None, api=api, _dry=True, _now=NOW_US)
        self.assertEqual(v["reviewed_at"], NOW_S.isoformat())

    def test_truncated_verdict_verifies(self):
        api, ids, body = self.reviewed()
        self.push(api, body)
        self.assertTrue(sc.verify_verdict(api)["counts"])

    def test_fractional_reviewed_at_unverified(self):
        api, ids, body = self.reviewed()
        v = json.loads(body)
        v["reviewed_at"] = NOW_US.isoformat()
        self.push(api, json.dumps(v))
        self.assertEqual(sc.verify_verdict(api)["code"], "VERDICT_UNVERIFIED")


class TestPlatformIndependent(Env):
    def test_other_platform_string_still_verifies(self):
        api, ids, body = self.reviewed()
        self.push(api, body)
        with mock.patch.object(platform, "platform", lambda *a, **k: "Other-9.9-x"):
            r = sc.verify_verdict(api)
        self.assertTrue(r["counts"], r)

    def test_platform_still_recorded(self):
        api, ids, body = self.reviewed()
        self.assertEqual(json.loads(body)["platform"], platform.platform())

    def test_interpreter_mismatch_still_unverified(self):
        api, ids, body = self.reviewed()
        self.push(api, body)
        with mock.patch.object(platform, "python_version", lambda: "0.0.1"):
            r = sc.verify_verdict(api)
        self.assertFalse(r["counts"])
        self.assertEqual(r["code"], "VERDICT_UNVERIFIED")

    def test_tampered_python_version_unverified(self):
        api, ids, body = self.reviewed()
        v = json.loads(body)
        v["python_version"] = "0.0.1"
        self.push(api, json.dumps(v))
        self.assertEqual(sc.verify_verdict(api)["code"], "VERDICT_UNVERIFIED")

    def test_missing_python_version_unverified(self):
        api, ids, body = self.reviewed()
        v = json.loads(body)
        del v["python_version"]
        self.push(api, json.dumps(v))
        self.assertEqual(sc.verify_verdict(api)["code"], "VERDICT_UNVERIFIED")

    def test_other_fields_still_compared(self):
        api, ids, body = self.reviewed()
        v = json.loads(body)
        v["n_picked"] += 1
        self.push(api, json.dumps(v))
        self.assertEqual(sc.verify_verdict(api)["code"], "VERDICT_UNVERIFIED")


class TestPreWriteFreeze(Env):
    def assert_refused(self, api, ids, wt):
        with self.assertRaises(sc.ReviewFreezeMismatch):
            sc.review(ids, records_worktree=wt, api=api)
        self.assertFalse((Path(wt) / sc.VERDICT_PATH).exists())
        self.assertFalse((Path(wt) / sc.NONBINDING_VERDICT_PATH).exists())

    def test_each_pin_mismatch_refused(self):
        for k in ("pricer_sha256", "scorer_sha256", "provenance_sha256", "prereg_sha256"):
            with self.subTest(k=k):
                self.assert_refused(*v12_world({k: "0" * 64}))

    def test_v11_freeze_refuses_v12_scorer(self):
        api = FakeGitHub()                       # FREEZE pins the v1.1 scorer
        ids = ledger_to_branch(api, _ledger(4, 14, 3, clv=0.02))
        self.assert_refused(api, ids, records_worktree())

    def test_local_code_drift_refused(self):
        api, ids, wt = v12_world()
        real = sc.local_shas()
        with mock.patch.object(sc, "local_shas", lambda: dict(real, provenance_sha256="1" * 64)):
            self.assert_refused(api, ids, wt)

    def test_no_freeze_refused(self):
        api, ids, wt = v12_world(freeze=False)
        with self.assertRaises((sc.ReviewFreezeMismatch, pv.ProvenanceFailed)):
            sc.review(ids, records_worktree=wt, api=api)
        self.assertFalse((Path(wt) / sc.VERDICT_PATH).exists())

    def test_refusal_code(self):
        self.assertEqual(sc.ReviewFreezeMismatch.code, "REVIEW_FREEZE_MISMATCH")

    def test_matching_freeze_writes(self):
        api, ids, body = self.reviewed()
        self.assertTrue(json.loads(body)["binding"])


class TestCLI(unittest.TestCase):
    def run_cli(self, api, ids, wt):
        d = tempfile.mkdtemp()
        st = Path(d) / "fake_state.json"
        st.write_text(api.to_json())
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        env.update(PYTHONPATH=str(HERE), ATD_TEST_FAKE_STATE=str(st),
                   ATD_TEST_NOW="2026-11-30T00:00:00.654321+00:00")
        p = subprocess.run([sys.executable, str(HERE / "score_nfl_atd_forward_v12.py"),
                            "--records-worktree", str(wt), *ids],
                           capture_output=True, text=True, env=env, cwd=d, timeout=300)
        return json.loads(p.stdout.strip().splitlines()[-1]), p

    def test_cli_freeze_mismatch(self):
        api, ids, wt = v12_world({"scorer_sha256": "0" * 64})
        out, p = self.run_cli(api, ids, wt)
        self.assertEqual(out["refusal"], "REVIEW_FREEZE_MISMATCH", p.stderr)
        self.assertNotEqual(p.returncode, 0)

    def test_cli_switch_still_nonbinding_and_whole_seconds(self):
        api, ids, wt = v12_world()
        out, p = self.run_cli(api, ids, wt)
        self.assertEqual(out["refusal"], "REVIEW_NOT_BINDING_TEST_SWITCH", p.stderr)
        self.assertFalse(out["binding"])
        v = json.loads(Path(out["verdict_path"]).read_text())
        self.assertEqual(v["reviewed_at"], NOW_S.isoformat())


class TestV11Untouched(unittest.TestCase):
    def test_v11_hashes_unchanged(self):
        import hashlib
        h = lambda n: hashlib.sha256((HERE / n).read_bytes()).hexdigest()
        self.assertEqual(h("score_nfl_atd_forward.py"),
                         "000e8f8685c76b814ccf878d50aa8a8c13afafc06e5279f95ab132e5c074b649")
        self.assertEqual(h("atd_provenance.py"),
                         "48f0c18aba1c8ea540e0665d385aa7e0da20b8598d87e2c2500f950569e814e0")
        import price_nfl_atd_board_v11 as pr
        self.assertEqual(pr.pricer_sha256(),
                         "c054c372a6984b65697aad859111fab941faaf51948045f47ee6674ecc4f8a89")


if __name__ == "__main__":
    unittest.main()
