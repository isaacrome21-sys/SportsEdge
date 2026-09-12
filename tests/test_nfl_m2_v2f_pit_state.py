from __future__ import annotations

import unittest

from sportsedge.sports.nfl.m2_history_features import _Stats
from sportsedge.sports.nfl.m2_v2f_pit_state import blended_state_view


class NFLM2V2FPITStateTests(unittest.TestCase):
    @staticmethod
    def _stats(*, off: float, deff: float, passes: float, rush: float, success: int, explosive: int,
               pressure_for: int, pressure_allowed: int, plays: int = 10) -> _Stats:
        return _Stats(
            off_epa_sum=off * plays,
            off_plays=plays,
            def_epa_sum=deff * plays,
            def_plays=plays,
            pass_epa_sum=passes * plays,
            pass_plays=plays,
            rush_epa_sum=rush * plays,
            rush_plays=plays,
            success=success,
            explosive=explosive,
            pressure_for=pressure_for,
            pressure_for_n=plays,
            pressure_allowed=pressure_allowed,
            pressure_allowed_n=plays,
        )

    def test_week_one_uses_real_prior_instead_of_zero_current(self) -> None:
        current = _Stats()
        prior = self._stats(
            off=0.20, deff=-0.10, passes=0.30, rush=0.05,
            success=6, explosive=2, pressure_for=4, pressure_allowed=3,
        )
        view = blended_state_view(current, prior, prior_weight=1.0)
        self.assertAlmostEqual(view.off_epa, 0.20)
        self.assertAlmostEqual(view.def_epa, -0.10)
        self.assertAlmostEqual(view.pass_epa, 0.30)
        self.assertAlmostEqual(view.rush_epa, 0.05)
        self.assertAlmostEqual(view.success_rate, 0.60)
        self.assertAlmostEqual(view.explosive_rate, 0.20)
        self.assertAlmostEqual(view.pressure_for, 0.40)
        self.assertAlmostEqual(view.pressure_allowed, 0.30)
        self.assertTrue(view.prior_available)
        self.assertEqual(view.prior_weight_applied, 1.0)

    def test_zero_weight_is_exact_current_state(self) -> None:
        current = self._stats(
            off=0.11, deff=-0.04, passes=0.19, rush=0.02,
            success=5, explosive=1, pressure_for=2, pressure_allowed=4,
        )
        prior = self._stats(
            off=-0.30, deff=0.22, passes=-0.20, rush=-0.10,
            success=2, explosive=0, pressure_for=1, pressure_allowed=6,
        )
        view = blended_state_view(current, prior, prior_weight=0.0)
        self.assertAlmostEqual(view.off_epa, current.off_epa())
        self.assertAlmostEqual(view.def_epa, current.def_epa())
        self.assertAlmostEqual(view.pass_epa, current.pass_epa())
        self.assertAlmostEqual(view.rush_epa, current.rush_epa())
        self.assertAlmostEqual(view.success_rate, current.success_rate())

    def test_missing_prior_does_not_create_synthetic_zero_prior(self) -> None:
        current = self._stats(
            off=0.15, deff=-0.08, passes=0.18, rush=0.07,
            success=7, explosive=3, pressure_for=5, pressure_allowed=2,
        )
        view = blended_state_view(current, None, prior_weight=0.95)
        self.assertAlmostEqual(view.off_epa, current.off_epa())
        self.assertAlmostEqual(view.def_epa, current.def_epa())
        self.assertAlmostEqual(view.pass_epa, current.pass_epa())
        self.assertAlmostEqual(view.rush_epa, current.rush_epa())
        self.assertAlmostEqual(view.pressure_for, current.pressure_for_rate())
        self.assertAlmostEqual(view.pressure_allowed, current.pressure_allowed_rate())
        self.assertFalse(view.prior_available)
        self.assertEqual(view.prior_weight_applied, 0.0)

    def test_invalid_weight_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "NFL_M2_V2F_PRIOR_WEIGHT_INVALID"):
            blended_state_view(_Stats(), _Stats(), prior_weight=1.01)


if __name__ == "__main__":
    unittest.main()
