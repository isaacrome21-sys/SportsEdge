import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.live_slate import make_live_game, LiveSlateError
from sportsedge.mlb_source import GameSnapshot
from sportsedge.pitcher_live import assemble_pitcher_bb_candidate
from sportsedge.pitcher_card_pipeline import run_pitcher_bb_card

UTC=timezone.utc; NOW=datetime(2026,8,10,20,0,tzinfo=UTC)
def rows(start): return [{"player_id":start+i,"slot":i+1,"sequence":0} for i in range(9)]
def game():
    snap=GameSnapshot(game_pk=777,game_date="2026-08-10T23:00:00Z",status="Preview",away_id=1,away_name="Away",home_id=2,home_name="Home",away_probable_pitcher_id=11,away_probable_pitcher_name="Away SP",home_probable_pitcher_id=22,home_probable_pitcher_name="Home SP",retrieved_at="2026-08-10T19:59:00+00:00")
    return make_live_game(snap,rows(100),rows(200))
def feature(pid=11,team=1): return {"game_pk":777,"player_id":pid,"team_id":team,"market":"PITCHER_BB","feature_version":"pitcher_bb_features_v1","own_bb":20,"own_bfp":220,"rolling_league_rate":.082,"pool":[22,24,25,27],"league_pool":[20,21,23,24,25,26,27,28]}
def quote(pid=11,side="OVER",odds=100,line=1.5): return {"game_id":"777","period":"FG","market":"PITCHER_BB","entity_id":str(pid),"line":line,"side":side,"book_key":"draftkings","is_alternate":False,"raw_market_name":"Pitcher Walks","american_odds":odds,"retrieved_at":NOW,"ttl_seconds":300}
def pair(): return [quote(side="OVER",odds=100),quote(side="UNDER",odds=-120)]
def deployed_registry(path): path.write_text(json.dumps({"schema_version":1,"markets":{"PITCHER_BB":{"eligible":True,"stage":"DEPLOYED","reason":"test"}}}))
def floor_registry(path):
    devig={"policy_id":"EDGE_FLOOR_DEVIG_V1","status":"FROZEN_PRE_DERIVATION","longshot_trigger_american_odds":400,"longshot_trigger_rule":"EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400","sensitivity_methods":["MULTIPLICATIVE_V1","POWER_V1","SHIN_V1"],"sensitivity_limit_absolute_probability_points":0.01,"stable_candidate_estimator":"MULTIPLICATIVE_V1","longshot_candidate_estimator":"POWER_V1","haircut_probability_points":0.0,"aggregation_rule":"ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS","sensitivity_failure":"BLOCK"}
    path.write_text(json.dumps({"truth_gate":{"schema_version":2,"production":{"fail_closed":True,"allow_cli_floor_override":False,"require_frozen_floor_for_eligible_market":True},"devig_policy":devig,"edge_floors":{"PITCHER_BB":{"status":"FROZEN","value_probability_points":0.01,"method_version":"test_fixture_v1","evidence":{"evidence_sha256":"e"*64,"derivation_code_sha256":"d"*64,"oos_cutoff_utc":"2026-08-01T00:00:00Z"},"frozen":{"frozen_by_commit":"a"*40}}}}}))

class PitcherLiveTests(unittest.TestCase):
    def test_probable_pitcher_identity_is_bound(self):
        c=assemble_pitcher_bb_candidate(game=game(),feature_row=feature(),quote=quote()); self.assertEqual(c["model_input"]["entity_id"],"11"); self.assertEqual(c["model_input"]["market"],"PITCHER_BB"); self.assertEqual(len(c["model_input"]["build_hash"]),64)
    def test_rng_identity_is_invariant_to_quote_side_and_line(self):
        over=assemble_pitcher_bb_candidate(game=game(),feature_row=feature(),quote=quote(side="OVER",line=1.5))
        under=assemble_pitcher_bb_candidate(game=game(),feature_row=feature(),quote=quote(side="UNDER",line=2.5))
        self.assertEqual(over["model_input"]["build_hash"],under["model_input"]["build_hash"])
    def test_non_probable_pitcher_fails_closed(self):
        with self.assertRaises(LiveSlateError): assemble_pitcher_bb_candidate(game=game(),feature_row=feature(99),quote=quote(99))
    def test_wrong_team_fails_closed(self):
        with self.assertRaises(LiveSlateError): assemble_pitcher_bb_candidate(game=game(),feature_row=feature(team=2),quote=quote())
    def test_checked_registry_remains_blocked(self):
        out=run_pitcher_bb_card(games=[game()],feature_rows=[feature()],quotes=[quote()],ingestion_now=NOW,finalization_now=NOW); self.assertEqual(out[0].bet_status,"BLOCKED")
    def test_direct_quote_missing_taxonomy_blocks(self):
        q=quote(); del q["raw_market_name"]; out=run_pitcher_bb_card(games=[game()],feature_rows=[feature()],quotes=[q],ingestion_now=NOW,finalization_now=NOW); self.assertEqual(out[0].bet_status,"BLOCKED"); self.assertIn("QUOTE_IDENTITY_INCOMPLETE",out[0].reason)
    def test_temp_deployed_registry_cannot_make_legacy_compat_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"deployments.json"; f=Path(td)/"floors.json"; deployed_registry(p); floor_registry(f); out=run_pitcher_bb_card(games=[game()],feature_rows=[feature()],quotes=pair(),ingestion_now=NOW,finalization_now=NOW,registry_path=str(p),edge_floor_config_path=str(f))
        self.assertEqual(out[0].bet_status,"BLOCKED"); self.assertIsNone(out[0].model_p); self.assertIn("LEGACY_COMPAT_PATH_NOT_CANDIDATE",out[0].reason)

if __name__=="__main__": unittest.main()
