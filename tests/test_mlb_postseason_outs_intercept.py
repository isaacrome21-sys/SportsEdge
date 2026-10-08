import unittest

from scripts.eval_mlb_postseason_outs_intercept import (
    FOLDS, INPUT_KEYS, adjusted_probability, fit_intercept,
    game_cluster_bootstrap, loss, starter_rows,
)


class PostseasonInterceptTemporalValidationTest(unittest.TestCase):
    def _rows(self,n=140):
        return [{"p_recent_only":0.75, "p_recent_plus_capped_prior":0.78,
                 "actual_over":float(i%3==0),"game_pk":i//3+1} for i in range(n)]

    def test_locked_forward_training_seasons(self):
        self.assertEqual(FOLDS,((2024,(2023,)),(2025,(2023,2024))))
        self.assertTrue(all(max(train)<target for target,train in FOLDS))

    def test_fit_shrinks_overconfident_regular_history(self):
        rows=self._rows()
        offset=fit_intercept(rows,"p_recent_only")
        self.assertLess(offset,-1)
        self.assertLess(adjusted_probability(0.80,offset),0.80)
        self.assertLess(loss(rows,"p_recent_only",offset)["log_loss"],
                        loss(rows,"p_recent_only")["log_loss"])

    def test_cluster_bootstrap_groups_same_game(self):
        rows=self._rows()
        offset=fit_intercept(rows,"p_recent_only")
        bounds=game_cluster_bootstrap(rows,source="p_recent_only",
                   intercept=offset,seed=123)
        self.assertEqual(len(bounds),2)
        self.assertLess(bounds[0],bounds[1])

    def test_rejects_wrong_audit_version_and_seasons(self):
        with self.assertRaises(ValueError):
            starter_rows({"version":"wrong","frozen_seasons":[2023,2024,2025],"starts":[]})
        with self.assertRaises(ValueError):
            starter_rows({"version":"mlb_postseason_starter_workload_audit_2023_2025_v1",
                "frozen_seasons":[2024,2025,2026],"starts":[]})

    def test_probability_validation(self):
        with self.assertRaises(ValueError):
            adjusted_probability(1.7,0.0)
        with self.assertRaises(ValueError):
            fit_intercept(self._rows(3),"p_recent_only")


if __name__=="__main__":
    unittest.main()
