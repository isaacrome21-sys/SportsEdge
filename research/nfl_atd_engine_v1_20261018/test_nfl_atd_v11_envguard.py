"""v1.1 re-audit of 8d86e7a9: no replayer hook in production code; review
refuses an untrusted environment (REVIEW_ENV_UNTRUSTED). RED first.
"""
import importlib
import platform
import sys
import unittest
from pathlib import Path
from unittest import mock

import atd_provenance as pv
import price_nfl_atd_board_v11 as pr
import score_nfl_atd_forward as sc


class TestNoHook(unittest.TestCase):
    def test_extra_replayers_deleted(self):
        self.assertFalse(hasattr(pv, "EXTRA_REPLAYERS"))
        src = Path(pv.__file__).read_text()
        self.assertNotIn("EXTRA_REPLAYERS", src)

    def test_replayers_only_real_pricer(self):
        self.assertEqual(pv.replayers(), {pr.pricer_sha256(): pr.replay})

    def test_fake_import_registers_nothing(self):
        before = pv.replayers
        import fake_github_api
        importlib.reload(fake_github_api)
        self.assertIs(pv.replayers, before)
        self.assertEqual(set(pv.replayers()), {pr.pricer_sha256()})


class TestGuard(unittest.TestCase):
    def code(self):
        with self.assertRaises(sc.ReviewEnvUntrusted) as cm:
            sc.review([], records_worktree="/nonexistent", api=object())
        return cm.exception.code

    def test_fake_module_loaded_refuses(self):
        import fake_github_api  # noqa: F401
        self.assertIn("fake_github_api", sys.modules)
        self.assertEqual(self.code(), "REVIEW_ENV_UNTRUSTED")

    def test_patched_replayers_refuses_even_without_fake_module(self):
        mods = {k: v for k, v in sys.modules.items() if k != "fake_github_api"}
        with mock.patch.dict(sys.modules, mods, clear=True), \
                mock.patch.object(pv, "replayers", lambda: {pr.pricer_sha256(): pr.replay}):
            self.assertEqual(self.code(), "REVIEW_ENV_UNTRUSTED")

    def test_problem_list(self):
        orig = pv.replayers
        extra = lambda: {pr.pricer_sha256(): pr.replay, "f" * 64: None}  # noqa: E731
        self.assertEqual(sc._review_env_problems(orig, orig, {}), [])
        self.assertIn("replayers_patched", sc._review_env_problems(extra, orig, {}))
        self.assertIn("fake_module_loaded",
                      sc._review_env_problems(orig, orig, {"fake_github_api": 1}))
        self.assertIn("replayer_keys", sc._review_env_problems(extra, extra, {}))

    def test_guard_runs_before_anything(self):
        # no token, no worktree: still the env refusal, not another error
        import fake_github_api  # noqa: F401
        self.assertEqual(self.code(), "REVIEW_ENV_UNTRUSTED")


class TestVerdictEnv(unittest.TestCase):
    def test_verdict_records_environment(self):
        from datetime import datetime, timezone
        from fake_github_api import FakeGitHub, fake_replayers, ledger_to_branch, records_worktree
        from test_nfl_atd_v11_scorer import _ledger
        api = FakeGitHub()
        ids = ledger_to_branch(api, _ledger(4, 14, 3, clv=0.02))
        with mock.patch.object(pv, "replayers", fake_replayers), \
                mock.patch.object(sc, "_review_env_guard", lambda: None), \
                mock.patch.object(sc, "_utcnow",
                                  lambda: datetime(2026, 11, 30, tzinfo=timezone.utc)):
            v = sc.review(ids, records_worktree=records_worktree(), api=api)
        import hashlib
        self.assertEqual(v["pricer_sha256"], pr.pricer_sha256())
        self.assertEqual(v["scorer_sha256"],
                         hashlib.sha256(Path(sc.__file__).read_bytes()).hexdigest())
        self.assertEqual(v["python_version"], platform.python_version())
        self.assertEqual(v["platform"], platform.platform())


class TestPrereg(unittest.TestCase):
    def test_2b_binding_review(self):
        t = Path(pv.__file__).with_name("PREREG_NFL_ATD_ENGINE_V1_1_DRAFT.md").read_text()
        s2b = t[t.index("## 2b."):t.index("## 3.")]
        self.assertIn("REVIEW_ENV_UNTRUSTED", s2b)
        self.assertIn("in-process monkeypatching is out of scope", s2b)
        self.assertIn("same interpreter version", s2b)


if __name__ == "__main__":
    unittest.main()
