import unittest

from sportsedge.sports.cfb.candidate_model_v2 import candidate_feature_names, candidate_feature_vector
from sportsedge.sports.cfb.candidate_registry_v2 import EQUAL, RELIABILITY, BLEND, GAMES
from sportsedge.sports.cfb.candidate_families import TEAM_METRIC_KEYS


def metrics(season, through_week, source, value, games):
    out = {key: float(value) for key in TEAM_METRIC_KEYS}
    out.update({
        "team": "T", "season": season, "through_week": through_week,
        "sample_source": source, "games_in_sample": games,
    })
    return out


def row():
    prior = metrics(2025, 99, "PRIOR_SEASON_FALLBACK", 0.2, 0)
    current = metrics(2026, 2, "CURRENT_SEASON_PRIOR_WEEKS", 0.4, 2)
    return {
        "season": 2026,
        "week": 3,
        "neutral_site": False,
        "weather": {"game_indoor": True},
        "home_metrics": current.copy(),
        "away_metrics": current.copy(),
        "home_prior_metrics": prior.copy(),
        "away_prior_metrics": prior.copy(),
        "home_current_metrics": current.copy(),
        "away_current_metrics": current.copy(),
    }


def week1_row():
    prior = metrics(2025, 99, "PRIOR_SEASON_FALLBACK", 0.2, 0)
    return {
        "season": 2026,
        "week": 1,
        "neutral_site": False,
        "weather": {"game_indoor": True},
        "home_metrics": prior.copy(),
        "away_metrics": prior.copy(),
        "home_prior_metrics": prior.copy(),
        "away_prior_metrics": prior.copy(),
        "home_current_metrics": prior.copy(),
        "away_current_metrics": prior.copy(),
    }


class TestCFBCandidateModelV2(unittest.TestCase):
    def test_three_metric_transform_families_keep_baseline_dimension(self):
        base = len(candidate_feature_names(EQUAL))
        for family in (EQUAL, RELIABILITY, BLEND):
            self.assertEqual(len(candidate_feature_names(family)), base)
            self.assertEqual(candidate_feature_vector(family, row()).shape, (base,))

    def test_games_family_appends_two_real_features(self):
        base = len(candidate_feature_names(EQUAL))
        names = candidate_feature_names(GAMES)
        vector = candidate_feature_vector(GAMES, row())
        self.assertEqual(len(names), base + 2)
        self.assertEqual(vector.shape, (base + 2,))
        self.assertEqual(names[-2:], ("home_games_in_sample_feature", "away_games_in_sample_feature"))
        self.assertAlmostEqual(float(vector[-2]), 2.0 / 12.0)
        self.assertAlmostEqual(float(vector[-1]), 2.0 / 12.0)

    def test_week1_prior_fallback_is_executable_for_all_frozen_families(self):
        base = len(candidate_feature_names(EQUAL))
        for family in (EQUAL, RELIABILITY, BLEND, GAMES):
            vector = candidate_feature_vector(family, week1_row())
            expected = base + 2 if family == GAMES else base
            self.assertEqual(vector.shape, (expected,))
        games_vector = candidate_feature_vector(GAMES, week1_row())
        self.assertEqual(float(games_vector[-2]), 0.0)
        self.assertEqual(float(games_vector[-1]), 0.0)


if __name__ == "__main__":
    unittest.main()
