import unittest
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge.generic_card_pipeline import run_generic_card
from sportsedge.live_slate import LiveGame,TeamLineup
from sportsedge.mlb_market_binding import MARKET_BINDINGS,audit_status,validate_binding as real_validate_binding
from sportsedge.mlb_binding_runtime import probability_binding_row as real_probability_binding_row
from sportsedge.orchestrator import MLB_EXTERNAL_BINDING_MODE,run_candidate

NOW=datetime(2026,9,8,1,0,tzinfo=timezone.utc)


def game(game_number=1):
    return LiveGame(game_pk=777,away_team_id=20,home_team_id=10,away_probable_pitcher_id=200,home_probable_pitcher_id=100,away_lineup=TeamLineup(20,"away",(),(),False),home_lineup=TeamLineup(10,"home",(),(),False),game_number=game_number,status="SCHEDULED")


def quote(market,entity,side,*,line=None,book="draftkings",retrieved_at=NOW,event_id="777",game_number=1,home_team_id="10",away_team_id="20"):
    return {
        "game_id":"777",
        "event_id":event_id,
        "game_number":game_number,
        "event_home_team_id":home_team_id,
        "event_away_team_id":away_team_id,
        "period":"FG",
        "market":market,
        "entity_id":str(entity),
        "line":line,
        "side":side,
        "american_odds":-110,
        "book_key":book,
        "retrieved_at":retrieved_at,
        "ttl_seconds":300,
        "is_alternate":False,
        "raw_market_name":market.lower(),
    }


def feature(market,entity):
    return {"game_id":"777","market":market,"entity_id":str(entity),"away_mean_runs":4.0,"home_mean_runs":4.5,"total_line":8.5}


def fake_run(model_p=.55,push=0.0):
    return SimpleNamespace(model_p=model_p,bet_status="PASS",reason="TEST_PASS",decision=SimpleNamespace(push_probability=push),model_input_hash="mi",distribution_sha256="dist",readout_sha256="ro",readout_version="v",engine_version="e",seed_policy="seed",mc_paths=1000,book_key="draftkings",sportsbook="DraftKings",quote_retrieved_at=NOW.isoformat(),offer_id=None)


