"""t236b (Grok ruling under owner delegation t234u): ATD v1.2 gets its own
pricer, price_nfl_atd_board_v12.py: a copy of the frozen v1.1 pricer that
differs ONLY in the provenance import / pricer file names and nfl_atd_v1_2/
paths. The v1.2 provenance replays with it, and the v1.2 scorer's pricer pin
covers the v1.2 pricer and the v1.2 provenance. v1.1 stays byte-identical.
RED first.
"""
import difflib
import hashlib
import re
import unittest
from pathlib import Path
from unittest import mock

import fake_github_api as fk

HERE = Path(__file__).resolve().parent
V11 = {"score_nfl_atd_forward.py": "000e8f8685c76b814ccf878d50aa8a8c13afafc06e5279f95ab132e5c074b649",
       "atd_provenance.py": "48f0c18aba1c8ea540e0665d385aa7e0da20b8598d87e2c2500f950569e814e0"}
V11_PRICER = "c054c372a6984b65697aad859111fab941faaf51948045f47ee6674ecc4f8a89"
_OLD = []


def setUpModule():
    _OLD.append(fk.use_modules("atd_provenance_v12", "score_nfl_atd_forward_v12",
                               "price_nfl_atd_board_v12"))


def tearDownModule():
    fk.use_modules(*_OLD.pop())


def h(n):
    return hashlib.sha256((HERE / n).read_bytes()).hexdigest()


def swap(text):
    return (text.replace("price_nfl_atd_board_v11", "price_nfl_atd_board_v12")
            .replace("atd_provenance", "atd_provenance_v12")
            .replace("nfl_atd_v1_1", "nfl_atd_v1_2").replace("nfl-atd-v1-1", "nfl-atd-v1-2"))


class TestOnlyImportAndPathDiffs(unittest.TestCase):
    def test_pricer_is_swapped_copy(self):
        a = swap((HERE / "price_nfl_atd_board_v11.py").read_text())
        b = (HERE / "price_nfl_atd_board_v12.py").read_text()
        self.assertEqual(a, b, "".join(difflib.unified_diff(a.splitlines(1), b.splitlines(1))))

    def test_changed_lines_are_only_import_and_path_strings(self):
        a = (HERE / "price_nfl_atd_board_v11.py").read_text().splitlines()
        b = (HERE / "price_nfl_atd_board_v12.py").read_text().splitlines()
        self.assertEqual(len(a), len(b))
        changed = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertTrue(changed)
        tok = re.compile(r"atd_provenance(_v12)?|price_nfl_atd_board_v1[12]|nfl[_-]atd[_-]v1[_-][12]")
        for x, y in changed:
            self.assertEqual(tok.sub("T", x), tok.sub("T", y), (x, y))

    def test_no_v11_location_or_module_in_v12_pricer(self):
        s = (HERE / "price_nfl_atd_board_v12.py").read_text()
        for bad in ("import atd_provenance as", "price_nfl_atd_board_v11", "nfl_atd_v1_1",
                    "nfl-atd-v1-1", '"atd_provenance.py"'):
            self.assertNotIn(bad, s)

    def test_provenance_v12_is_swapped_copy(self):
        a = (HERE / "atd_provenance.py").read_text().replace("nfl_atd_v1_1", "nfl_atd_v1_2") \
            .replace("nfl-atd-v1-1", "nfl-atd-v1-2") \
            .replace("price_nfl_atd_board_v11", "price_nfl_atd_board_v12")
        self.assertEqual(a, (HERE / "atd_provenance_v12.py").read_text())


class TestWiring(unittest.TestCase):
    def setUp(self):
        import atd_provenance_v12 as pv
        import price_nfl_atd_board_v12 as pr
        import score_nfl_atd_forward_v12 as sc
        self.pv, self.pr, self.sc = pv, pr, sc

    def test_pricer_uses_v12_provenance(self):
        self.assertIs(self.pr.pv, self.pv)

    def test_pricer_files_cover_v12(self):
        self.assertEqual(self.pr.PRICER_FILES, ("atd_engine.py", "atd_refresh.py",
                                                "atd_provenance_v12.py",
                                                "price_nfl_atd_board_v12.py"))

    def test_pricer_hash_differs_from_v11(self):
        self.assertNotEqual(self.pr.pricer_sha256(), V11_PRICER)

    def test_hash_covers_v12_provenance_and_pricer(self):
        real = Path.read_bytes
        for name in ("atd_provenance_v12.py", "price_nfl_atd_board_v12.py"):
            with self.subTest(name=name):
                def patched(p, _n=name):
                    b = real(p)
                    return b + b"#x" if p.name == _n else b
                base = self.pr.pricer_sha256()
                with mock.patch.object(Path, "read_bytes", patched):
                    self.assertNotEqual(self.pr.pricer_sha256(), base)

    def test_hash_ignores_v11_files(self):
        real = Path.read_bytes
        base = self.pr.pricer_sha256()

        def patched(p):
            b = real(p)
            return b + b"#x" if p.name in ("atd_provenance.py", "price_nfl_atd_board_v11.py") else b
        with mock.patch.object(Path, "read_bytes", patched):
            self.assertEqual(self.pr.pricer_sha256(), base)

    def test_scorer_pin_is_v12_pricer(self):
        self.assertEqual(self.sc.local_shas()["pricer_sha256"], self.pr.pricer_sha256())

    def test_replayer_registry_is_v12_pricer(self):
        self.assertEqual(set(self.pv.replayers()), {self.pr.pricer_sha256()})
        self.assertIs(self.pv.replayers()[self.pr.pricer_sha256()], self.pr.replay)

    def test_env_guard_accepts_untouched_v12_registry(self):
        import sys
        self.assertEqual(self.sc._review_env_problems(
            self.pv.replayers, self.pv._ORIGINAL_REPLAYERS,
            {k: v for k, v in sys.modules.items() if k != "fake_github_api"}), [])

    def test_v11_pricer_still_uses_v11_provenance(self):
        import atd_provenance as pv11
        import price_nfl_atd_board_v11 as pr11
        self.assertIs(pr11.pv, pv11)
        self.assertEqual(pr11.pricer_sha256(), V11_PRICER)


class TestV11ByteIdentical(unittest.TestCase):
    def test_v11_files(self):
        for n, s in V11.items():
            self.assertEqual(h(n), s, n)
        import price_nfl_atd_board_v11 as pr11
        self.assertEqual(pr11.pricer_sha256(), V11_PRICER)


if __name__ == "__main__":
    unittest.main()
