import unittest
from sportsedge.first_hr_order_engine import build_shared_first_hr_engine_session, simulate_first_hr_distribution


def lineup(start, p_hr):
    return [{"player_id": start+i, "slot": i+1, "p_hr": p_hr if i == 0 else 0.0, "p_non_hr_on_base": 0.0} for i in range(9)]


class FirstHROrderTests(unittest.TestCase):
    def test_away_leadoff_gets_first_opportunity(self):
        features={"away_lineup":lineup(100,1.0),"home_lineup":lineup(200,1.0)}
        dist=simulate_first_hr_distribution(features,simulations=1000,build_hash="a"*64)
        self.assertEqual(dist.winner_probabilities,{"100":1.0})
        self.assertEqual(dist.no_home_run_probability,0.0)

    def test_no_hr_mass_is_explicit(self):
        features={"away_lineup":lineup(100,0.0),"home_lineup":lineup(200,0.0)}
        dist=simulate_first_hr_distribution(features,simulations=1000,build_hash="b"*64)
        self.assertEqual(dist.winner_probabilities,{})
        self.assertEqual(dist.no_home_run_probability,1.0)

    def test_player_and_side_are_readout_only(self):
        features={"away_lineup":lineup(100,0.08),"home_lineup":lineup(200,0.08)}
        engine=build_shared_first_hr_engine_session()
        base={"game_id":"1","market":"FIRST_HOME_RUN","line":0.5,"features":features,"feature_source_hash":"c"*64,"simulations":2000}
        yes=engine({**base,"entity_id":"100","side":"YES"})
        no=engine({**base,"entity_id":"100","side":"NO"})
        other=engine({**base,"entity_id":"200","side":"YES"})
        self.assertEqual(yes["distribution_sha256"],no["distribution_sha256"])
        self.assertEqual(yes["distribution_sha256"],other["distribution_sha256"])
        self.assertAlmostEqual(yes["model_p"]+no["model_p"],1.0)
        self.assertNotEqual(yes["readout_sha256"],other["readout_sha256"])

if __name__ == "__main__": unittest.main()
