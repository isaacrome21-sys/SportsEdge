import unittest

from sportsedge.sports.nfl.m2_v2_candidate import (
    NFLM2V2CandidateModel,
    NFLM2V2SupportPoint,
    NFL_M2_V2_CANDIDATE_MODEL_ID,
    NFL_M2_V2_DISTRIBUTION_CONTRACT,
    derive_nfl_m2_v2_score_distribution,
)
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT


class _MeanModel:
    margin_sigma = 1.0
    total_sigma = 1.0

    def predict(self, row):
        return 0.0, 0.0


class NFLM2V2BandwidthSplitTests(unittest.TestCase):
    def _model(self, *, shared=1.0, margin=1.0, total=1.0):
        return NFLM2V2CandidateModel(
            model_id=NFL_M2_V2_CANDIDATE_MODEL_ID,
            feature_contract=NFL_M2_FEATURE_CONTRACT,
            distribution_contract=NFL_M2_V2_DISTRIBUTION_CONTRACT,
            mean_model=_MeanModel(),
            support_points=(
                NFLM2V2SupportPoint(24, 21, 0.0, 2.0),
                NFLM2V2SupportPoint(28, 21, 2.0, 0.0),
                NFLM2V2SupportPoint(20, 20, -1.0, -1.0),
            ),
            train_seasons=(2022, 2023),
            kernel_scale=shared,
            margin_kernel_scale=margin,
            total_kernel_scale=total,
        )

    def test_equal_dimension_scales_preserve_shared_kernel_distribution(self):
        first = derive_nfl_m2_v2_score_distribution(
            self._model(shared=1.0, margin=1.0, total=1.0), {}
        )
        second = derive_nfl_m2_v2_score_distribution(
            self._model(shared=2.0, margin=1.0, total=1.0), {}
        )
        # derive() must consume the dimension-specific scales, not the legacy
        # shared metadata field. This locks backwards-compatible 1/1 behavior.
        self.assertEqual(first, second)

    def test_margin_and_total_scales_are_independent(self):
        narrow_margin = derive_nfl_m2_v2_score_distribution(
            self._model(margin=0.25, total=1.0), {}
        )
        narrow_total = derive_nfl_m2_v2_score_distribution(
            self._model(margin=1.0, total=0.25), {}
        )
        self.assertNotEqual(narrow_margin, narrow_total)
        self.assertAlmostEqual(sum(float(row["weight"]) for row in narrow_margin), 1.0)
        self.assertAlmostEqual(sum(float(row["weight"]) for row in narrow_total), 1.0)

    def test_split_bandwidth_path_remains_market_blind(self):
        model = self._model(margin=0.5, total=1.5)
        baseline = derive_nfl_m2_v2_score_distribution(model, {})
        contaminated = derive_nfl_m2_v2_score_distribution(
            model,
            {
                "spread_line": -14.5,
                "total_line": 99.5,
                "book": "MUST_NOT_ENTER_DISTRIBUTION",
                "home_spread_odds": -10000,
            },
        )
        self.assertEqual(baseline, contaminated)


if __name__ == "__main__":
    unittest.main()
