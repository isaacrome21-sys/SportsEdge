import unittest
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch
from sportsedge.generic_card_pipeline import run_generic_card
from sportsedge.live_slate import LiveGame,TeamLineup
from sportsedge.mlb_market_binding import audit_status,validate_binding as real_validate_binding
from sportsedge.mlb_binding_runtime import probability_binding_row as real_probability_binding_row

NOW=datetime(2026,9,8,1,0,tzinfo=timezone.utc)

def game(game_number=1):
    return LiveGame(game_pk=777,away_team_id=20,home_team_id=10,away_probable_pitcher_id=200,home_probable_pitcher_id=100,away_lineup=TeamLineup(20,"away",(),(),False),home_lineup=TeamLineup(10,"home",(),(),False),game_number=game_number,status="SCHEDULED")

def quote(market,entity,side,*,line=None,book="draftkings",retrieved_at=NOW):
    return {"game_id":"777","period":"FG","market":market,"entity_id":str(entity),"line":line,"side":side,"american_odds":-110,"book_key":book,"retrieved_at":retrieved_at,"ttl_seconds":300,"is_alternate":False,"raw_market_name":market.lower()}

def feature(market,entity):
    return {"game_id":"777","market":market,"entity_id":str(entity),"away_mean_runs":4.0,"home_mean_runs":4.5,"total_line":8.5}

def fake_run(model_p=.55,push=0.0):
    return SimpleNamespace(model_p=model_p,bet_status="PASS",reason="TEST_PASS",decision=SimpleNamespace(push_probability=push),model_input_hash="mi",distribution_sha256="dist",readout_sha256="ro",readout_version="v",engine_version="e",seed_policy="seed",mc_paths=1000,book_key="draftkings",sportsbook="DraftKings",quote_retrieved_at=NOW.isoformat(),offer_id=None)

class ProductionWiringTests(unittest.TestCase):
    def _run(self,quotes,features,*,live_game=None,run=None):
        markets={q["market"] for q in quotes}
        with patch("sportsedge.generic_card_pipeline.load_registry",return_value={"markets":{m:{} for m in markets}}),patch("sportsedge.generic_card_pipeline.engine_registry",return_value={m:object() for m in markets}),patch("sportsedge.generic_card_pipeline.run_candidate",return_value=run or fake_run()):
            return run_generic_card(games=[live_game or game()],feature_rows=features,quotes=quotes,ingestion_now=NOW,finalization_now=NOW)
    def test_all_four_wired_game_families_traverse_real_pipeline(self):
        cases=[([quote("MONEYLINE",10,"HOME"),quote("MONEYLINE",20,"AWAY")],[feature("MONEYLINE",10),feature("MONEYLINE",20)]),([quote("RUN_LINE",10,"HOME",line=-1.5),quote("RUN_LINE",20,"AWAY",line=1.5)],[feature("RUN_LINE",10),feature("RUN_LINE",20)]),([quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)],[feature("TOTALS",777)]),([quote("TEAM_TOTALS",10,"OVER",line=4.5),quote("TEAM_TOTALS",10,"UNDER",line=4.5)],[feature("TEAM_TOTALS",10)])]
        for qs,fs in cases:
            with self.subTest(market=qs[0]["market"]):
                out=self._run(qs,fs);self.assertEqual(len(out),2);self.assertTrue(all(r.bet_status=="PASS" for r in out),out)
    def test_bad_home_binding_blocks_only_bad_market(self):
        bad=quote("MONEYLINE",20,"HOME");good=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        out=self._run([bad]+good,[feature("MONEYLINE",20),feature("TOTALS",777)])
        self.assertEqual(out[0].bet_status,"BLOCKED");self.assertIn("SIDE_TEAM_MISMATCH",out[0].reason);self.assertTrue(all(r.bet_status=="PASS" for r in out[1:]))
    def test_same_signed_runline_pair_blocks(self):
        qs=[quote("RUN_LINE",10,"HOME",line=-1.5),quote("RUN_LINE",20,"AWAY",line=-1.5)]
        out=self._run(qs,[feature("RUN_LINE",10),feature("RUN_LINE",20)]);self.assertTrue(all(r.bet_status=="BLOCKED" for r in out));self.assertTrue(all("PAIRED_PRICE_REQUIRED_FOR_BINDING" in r.reason for r in out))
    def test_team_total_different_team_cannot_pair(self):
        qs=[quote("TEAM_TOTALS",10,"OVER",line=4.5),quote("TEAM_TOTALS",20,"UNDER",line=4.5)]
        out=self._run(qs,[feature("TEAM_TOTALS",10),feature("TEAM_TOTALS",20)]);self.assertTrue(all(r.bet_status=="BLOCKED" for r in out))
    def test_missing_official_game_number_is_per_market_block(self):
        qs=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        out=self._run(qs,[feature("TOTALS",777)],live_game=game(None));self.assertTrue(all(r.bet_status=="BLOCKED" for r in out));self.assertTrue(all("game_number" in r.reason or "ILLEGAL_GAME_NUMBER" in r.reason for r in out))
    def test_post_model_full_binding_is_called(self):
        qs=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        with patch("sportsedge.generic_card_pipeline.validate_binding",wraps=real_validate_binding) as spy,patch("sportsedge.generic_card_pipeline.load_registry",return_value={"markets":{"TOTALS":{}}}),patch("sportsedge.generic_card_pipeline.engine_registry",return_value={"TOTALS":object()}),patch("sportsedge.generic_card_pipeline.run_candidate",return_value=fake_run()):
            out=run_generic_card(games=[game()],feature_rows=[feature("TOTALS",777)],quotes=qs,ingestion_now=NOW,finalization_now=NOW)
        self.assertEqual(spy.call_count,2);self.assertTrue(all(r.bet_status=="PASS" for r in out))
    def test_wrong_probability_event_blocks_post_model(self):
        qs=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        def corrupt(**kwargs):
            r=real_probability_binding_row(**kwargs);r["probability_event_id"]="wrong-event";return r
        with patch("sportsedge.generic_card_pipeline.probability_binding_row",side_effect=corrupt):out=self._run(qs,[feature("TOTALS",777)])
        self.assertTrue(all(r.bet_status=="BLOCKED" for r in out));self.assertTrue(all("PROBABILITY_EVENT_ID_MISMATCH" in r.reason for r in out))
    def test_wrong_probability_side_blocks_post_model(self):
        qs=[quote("TOTALS",777,"OVER",line=8.5),quote("TOTALS",777,"UNDER",line=8.5)]
        def corrupt(**kwargs):
            r=real_probability_binding_row(**kwargs);r["probability_side"]="UNDER" if r["side"]=="OVER" else "OVER";return r
        with patch("sportsedge.generic_card_pipeline.probability_binding_row",side_effect=corrupt):out=self._run(qs,[feature("TOTALS",777)])
        self.assertTrue(all(r.bet_status=="BLOCKED" for r in out));self.assertTrue(all("PROBABILITY_SIDE_MISMATCH" in r.reason for r in out))
    def test_audit_status_is_exactly_four_of_thirty_eight(self):
        wired={"MONEYLINE","RUN_LINE","TOTALS","TEAM_TOTALS"};self.assertTrue(all(audit_status(m)=="PASS" for m in wired));self.assertTrue(all(audit_status(m)!="PASS" for m in {"F5_MONEYLINE","NRFI","HITS","PITCHER_K","FIRST_HOME_RUN"}))

if __name__=="__main__":unittest.main()
