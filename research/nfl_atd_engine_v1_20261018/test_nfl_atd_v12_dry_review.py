"""v1.2 only: parallel-safe dry-review-writes-nothing (Grok, Oct 23 2026).

The frozen v1.1 test (test_nfl_atd_v11_freeze.TestVerify.test_dry_review_writes_nothing)
compares a listing of the *shared* system temp dir before/after, so any other process or
xdist worker creating a temp file in between makes it fail. This v1.2 copy points
tempfile (and TMPDIR) at a fresh per-test directory and asserts only that directory stays
empty. v1.1 files are untouched.
"""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import fake_github_api as fk
import score_nfl_atd_forward_v12 as sc
from test_nfl_atd_v12 import NOW_US, Env, v12_world

_OLD = []


def setUpModule():
    _OLD.append(fk.use_modules("atd_provenance_v12", "score_nfl_atd_forward_v12",
                               "price_nfl_atd_board_v12"))


def tearDownModule():
    fk.use_modules(*_OLD.pop())


class TestDryReviewWritesNothingV12(Env):
    def _isolated_dry_review(self, api, ids):
        with tempfile.TemporaryDirectory(prefix="atd-v12-dry-") as root:
            iso = Path(root) / "tmp"
            iso.mkdir()
            with mock.patch.object(tempfile, "tempdir", str(iso)), \
                    mock.patch.dict(os.environ, {"TMPDIR": str(iso)}):
                v = sc.review(ids, records_worktree=None, api=api, _dry=True, _now=NOW_US)
            left = sorted(p.name for p in iso.iterdir())
        return v, left

    def test_dry_review_writes_nothing(self):
        api, ids, _wt = v12_world()   # fixtures may use temp dirs; built before isolation
        v, left = self._isolated_dry_review(api, ids)
        self.assertEqual(v["verdict"], "BEATS_MARKET")
        self.assertEqual(left, [])

    def test_unaffected_by_concurrent_writers_in_shared_tmp(self):
        api, ids, _wt = v12_world()
        shared = tempfile.gettempdir()
        stop = threading.Event()
        made = []

        def noisy():
            while not stop.is_set():
                fd, p = tempfile.mkstemp(dir=shared, prefix="atd-v12-noise-")
                os.close(fd); made.append(p)
                stop.wait(0.001)

        t = threading.Thread(target=noisy, daemon=True)
        t.start()
        try:
            v, left = self._isolated_dry_review(api, ids)
        finally:
            stop.set(); t.join()
            for p in made:
                os.unlink(p)
        self.assertTrue(made)          # the shared temp dir really did change
        self.assertEqual(v["verdict"], "BEATS_MARKET")
        self.assertEqual(left, [])

    def test_isolation_detects_a_write(self):
        """Control: a dry review that wrote a temp file would be caught."""
        api, ids, _wt = v12_world()
        real = sc.review

        def leaky(*a, **k):
            tempfile.mkstemp()
            return real(*a, **k)

        with mock.patch.object(sc, "review", leaky):
            _v, left = self._isolated_dry_review(api, ids)
        self.assertEqual(len(left), 1)


if __name__ == "__main__":
    unittest.main()
