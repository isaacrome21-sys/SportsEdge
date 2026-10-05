import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path
import unittest

from scripts import intake_mlb_lines_issue as INTAKE

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "research_mlb_f5_nrfi_tightening",
    ROOT / "scripts" / "research_mlb_f5_nrfi_tightening.py",
)
R = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = R
assert SPEC.loader is not None
SPEC.loader.exec_module(R)


def row(day, *, runs_for=4, runs_against=4, i1_for=0, i1_against=0, f5_for=2, f5_against=2):
    return {
        "day": day,
        "runs_for": runs_for,
        "runs_against": runs_against,
        "i1_for": i1_for,
        "i1_against": i1_against,
        "f5_for": f5_for,
        "f5_against": f5_against,
    }


class F5NRFITighteningResearchTests(unittest.TestCase):
    def test_research_directive_is_registered(self):
        self.assertEqual(INTAKE.research_directive("RESEARCH f5_nrfi_tightening"), "f5_nrfi_tightening")

    def test_smoothing_adds_league_support_and_conserves_mass(self):
        got = R.smoothed_pmf([0, 0, 1, 1], {0: 0.5, 1: 0.25, 2: 0.25}, 5)
        self.assertAlmostEqual(sum(got.values()), 1.0, places=12)
        self.assertGreater(got[2], 0.0)
        base = R.smoothed_pmf([0, 0, 1, 1], {0: 0.5, 1: 0.25, 2: 0.25}, 0)
        self.assertEqual(base.get(2, 0.0), 0.0)

    def test_f5_exact_score_metric_rewards_observed_support(self):
        weak = R.f5_metrics({0: 1.0}, {0: 1.0}, 2, 1)
        strong = R.f5_metrics({2: 0.8, 0: 0.2}, {1: 0.8, 0: 0.2}, 2, 1)
        self.assertLess(strong["nll"], weak["nll"])

    def test_direct_nrfi_is_probability_and_complementable(self):
        start = date(2026, 9, 1)
        away = [row(start + timedelta(days=i), i1_for=0 if i < 7 else 1, i1_against=0 if i < 6 else 1) for i in range(10)]
        home = [row(start + timedelta(days=i), i1_for=0 if i < 6 else 1, i1_against=0 if i < 8 else 1) for i in range(10)]
        p = R.direct_nrfi(away, home, 0.72, 15)
        self.assertGreaterEqual(p, 0.0)
        self.assertLessEqual(p, 1.0)
        self.assertAlmostEqual(p + (1.0-p), 1.0, places=12)

    def test_strength_zero_exactly_matches_current_jeffreys_production_math(self):
        start = date(2026, 9, 1)
        away = [row(start + timedelta(days=i), i1_for=0 if i < 7 else 1, i1_against=0 if i < 6 else 1) for i in range(10)]
        home = [row(start + timedelta(days=i), i1_for=0 if i < 6 else 1, i1_against=0 if i < 8 else 1) for i in range(10)]

        def zero_probability(values):
            return (sum(values) + 0.5) / (len(values) + 1.0)

        away_off = zero_probability([int(r["i1_for"] == 0) for r in away])
        home_def = zero_probability([int(r["i1_against"] == 0) for r in home])
        home_off = zero_probability([int(r["i1_for"] == 0) for r in home])
        away_def = zero_probability([int(r["i1_against"] == 0) for r in away])
        expected = (0.5 * away_off + 0.5 * home_def) * (0.5 * home_off + 0.5 * away_def)

        self.assertAlmostEqual(R.direct_nrfi(away, home, 0.72, 0), expected, places=12)
        self.assertEqual(R.NRFI_BASE, "production_empirical_jeffreys")

    def test_same_day_games_are_not_prior_history(self):
        target = date(2026, 9, 2)
        rows = [row(date(2026, 9, 1)), row(target), row(target)]
        got = R.prior_team(rows, target)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["day"], date(2026, 9, 1))

    def test_cluster_bootstrap_is_deterministic(self):
        rows = []
        for i in range(20):
            rows.append({
                "date": f"2025-07-{(i % 10)+1:02d}",
                "base": {"loss": 0.7},
                "selected": {"loss": 0.6},
            })
        a = R.bootstrap(rows, "selected", "base", "loss")
        b = R.bootstrap(rows, "selected", "base", "loss")
        self.assertEqual(a, b)
        self.assertLess(a["hi"], 0.0)


if __name__ == "__main__":
    unittest.main()
