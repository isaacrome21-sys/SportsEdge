from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

import numpy as np


_SPEC = importlib.util.spec_from_file_location(
    "fit_football_baselines",
    Path(__file__).resolve().parents[1] / "scripts" / "fit_football_baselines.py",
)
assert _SPEC and _SPEC.loader
_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_mod)


class TestFootballBaselineDiagnostics(unittest.TestCase):
    def test_placebo_null_is_deterministic_and_has_requested_draw_count(self):
        rng = np.random.default_rng(9)
        xtr = rng.normal(size=(240, 6))
        ytr = rng.normal(size=240)
        xte = rng.normal(size=(80, 6))
        yte = rng.normal(size=80)
        a = _mod.placebo_null(xtr, ytr, xte, yte, alpha=10.0, draws=200, seed=20260910)
        b = _mod.placebo_null(xtr, ytr, xte, yte, alpha=10.0, draws=200, seed=20260910)
        self.assertEqual(a, b)
        self.assertEqual(a["draws"], 200)
        self.assertLessEqual(a["p95_r2_vs_mean"], 1.0)
        self.assertGreaterEqual(a["p95_r2_vs_mean"], a["median_r2_vs_mean"])

    def test_closing_verdict_prefers_lower_rmse_and_rejects_bad_sign(self):
        self.assertEqual(_mod.closing_line_verdict(13.2, 12.3, correlation=0.49), "WORSE_THAN_CLOSING_LINE")
        self.assertEqual(_mod.closing_line_verdict(11.9, 12.3, correlation=0.49), "BEATS_CLOSING_LINE")
        self.assertEqual(_mod.closing_line_verdict(11.9, 12.3, correlation=-0.49), "INVALID_SPREAD_SIGN_CONVENTION")


if __name__ == "__main__":
    unittest.main()