class ProductionWiringTests(unittest.TestCase):
    def _run(self,quotes,features,*,live_game=None,run=None):
        markets={q["market"] for q in quotes}
        with patch("sportsedge.generic_card_pipeline.load_registry",return_value={"markets":{m:{} for m in markets}}),patch("sportsedge.generic_card_pipeline.engine_registry",return_value={m:object() for m in markets}),patch("sportsedge.generic_card_pipeline.run_candidate",return_value=run or fake_run()):
            return run_generic_card(games=[live_game or game()],feature_rows=features,quotes=quotes,ingestion_now=NOW,finalization_now=NOW)

    def test_all_four_wired_game_families_traverse_quote_bound_pipeline(self):
        cases=[
            ([quote("MONEYLINE",10,"HOME"),quote("MONEYLINE",20,"AWAY")],[feature("MONEYLINE",10),feature("MONEYLINE",20)]),
            ([quote("RUN_LINE",10,"HOME",line=-1.5),quote("RUN_LINE",20,"AWAY",line=1.5)],[feature("RUN_LINE",10),feature("RUN_LINE",20)]),
            ([quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)],[feature("TOTALS",777)]),
            ([quote("TEAM_TOTALS",10,"OVER",line=4.5),quote("TEAM_TOTALS",10,"UNDER",line=4.5)],[feature("TEAM_TOTALS",10)]),
        ]
        for qs,fs in cases:
            with self.subTest(market=qs[0]["market"]):
                out=self._run(qs,fs)
                self.assertEqual(len(out),2)
                self.assertTrue(all(r.bet_status=="PASS" for r in out),out)

    def test_bad_home_binding_blocks_only_bad_market(self):
        bad=quote("MONEYLINE",20,"HOME")
        good=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        out=self._run([bad]+good,[feature("MONEYLINE",20),feature("TOTALS",777)])
        self.assertEqual(out[0].bet_status,"BLOCKED")
        self.assertIn("SIDE_TEAM_MISMATCH",out[0].reason)
        self.assertTrue(all(r.bet_status=="PASS" for r in out[1:]))

    def test_source_event_mismatch_blocks_only_bad_row(self):
        bad=quote("MONEYLINE",10,"HOME",event_id="999")
        good=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        out=self._run([bad]+good,[feature("MONEYLINE",10),feature("TOTALS",777)])
        self.assertEqual(out[0].bet_status,"BLOCKED")
        self.assertIn("SOURCE_EVENT_MISMATCH",out[0].reason)
        self.assertTrue(all(r.bet_status=="PASS" for r in out[1:]))

    def test_missing_source_identity_blocks_instead_of_backfilling(self):
        bad=quote("MONEYLINE",10,"HOME")
        bad.pop("event_home_team_id")
        good=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        out=self._run([bad]+good,[feature("MONEYLINE",10),feature("TOTALS",777)])
        self.assertEqual(out[0].bet_status,"BLOCKED")
        self.assertIn("MISSING_SOURCE_BINDING_IDENTITY:MONEYLINE:event_home_team_id",out[0].reason)
        self.assertTrue(all(r.bet_status=="PASS" for r in out[1:]))

    def test_same_signed_runline_pair_blocks(self):
        qs=[quote("RUN_LINE",10,"HOME",line=-1.5),quote("RUN_LINE",20,"AWAY",line=-1.5)]
        out=self._run(qs,[feature("RUN_LINE",10),feature("RUN_LINE",20)])
        self.assertTrue(all(r.bet_status=="BLOCKED" for r in out))
        self.assertTrue(all("PAIRED_PRICE_REQUIRED_FOR_BINDING" in r.reason for r in out))

    def test_team_total_different_team_cannot_pair(self):
        qs=[quote("TEAM_TOTALS",10,"OVER",line=4.5),quote("TEAM_TOTALS",20,"UNDER",line=4.5)]
        out=self._run(qs,[feature("TEAM_TOTALS",10),feature("TEAM_TOTALS",20)])
        self.assertTrue(all(r.bet_status=="BLOCKED" for r in out))

    def test_missing_official_game_number_is_per_market_block(self):
        qs=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        out=self._run(qs,[feature("TOTALS",777)],live_game=game(None))
        self.assertTrue(all(r.bet_status=="BLOCKED" for r in out))
        self.assertTrue(all("OFFICIAL_GAME_NUMBER_MISSING" in r.reason for r in out))

    def test_post_model_full_binding_is_called(self):
        qs=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        with patch("sportsedge.generic_card_pipeline.validate_binding",wraps=real_validate_binding) as spy,patch("sportsedge.generic_card_pipeline.load_registry",return_value={"markets":{"TOTALS":{}}}),patch("sportsedge.generic_card_pipeline.engine_registry",return_value={"TOTALS":object()}),patch("sportsedge.generic_card_pipeline.run_candidate",return_value=fake_run()):
            out=run_generic_card(games=[game()],feature_rows=[feature("TOTALS",777)],quotes=qs,ingestion_now=NOW,finalization_now=NOW)
        self.assertEqual(spy.call_count,2)
        self.assertTrue(all(r.bet_status=="PASS" for r in out))

    def test_wrong_probability_event_blocks_post_model(self):
        qs=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        def corrupt(**kwargs):
            r=real_probability_binding_row(**kwargs);r["probability_event_id"]="wrong-event";return r
        with patch("sportsedge.generic_card_pipeline.probability_binding_row",side_effect=corrupt):
            out=self._run(qs,[feature("TOTALS",777)])
        self.assertTrue(all(r.bet_status=="BLOCKED" for r in out))
        self.assertTrue(all("PROBABILITY_EVENT_ID_MISMATCH" in r.reason for r in out))

    def test_wrong_probability_side_blocks_post_model(self):
        qs=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        def corrupt(**kwargs):
            r=real_probability_binding_row(**kwargs);r["probability_side"]="UNDER" if r["side"]=="OVER" else "OVER";return r
        with patch("sportsedge.generic_card_pipeline.probability_binding_row",side_effect=corrupt):
            out=self._run(qs,[feature("TOTALS",777)])
        self.assertTrue(all(r.bet_status=="BLOCKED" for r in out))
        self.assertTrue(all("PROBABILITY_SIDE_MISMATCH" in r.reason for r in out))

    def test_external_binding_mode_never_calls_legacy_candidate_binder(self):
        q=quote("TOTALS",777,"OVER",line=8.5)
        opposite=quote("TOTALS",777,"UNDER",line=8.5)
        model_input={"game_id":"777","market":"TOTALS","entity_id":"777","line":8.5,"side":"OVER","away_mean_runs":4.0,"home_mean_runs":4.5}
        with patch("sportsedge.orchestrator.bind_candidate",side_effect=AssertionError("legacy binder must not run")),patch("sportsedge.orchestrator.require_production_edge_floor",side_effect=RuntimeError("AFTER_BINDING_SENTINEL")):
            result=run_candidate(model_input=model_input,quote=q,paired_quote=opposite,deployment={},engine_fn=lambda _: {"model_p":0.55},ingestion_now=NOW,finalization_now=NOW,candidate_binding_mode=MLB_EXTERNAL_BINDING_MODE)
        self.assertEqual(result.bet_status,"BLOCKED")
        self.assertIn("AFTER_BINDING_SENTINEL",result.reason)
        self.assertNotIn("legacy binder",result.reason)

    def test_engine_cannot_smuggle_source_binding_identity(self):
        q=quote("TOTALS",777,"OVER",line=8.5)
        opposite=quote("TOTALS",777,"UNDER",line=8.5)
        model_input={"game_id":"777","market":"TOTALS","entity_id":"777","line":8.5,"side":"OVER","away_mean_runs":4.0,"home_mean_runs":4.5}
        result=run_candidate(model_input=model_input,quote=q,paired_quote=opposite,deployment={},engine_fn=lambda _: {"model_p":0.55,"event_id":"777"},ingestion_now=NOW,finalization_now=NOW,candidate_binding_mode=MLB_EXTERNAL_BINDING_MODE)
        self.assertEqual(result.bet_status,"BLOCKED")
        self.assertIn("engine output contains quote/orchestration source identity",result.reason)

    def test_audit_remains_zero_of_thirty_eight_without_live_source_evidence(self):
        self.assertEqual(len(MARKET_BINDINGS),38)
        self.assertEqual(sum(audit_status(m)=="PASS" for m in MARKET_BINDINGS),0)


if __name__=="__main__":
    unittest.main()
