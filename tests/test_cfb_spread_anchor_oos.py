"""Research-only chronological CFB spread anchor: no runtime or Model_P authority."""
import unittest
from scripts.research_cfb_spread_anchor_oos import assemble,evaluate,clustered_slope_ci

def samples(seasons=range(2016,2026),slope=0.):
    records=[]
    for year in seasons:
        for j in range(150):
            x=((j*13)%71-35)/3
            e=(((j*17)%31)-15)/6+(year%3-1)*.2
            records.append({"game_id":f"{year}-{j}","season":year,
                            "x":x,"y":slope*x+e})
    return records

class SpreadAnchorOOSTests(unittest.TestCase):
    def test_home_handicap_sign(self):
        rows=assemble({"1":{"season":2023,"model_margin":8,"actual_margin":6}},
                      {"lines_2023":{"1":{"spread":-3.5}}})
        self.assertEqual((rows[0]["market_margin"],rows[0]["x"],rows[0]["y"]),
                         (3.5,4.5,2.5))
    def test_future_season_outcomes_never_change_previous_fold(self):
        first=evaluate(samples())
        damaged=[{**r,"y":r["y"]+500} if r["season"]==2025 else r for r in samples()]
        changed=evaluate(damaged)
        self.assertEqual(first["folds"][-2],changed["folds"][-2])
        self.assertTrue(all(f["max_train_season"]<f["season"] for f in first["folds"]))
    def test_recovers_known_margin_signal(self):
        report=evaluate(samples(slope=.2))
        self.assertAlmostEqual(report["heldout_residual_weight_diagnostic"]["weight"],.2,delta=.03)
        self.assertFalse(report["ci_includes_zero"])
    def test_null_signal_retains_off(self):
        data=samples()
        for r in data: r["y"]=float(r["season"]%3)
        result=evaluate(data)
        self.assertTrue(result["ci_includes_zero"])
        self.assertEqual(result["status"],"NO_PROVEN_SPREAD_EDGE_LANE_OFF")
    def test_cluster_minimum(self):
        with self.assertRaisesRegex(ValueError,"CLUSTERS"):
            clustered_slope_ci(samples(range(2021,2023)))
if __name__=="__main__": unittest.main()
