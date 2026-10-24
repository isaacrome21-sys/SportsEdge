"""t236 (Grok ruling under owner delegation t234u/t236u, Oct 23): ATD v1.2
gets its OWN records area so it can never read or overwrite the v1.1 FREEZE
or verdict. atd_provenance_v12.py = copy of atd_provenance.py pointing at
records/nfl-atd-v1-2 and nfl_atd_v1_2/. The v1.2 scorer is wired to it, and
score_slate's _utcnow is truncated to whole seconds. v1.1 stays byte-identical.
RED first.
"""
import hashlib
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import atd_provenance as pv11
import fake_github_api as fk

HERE = Path(__file__).resolve().parent
_OLD = []


def setUpModule():
    _OLD.append(fk.use_modules("atd_provenance_v12", "score_nfl_atd_forward_v12",
                               "price_nfl_atd_board_v12"))


def tearDownModule():
    fk.use_modules(*_OLD.pop())


def h(n):
    return hashlib.sha256((HERE / n).read_bytes()).hexdigest()


class TestOwnRecordsArea(unittest.TestCase):
    def setUp(self):
        import atd_provenance_v12 as pv
        self.pv = pv

    def test_branch_and_root(self):
        self.assertEqual(self.pv.RECORDS_BRANCH, "records/nfl-atd-v1-2")
        self.assertEqual(self.pv.ROOT, "nfl_atd_v1_2")

    def test_freeze_and_verdict_paths(self):
        self.assertEqual(self.pv.FREEZE_PATH, "nfl_atd_v1_2/FREEZE.json")
        self.assertEqual(self.pv.VERDICT_PATH, "nfl_atd_v1_2/VERDICT.json")

    def test_record_paths_under_v12_root(self):
        s = "a" * 64
        for p in (self.pv.fetch_record_path(s), self.pv.run_record_path("x"),
                  self.pv.data_record_path(s), self.pv.board_record_path(s, 2026, 8),
                  self.pv.close_record_path(s, 2026, 8),
                  self.pv.settlement_data_path(s, 2026, 8)):
            self.assertTrue(p.startswith("nfl_atd_v1_2/"), p)

    def test_disjoint_from_v11(self):
        self.assertNotEqual(self.pv.RECORDS_BRANCH, pv11.RECORDS_BRANCH)
        self.assertNotEqual(self.pv.FREEZE_PATH, pv11.FREEZE_PATH)
        self.assertNotEqual(self.pv.VERDICT_PATH, pv11.VERDICT_PATH)

    def test_no_v11_location_in_v12_module(self):
        src = (HERE / "atd_provenance_v12.py").read_text()
        self.assertNotIn("nfl_atd_v1_1", src)
        self.assertNotIn("nfl-atd-v1-1", src)

    def test_otherwise_a_copy(self):
        a = (HERE / "atd_provenance.py").read_text().replace("nfl_atd_v1_1", "nfl_atd_v1_2") \
            .replace("nfl-atd-v1-1", "nfl-atd-v1-2") \
            .replace("price_nfl_atd_board_v11", "price_nfl_atd_board_v12")   # t236b
        b = (HERE / "atd_provenance_v12.py").read_text()
        self.assertEqual(a, b)

    def test_own_replayer_identity(self):
        import price_nfl_atd_board_v12 as pr
        self.assertIs(self.pv._ORIGINAL_REPLAYERS, self.pv.replayers)
        self.assertEqual(set(self.pv.replayers()), {pr.pricer_sha256()})


