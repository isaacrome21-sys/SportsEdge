import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sportsedge.generic_card_pipeline import _feature_index, run_generic_card
from sportsedge.live_slate import make_live_game
from sportsedge.mlb_source import GameSnapshot
from sportsedge.orchestrator import run_candidate as real_run_candidate

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)


def lineup_rows(start): return [{"player_id": start+i, "slot": i+1, "sequence": 0} for i in range(9)]

def frozen_game():
    snap=GameSnapshot(game_pk=777,game_date="2026-08-10T23:00:00Z",status="Preview",away_id=1,away_name="Away",home_id=2,home_name="Home",away_probable_pitcher_id=11,away_probable_pitcher_name="Away SP",home_probable_pitcher_id=22,home_probable_pitcher_name="Home SP",retrieved_at="2026-08-10T19:59:00+00:00")
    return make_live_game(snap,lineup_rows(100),lineup_rows(200))

def frozen_feature(): return {"game_pk":777,"entity_id":"777","market":"TOTALS","away_mean_runs":4.1,"home_mean_runs":4.6,"source_subset_hash":"fixture-v1"}

def frozen_quote(side,odds): return {"game_id":"777","period":"FG","market":"TOTALS","entity_id":"777","line":8.5,"side":side,"american_odds":odds,"book_key":"draftkings","is_alternate":False,"raw_market_name":"Game Total","retrieved_at":"2026-08-10T19:59:00Z","ttl_seconds":300}

def write_registry(path): path.write_text(json.dumps({"schema_version":1,"markets":{"TOTALS":{"market":"TOTALS","eligible":True,"stage":"DEPLOYED","reason":"frozen-fixture-ci"}}}))

def write_floors(path):
    devig={"policy_id":"EDGE_FLOOR_DEVIG_V1","status":"FROZEN_PRE_DERIVATION","longshot_trigger_american_odds":400,"longshot_trigger_rule":"EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400","sensitivity_methods":["MULTIPLICATIVE_V1","POWER_V1","SHIN_V1"],"sensitivity_limit_absolute_probability_points":0.01,"stable_candidate_estimator":"MULTIPLICATIVE_V1","longshot_candidate_estimator":"POWER_V1","haircut_probability_points":0.0,"aggregation_rule":"ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS","sensitivity_failure":"BLOCK"}
    path.write_text(json.dumps({"truth_gate":{"schema_version":2,"production":{"fail_closed":True,"allow_cli_floor_override":False,"require_frozen_floor_for_eligible_market":True},"devig_policy":devig,"edge_floors":{"TOTALS":{"status":"FROZEN","value_probability_points":0.01,"method_version":"fixture-ci-v1","evidence":{"evidence_sha256":"fixture-evidence-sha256","derivation_code_sha256":"fixture-derivation-sha256","oos_cutoff_utc":"2026-08-09T00:00:00Z"},"frozen":{"frozen_by_commit":"fixture-ci"}}}}}))


class MLBFixtureFullPipelineTests(unittest.TestCase):
    def test_identical_feature_reuse_is_idempotent_but_conflict_still_fails_closed(self):
        row=frozen_feature(); indexed=_feature_index([row,dict(row)])
        self.assertEqual(list(indexed),[("777","777","TOTALS")])
        conflict=dict(row); conflict["away_mean_runs"]=9.9
        with self.assertRaisesRegex(ValueError,"conflicting generic feature identity"): _feature_index([row,conflict])

    def test_frozen_totals_fixture_asserts_devig_values_end_to_end(self):
        quotes=[frozen_quote("OVER",-113),frozen_quote("UNDER",104)]
        captured=[]
        def capture_candidate(**kwargs):
            result=real_run_candidate(**kwargs); captured.append(result); return result
        with tempfile.TemporaryDirectory() as td:
            registry=Path(td)/"deployments.json"; floors=Path(td)/"floors.json"; write_registry(registry); write_floors(floors)
            with patch("sportsedge.generic_card_pipeline.run_candidate",side_effect=capture_candidate):
                results=run_generic_card(games=[frozen_game()],feature_rows=[frozen_feature(),frozen_feature()],quotes=quotes,ingestion_now=NOW,finalization_now=NOW,registry_path=str(registry),edge_floor_config_path=str(floors),kelly_multiplier=0.25)
        self.assertEqual(len(results),2)
        by={r.side:r for r in results}
        q_over=113/213; q_under=100/204; fair_over=q_over/(q_over+q_under); fair_under=q_under/(q_over+q_under)
        self.assertAlmostEqual(by["OVER"].implied_probability,fair_over,places=12)
        self.assertAlmostEqual(by["UNDER"].implied_probability,fair_under,places=12)
        self.assertAlmostEqual(by["OVER"].edge,by["OVER"].model_p-fair_over,places=12)
        self.assertAlmostEqual(by["UNDER"].edge,by["UNDER"].model_p-fair_under,places=12)
        self.assertNotAlmostEqual(by["OVER"].implied_probability,q_over,places=6)
        self.assertEqual(len(captured),2)
        self.assertTrue(all(r.decision is not None for r in captured),[r.reason for r in captured])
        self.assertTrue(all(r.bet_status in {"PASS","OFFICIAL_BET"} for r in captured))

    def test_missing_opposite_side_retains_model_candidate_but_cannot_devig(self):
        with tempfile.TemporaryDirectory() as td:
            registry=Path(td)/"deployments.json"; floors=Path(td)/"floors.json"; write_registry(registry); write_floors(floors)
            out=run_generic_card(games=[frozen_game()],feature_rows=[frozen_feature()],quotes=[frozen_quote("OVER",-113)],ingestion_now=NOW,finalization_now=NOW,registry_path=str(registry),edge_floor_config_path=str(floors))
        self.assertEqual(out[0].bet_status,"MODEL_CANDIDATE")
        self.assertIsNotNone(out[0].model_p)
        self.assertEqual(out[0].market_no_vig_p_status,"UNAVAILABLE_ONE_SIDED")
        self.assertIsNotNone(out[0].ev_per_dollar)
        self.assertIn("PAIRED_PRICE_REQUIRED_FOR_DEVIG",out[0].reason)


if __name__ == "__main__": unittest.main()
