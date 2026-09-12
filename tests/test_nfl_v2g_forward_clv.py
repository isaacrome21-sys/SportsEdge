import unittest

from sportsedge.sports.nfl.v2g_forward_clv import (
    CLV_SCHEMA, DECISION_SCHEMA, build_decisions, grade_close, weighted_probs,
)


class NFLV2GForwardCLVTests(unittest.TestCase):
    def policy(self):
        return {
            "schema_version":"SPORTSEDGE_NFL_V2G_FORWARD_CLV_POLICY_V1",
            "status":"FROZEN_BEFORE_FIRST_WEEK2_MARKET_DECISION",
            "candidate_id":"nfl_m2_scoring_event_v2g_candidate",
            "frozen_research_artifact_sha256":"b"*64,
            "decision_source":{"required_lock_status":["MATCH","LOCK_CREATED"]},
            "promotion_authority":False,"may_create_model_p":False,"official_status_granted":False,
        }

    def prediction(self):
        return {
            "schema_version":"NFL_M2_V2G_PROSPECTIVE_PREDICTION_V1",
            "game_id":"2026_02_PIT_NE","candidate_id":"nfl_m2_scoring_event_v2g_candidate",
            "artifact_sha256":"b"*64,"prediction_sha256":"a"*64,"schedule_snapshot_sha256":"c"*64,
            "away_team":"PIT","home_team":"NE","captured_at_utc":"2026-09-12T12:50:13+00:00","kickoff_utc":"2026-09-20T17:00:00+00:00",
            "market_prices_consumed":False,"promotion_authority":False,"may_create_model_p":False,"market_eligibility_changed":False,"official_status_granted":False,
            "score_distribution":[
                {"home_score":20,"away_score":17,"margin":3,"total":37,"weight":0.70},
                {"home_score":17,"away_score":20,"margin":-3,"total":37,"weight":0.20},
                {"home_score":24,"away_score":20,"margin":4,"total":44,"weight":0.10},
            ],
        }

    def opener(self):
        return {
            "capture_kind":"OPENER","week":2,"book":"draftkings","markets":["spreads","totals"],"lock_status":"MATCH","retrieved_at_utc":"2026-09-15T14:03:00+00:00",
            "games":[{
                "event_id":"evt-1","away_team":"Pittsburgh Steelers","home_team":"New England Patriots","commence_time":"2026-09-20T17:00:00Z","book":"draftkings",
                "spread":{"status":"OK","home_point":-3.0,"home_price":-110,"away_point":3.0,"away_price":-110},
                "total":{"status":"OK","point":41.5,"over_price":-110,"under_price":-110},
            }],
        }

    def close_event(self):
        return {
            "id":"evt-1","sport_key":"americanfootball_nfl","commence_time":"2026-09-20T17:00:00Z","home_team":"New England Patriots","away_team":"Pittsburgh Steelers",
            "bookmakers":[{"key":"draftkings","markets":[
                {"key":"spreads","outcomes":[{"name":"New England Patriots","point":-3.5,"price":-110},{"name":"Pittsburgh Steelers","point":3.5,"price":-110}]},
                {"key":"alternate_spreads","outcomes":[{"name":"New England Patriots","point":-3.0,"price":-105},{"name":"Pittsburgh Steelers","point":3.0,"price":-115}]},
                {"key":"totals","outcomes":[{"name":"Over","point":42.5,"price":-110},{"name":"Under","point":42.5,"price":-110}]},
                {"key":"alternate_totals","outcomes":[{"name":"Over","point":41.5,"price":-120},{"name":"Under","point":41.5,"price":100}]},
                {"key":"h2h","outcomes":[{"name":"New England Patriots","price":-130},{"name":"Pittsburgh Steelers","price":110}]},
            ]}],
        }

    def test_weighted_probability_not_row_count(self):
        win,push,loss=weighted_probs(self.prediction()["score_distribution"],"spread","home",-3.0)
        self.assertAlmostEqual(0.10,win)
        self.assertAlmostEqual(0.70,push)
        self.assertAlmostEqual(0.20,loss)
        self.assertNotAlmostEqual(1/3,win)

    def test_decision_uses_active_nonpush_probability_but_ev_keeps_push_refund(self):
        rows=build_decisions(self.prediction(),self.opener(),self.policy(),code_git_sha="d"*40)
        self.assertEqual(2,len(rows))
        spread=next(r for r in rows if r["market"]=="spread")
        self.assertEqual(DECISION_SCHEMA,spread["schema_version"])
        self.assertAlmostEqual(2/3,spread["model_prob"])
        self.assertAlmostEqual(0.20,spread["model_win_prob"])
        self.assertAlmostEqual(0.70,spread["model_push_prob"])
        self.assertAlmostEqual(0.10,spread["model_loss_prob"])
        self.assertEqual("PIT",spread["side"])
        self.assertEqual(0.0,spread["stake_units"])
        self.assertFalse(spread["promotion_authority"])

    def test_close_resolves_original_threshold_from_alternates(self):
        decisions=build_decisions(self.prediction(),self.opener(),self.policy(),code_git_sha="d"*40)
        rows=grade_close(decisions,self.close_event(),captured_at="2026-09-20T16:45:00+00:00")
        self.assertEqual(2,len(rows))
        self.assertTrue(all(r["schema_version"]==CLV_SCHEMA for r in rows))
        spread=next(r for r in rows if r["market"]=="spread")
        total=next(r for r in rows if r["market"]=="total")
        self.assertEqual(3.0,spread["probability_line"])
        self.assertEqual(41.5,total["probability_line"])
        expected_under_novig=0.5/(0.5+(120/220))
        self.assertAlmostEqual(expected_under_novig,total["closing_novig_prob"])
        self.assertFalse(spread["promotion_authority"])

    def test_missing_original_threshold_is_inconclusive(self):
        decisions=build_decisions(self.prediction(),self.opener(),self.policy(),code_git_sha="d"*40)
        event=self.close_event()
        event["bookmakers"][0]["markets"]=[m for m in event["bookmakers"][0]["markets"] if m["key"] not in {"alternate_spreads","alternate_totals"}]
        rows=grade_close(decisions,event,captured_at="2026-09-20T16:45:00+00:00")
        self.assertTrue(all(r["status"]=="INCONCLUSIVE_CLV_REFERENCE_LINE_MISMATCH" for r in rows))

    def test_market_contaminated_prediction_rejected(self):
        pred=self.prediction(); pred["market_prices_consumed"]=True
        with self.assertRaisesRegex(ValueError,"MARKET_LEAKAGE"):
            build_decisions(pred,self.opener(),self.policy(),code_git_sha="d"*40)


if __name__ == "__main__":
    unittest.main()
