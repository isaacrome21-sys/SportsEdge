import unittest

from sportsedge.sports.nfl.research_game_model import FEATURE_NAMES, fit_ridge, game_vector, predict_ridge


class NFLGameModelResearchTests(unittest.TestCase):
    def test_game_vector_is_home_minus_away_only(self):
        home = {name: float(i + 2) for i, name in enumerate(FEATURE_NAMES)}
        away = {name: float(i + 1) for i, name in enumerate(FEATURE_NAMES)}
        self.assertEqual(game_vector(home, away), [1.0] * len(FEATURE_NAMES))

    def test_missing_feature_fails_closed(self):
        home = {name: 1.0 for name in FEATURE_NAMES}
        away = {name: 1.0 for name in FEATURE_NAMES}
        del away[FEATURE_NAMES[0]]
        with self.assertRaisesRegex(ValueError, "NFL_RESEARCH_FEATURE_MISSING"):
            game_vector(home, away)

    def test_ridge_fits_simple_relationship(self):
        x = [[0.0], [1.0], [2.0], [3.0], [4.0]]
        y = [1.0 + 2.0 * row[0] for row in x]
        coef = fit_ridge(x, y, alpha=1e-9)
        pred = predict_ridge(coef, [[5.0]])[0]
        self.assertAlmostEqual(pred, 11.0, places=5)

    def test_negative_alpha_rejected(self):
        with self.assertRaisesRegex(ValueError, "NFL_RESEARCH_ALPHA_INVALID"):
            fit_ridge([[1.0], [2.0]], [1.0, 2.0], alpha=-1.0)


if __name__ == "__main__":
    unittest.main()
