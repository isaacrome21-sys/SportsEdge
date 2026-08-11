import unittest

from sportsedge.hits_engine import FEATURE_CONTRACT_VERSION as HITS_FEATURE_VERSION
from sportsedge.total_bases_engine import FEATURE_CONTRACT_VERSION as TB_FEATURE_VERSION
from sportsedge.live_slate import LiveSlateError, lineup_from_rows, make_live_game, assemble_hitter_candidate
from sportsedge.mlb_source import GameSnapshot


def rows(start=100):
    return [{"player_id": start+i, "slot": i+1, "sequence": 0} for i in range(9)]


class LiveSlateTests(unittest.TestCase):
    def snapshot(self):
        return GameSnapshot(
            game_pk=777, game_date="2026-08-10T23:00:00Z", status="Preview",
            away_id=1, away_name="Away", home_id=2, home_name="Home",
            away_probable_pitcher_id=11, away_probable_pitcher_name="A SP",
            home_probable_pitcher_id=22, home_probable_pitcher_name="H SP",
            retrieved_at="2026-08-10T20:00:00+00:00",
        )

    def feature(self, player_id=100):
        return {
            "game_pk":777,"player_id":player_id,"team_id":1,"market":"HITS",
            "feature_version":HITS_FEATURE_VERSION,
            "b_rate":.245,"p_rate":.232,"pa_pool":[4,4,5,3,4,4],
        }

    def tb_feature(self, player_id=100):
        return {
            "game_pk":777,"player_id":player_id,"team_id":1,"market":"TOTAL_BASES",
            "feature_version":TB_FEATURE_VERSION,
            "rates":{"s":.15,"d":.05,"t":.005,"hr":.04},
            "p_h":.23,"p_hr":.035,"park":1.02,"pa_pool":[4,4,5,3,4,4],
        }

    def quote(self, player_id=100, market="HITS"):
        return {"game_id":"777","market":market,"entity_id":str(player_id),"line":.5,"side":"OVER","american_odds":-125,"retrieved_at":"2026-08-10T20:00:00+00:00","ttl_seconds":300}

    def game(self, away=None, home=None):
        return make_live_game(self.snapshot(), away or rows(100), home or rows(200))

    def test_nine_primary_slots_confirms_lineup(self):
        self.assertTrue(lineup_from_rows(1,"away",rows(100)).confirmed)

    def test_missing_primary_slot_is_not_confirmed(self):
        self.assertFalse(lineup_from_rows(1,"away",rows(100)[:-1]).confirmed)

    def test_duplicate_player_fails_closed(self):
        r=rows(100); r[-1]={"player_id":100,"slot":9,"sequence":0}
        with self.assertRaises(LiveSlateError): lineup_from_rows(1,"away",r)

    def test_builds_canonical_hits_candidate(self):
        c=assemble_hitter_candidate(game=self.game(),market="HITS",feature_row=self.feature(),quote=self.quote())
        mi=c["model_input"]
        self.assertEqual(mi["feature_version"],HITS_FEATURE_VERSION)
        self.assertEqual(set(mi["features"]),{"b_rate","p_rate","pa_pool"})
        self.assertNotIn("american_odds",mi)

    def test_builds_total_bases_candidate(self):
        c=assemble_hitter_candidate(game=self.game(),market="TOTAL_BASES",feature_row=self.tb_feature(),quote=self.quote(market="TOTAL_BASES"))
        self.assertEqual(c["model_input"]["feature_version"],TB_FEATURE_VERSION)
        self.assertEqual(set(c["model_input"]["features"]),{"rates","p_h","p_hr","park","pa_pool"})

    def test_missing_feature_version_fails_closed(self):
        f=self.feature(); del f["feature_version"]
        with self.assertRaises(LiveSlateError): assemble_hitter_candidate(game=self.game(),market="HITS",feature_row=f,quote=self.quote())

    def test_wrong_feature_version_fails_closed(self):
        f=self.feature(); f["feature_version"]="research_v999"
        with self.assertRaises(LiveSlateError): assemble_hitter_candidate(game=self.game(),market="HITS",feature_row=f,quote=self.quote())

    def test_tb_version_cannot_feed_hits(self):
        f=self.feature(); f["feature_version"]=TB_FEATURE_VERSION
        with self.assertRaises(LiveSlateError): assemble_hitter_candidate(game=self.game(),market="HITS",feature_row=f,quote=self.quote())

    def test_feature_market_mismatch_fails(self):
        with self.assertRaises(LiveSlateError): assemble_hitter_candidate(game=self.game(),market="TOTAL_BASES",feature_row=self.feature(),quote=self.quote(market="TOTAL_BASES"))

    def test_quote_player_mismatch_fails(self):
        with self.assertRaises(LiveSlateError): assemble_hitter_candidate(game=self.game(),market="HITS",feature_row=self.feature(),quote=self.quote(101))

    def test_player_absent_from_lineup_fails(self):
        with self.assertRaises(LiveSlateError): assemble_hitter_candidate(game=self.game(),market="HITS",feature_row=self.feature(999),quote=self.quote(999))

    def test_unconfirmed_lineup_blocked_when_required(self):
        with self.assertRaises(LiveSlateError): assemble_hitter_candidate(game=self.game(away=rows(100)[:-1]),market="HITS",feature_row=self.feature(),quote=self.quote(),require_confirmed_lineup=True)

    def test_projected_allowed_only_when_explicit(self):
        c=assemble_hitter_candidate(game=self.game(away=rows(100)[:-1]),market="HITS",feature_row=self.feature(),quote=self.quote(),require_confirmed_lineup=False)
        self.assertEqual(c["model_input"]["lineup_status"],"PROJECTED")

    def test_rng_identity_changes_with_feature_contents(self):
        c1=assemble_hitter_candidate(game=self.game(),market="HITS",feature_row=self.feature(),quote=self.quote())
        f2=self.feature(); f2["pa_pool"]=[4,4,5,3,4,5]
        c2=assemble_hitter_candidate(game=self.game(),market="HITS",feature_row=f2,quote=self.quote())
        self.assertNotEqual(c1["model_input"]["build_hash"],c2["model_input"]["build_hash"])

    def test_nonfinite_features_fail(self):
        f=self.feature(); f["b_rate"]=float("nan")
        with self.assertRaises(LiveSlateError): assemble_hitter_candidate(game=self.game(),market="HITS",feature_row=f,quote=self.quote())


if __name__ == "__main__": unittest.main()