class TestScorerWired(unittest.TestCase):
    def setUp(self):
        import atd_provenance_v12 as pv
        import score_nfl_atd_forward_v12 as sc
        self.pv, self.sc = pv, sc

    def test_scorer_uses_v12_provenance(self):
        self.assertIs(self.sc.pv, self.pv)

    def test_verdict_paths(self):
        self.assertEqual(self.sc.VERDICT_PATH, "nfl_atd_v1_2/VERDICT.json")
        self.assertEqual(self.sc.NONBINDING_VERDICT_PATH,
                         "nfl_atd_v1_2/TEST_NONBINDING_VERDICT.json")

    def test_local_shas_pin_v12_provenance(self):
        s = self.sc.local_shas()
        self.assertEqual(s["provenance_sha256"], h("atd_provenance_v12.py"))
        self.assertEqual(s["scorer_sha256"], h("score_nfl_atd_forward_v12.py"))

    def test_env_guard_checks_v12_registry(self):
        with mock.patch.object(self.pv, "replayers", fk.fake_replayers):
            with self.assertRaises(self.sc.ReviewEnvUntrusted):
                self.sc._review_env_guard()

    def test_freeze_loaded_from_v12_branch_only(self):
        api = fk.FakeGitHub(freeze=False)
        api.publish_freeze(self.sc.local_shas())
        self.assertIsNotNone(api.get_file("records/nfl-atd-v1-2", "nfl_atd_v1_2/FREEZE.json"))
        self.assertIsNone(api.get_file("records/nfl-atd-v1-1", "nfl_atd_v1_1/FREEZE.json"))
        fz = self.pv.load_freeze(api)
        self.assertEqual({k: fz[k] for k in self.pv.FREEZE_KEYS}, self.sc.local_shas())

    def test_v11_freeze_location_not_read(self):
        api = fk.FakeGitHub(freeze=False)
        api.commit("records/nfl-atd-v1-1", {"nfl_atd_v1_1/FREEZE.json": "{}"},
                   "2026-10-01T00:02:00Z")
        with self.assertRaises(self.pv.ProvenanceFailed):
            self.pv.load_freeze(api)


class TestUtcnowWholeSeconds(unittest.TestCase):
    def test_utcnow_truncated(self):
        import score_nfl_atd_forward_v12 as sc
        fixed = datetime(2026, 11, 30, 0, 0, 0, 654321, tzinfo=timezone.utc)

        class D(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed
        with mock.patch.object(sc, "datetime", D):
            t = sc._utcnow()
        self.assertEqual(t.microsecond, 0)
        self.assertEqual(t, fixed.replace(microsecond=0))
        self.assertEqual(t.tzinfo, timezone.utc)

    def test_score_slate_passes_whole_seconds(self):
        import score_nfl_atd_forward_v12 as sc
        seen = {}
        fixed = datetime(2026, 11, 30, 0, 0, 0, 654321, tzinfo=timezone.utc)

        class D(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        def fake_setl(api, games, now):
            seen["now"] = now
            return {"settlements": {}}
        st = {"status": "COUNTS"}
        with mock.patch.object(sc, "datetime", D), \
                mock.patch.object(sc, "_review_env_guard", lambda: None), \
                mock.patch.object(sc.pv, "require_token", lambda api: None), \
                mock.patch.object(sc.pv, "load_slate", lambda api, sid: st), \
                mock.patch.object(sc.pv, "load_closes", lambda api, g: {}), \
                mock.patch.object(sc.pv, "load_settlements", fake_setl), \
                mock.patch.object(sc, "_rows", lambda s: []), \
                mock.patch.object(sc, "_games", lambda s: {}), \
                mock.patch.object(sc, "_score_rows", lambda r, c, s: []):
            sc.score_slate_rows(object(), "x")
        self.assertEqual(seen["now"].microsecond, 0)


class TestV11ByteIdentical(unittest.TestCase):
    def test_hashes(self):
        import price_nfl_atd_board_v11 as pr
        self.assertEqual(h("score_nfl_atd_forward.py"),
                         "000e8f8685c76b814ccf878d50aa8a8c13afafc06e5279f95ab132e5c074b649")
        self.assertEqual(h("atd_provenance.py"),
                         "48f0c18aba1c8ea540e0665d385aa7e0da20b8598d87e2c2500f950569e814e0")
        self.assertEqual(pr.pricer_sha256(),
                         "c054c372a6984b65697aad859111fab941faaf51948045f47ee6674ecc4f8a89")


if __name__ == "__main__":
    unittest.main()
