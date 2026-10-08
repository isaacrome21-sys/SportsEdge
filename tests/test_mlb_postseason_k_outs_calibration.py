import unittest
from scripts.eval_mlb_postseason_k_outs_calibration import (
    CHRONOLOGICAL_FOLDS, fit_intercept, shifted, metrics, game_cluster_interval,
)


class PostseasonKOutsResearchTests(unittest.TestCase):
    def rows(self, n=120):
        return [
            {"year":2023,"game_pk":i//2,"pitcher_id":100+i,
             "p_recent_only":0.80,"p_recent_plus_capped_prior":0.75,
             "outcome":float(i%4==0)} for i in range(n)
        ]

    def test_chronological_folds_never_fit_on_target_year(self):
        self.assertEqual(CHRONOLOGICAL_FOLDS,((2024,(2023,)),(2025,(2023,2024))))
        self.assertTrue(all(max(training)<target for target,training in CHRONOLOGICAL_FOLDS))

    def test_training_only_offset_redresses_high_probabilities(self):
        rows=self.rows()
        fit=fit_intercept(rows,"p_recent_only")
        self.assertLess(fit,0)
        self.assertLess(shifted(.89,fit),.89)
        self.assertLess(metrics(rows,"p_recent_only",fit)["brier"],
                        metrics(rows,"p_recent_only",0)["brier"])

    def test_proper_game_level_resampling(self):
        rows=self.rows()
        fit=fit_intercept(rows,"p_recent_only")
        bounds=game_cluster_interval(rows,"p_recent_only",fit,seed=2024)
        self.assertEqual(len(bounds),2)
        self.assertLess(bounds[0],bounds[1])

    def test_invalid_probability_fails_closed(self):
        with self.assertRaises(ValueError):
            shifted(1.3,-.5)
        with self.assertRaises(ValueError):
            fit_intercept(self.rows(4),"p_recent_only")


if __name__=="__main__":
    unittest.main()
