import unittest
from datetime import datetime, timezone

from sportsedge.mlb_source import GameSnapshot
from sportsedge.mlb_postseason_k_outs_forward_shadow import (
    MARKET_LINES, ProspectiveShadowError, build_prediction, postseason_shadow_p,
    settle_prediction,
)


def game(status="Preview"):
    return GameSnapshot(
        game_pk=12345, game_date="2026-10-10T00:00:00Z", status=status,
        away_id=100, away_name="Away", home_id=200, home_name="Home",
        away_probable_pitcher_id=111, away_probable_pitcher_name="Away Starter",
        home_probable_pitcher_id=222, home_probable_pitcher_name="Home Starter",
        retrieved_at="2026-10-09T22:00:00+00:00",
        official_date="2026-10-09",
    )


def feature(market):
    rows=[{"strikeouts":5,"outs":17,"earned_runs":1,
           "hits_allowed":4,"walks_allowed":1} for _ in range(10)]
    adj={"market":market,"beta":1 if market=="PITCHER_K" else -.25,
         "target_rel":1.0,"history_rel":[1.0]*10,
         "opponent_team_id":200,
         "index":"obidx" if market=="PITCHER_OUTS" else "kidx"}
    return {"game_pk":12345,"market":market,
            "retrieved_at":"2026-10-09T22:00:00+00:00",
            "source_subset_hash":"a"*64,
            "features":{"history_pool":rows,
                "opp_k_adjustment" if market=="PITCHER_K" else "opp_outs_adjustment":adj}}


class PostseasonForwardShadowTests(unittest.TestCase):
    def make(self, market="PITCHER_OUTS", line=12.5):
        return build_prediction(
            game=game(), pitcher_id=111, team_side="away",
            market=market,line=line,feature=feature(market),
            captured_at=datetime(2026,10,9,23,0,tzinfo=timezone.utc),
            schedule_sha256="b"*64,
        )

    def test_both_market_families_all_fixed_thresholds(self):
        for market,lines in MARKET_LINES.items():
            for line in lines:
                r=self.make(market,line)
                self.assertEqual(r["status"],"PREGAME_CAPTURED")
                self.assertLess(r["postseason_shadow_research_p_over"],
                                r["baseline_opponent_adjusted_p_over"])
                self.assertFalse(r["shadow_transfer_validated"])
                self.assertFalse(r["allow_betting_card"])
                self.assertEqual(len(r["receipt_sha256"]),64)

    def test_cannot_backfill_or_rewrite_post_start(self):
        with self.assertRaises(ProspectiveShadowError):
            build_prediction(game=game(),pitcher_id=111,team_side="away",
                market="PITCHER_OUTS",line=12.5,feature=feature("PITCHER_OUTS"),
                captured_at=datetime(2026,10,10,0,1,tzinfo=timezone.utc),
                schedule_sha256="b"*64)
        with self.assertRaises(ProspectiveShadowError):
            build_prediction(game=game("Final"),pitcher_id=111,team_side="away",
                market="PITCHER_K",line=2.5,feature=feature("PITCHER_K"),
                captured_at=datetime(2026,10,9,23,0,tzinfo=timezone.utc),
                schedule_sha256="b"*64)

    def test_incompatible_pitcher_identity_and_missing_opponent_fail(self):
        with self.assertRaises(ProspectiveShadowError):
            build_prediction(game=game(),pitcher_id=222,team_side="away",
                market="PITCHER_OUTS",line=12.5,feature=feature("PITCHER_OUTS"),
                captured_at=datetime(2026,10,9,23,0,tzinfo=timezone.utc),
                schedule_sha256="b"*64)
        f=feature("PITCHER_K")
        f["features"].pop("opp_k_adjustment")
        with self.assertRaises(ProspectiveShadowError):
            build_prediction(game=game(),pitcher_id=111,team_side="away",
                market="PITCHER_K",line=2.5,feature=f,
                captured_at=datetime(2026,10,9,23,0,tzinfo=timezone.utc),
                schedule_sha256="b"*64)

    def test_actual_start_pitcher_outs_and_k_settle_separately(self):
        official={"teams":{"away":{"pitchers":[111,333],
            "players":{"ID111":{"stats":{"pitching":{
                "inningsPitched":"4.1","strikeOuts":3}}}}}}}
        for market, line, expected in (("PITCHER_OUTS",12.5,13),("PITCHER_K",2.5,3)):
            r=self.make(market,line)
            final=settle_prediction(game=game("Final"),prediction=r,boxscore=official,
                settled_at=datetime(2026,10,10,5,0,tzinfo=timezone.utc),
                final_source_sha256="c"*64)
            self.assertEqual(final["status"],"GRADED")
            self.assertEqual(final["actual_count"],expected)
            self.assertTrue(final["actual_over"])
            self.assertIsInstance(final["shadow_minus_baseline_brier"],float)

    def test_changed_actual_starter_voids_not_backfills(self):
        r=self.make()
        outcome=settle_prediction(game=game("Final"),prediction=r,
            boxscore={"teams":{"away":{"pitchers":[333],"players":{}}}},
            settled_at=datetime(2026,10,10,5,0,tzinfo=timezone.utc),
            final_source_sha256="c"*64)
        self.assertEqual(outcome["status"],"VOID_NOT_ACTUAL_STARTER")
        self.assertIsNone(outcome["actual_count"])

    def test_hash_changed_prediction_cannot_grade(self):
        p=self.make()
        p["baseline_opponent_adjusted_p_over"]=0.01
        with self.assertRaises(ProspectiveShadowError):
            settle_prediction(game=game("Final"),prediction=p,boxscore={},
                settled_at=datetime(2026,10,10,5,0,tzinfo=timezone.utc),
                final_source_sha256="c"*64)

    def test_offset_is_only_descriptive_shadow(self):
        self.assertAlmostEqual(postseason_shadow_p(.773,"PITCHER_OUTS"),.541,places=2)


if __name__=="__main__":
    unittest.main()
