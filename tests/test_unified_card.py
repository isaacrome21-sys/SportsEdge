import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from sportsedge.card_pipeline import run_hitter_card
from sportsedge.hits_engine import FEATURE_CONTRACT_VERSION as HITS_V
from sportsedge.live_slate import make_live_game
from sportsedge.mlb_source import GameSnapshot
from sportsedge.pitcher_card_pipeline import run_pitcher_bb_card
from sportsedge.total_bases_engine import FEATURE_CONTRACT_VERSION as TB_V
from sportsedge.unified_card import run_unified_card

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)


def rows(start):
    return [{"player_id": start+i, "slot": i+1, "sequence": 0} for i in range(9)]


def game():
    snap = GameSnapshot(game_pk=777, game_date="2026-08-10T23:00:00Z", status="Preview", away_id=1, away_name="Away", home_id=2, home_name="Home", away_probable_pitcher_id=11, away_probable_pitcher_name="Away SP", home_probable_pitcher_id=22, home_probable_pitcher_name="Home SP", retrieved_at="2026-08-10T19:59:00+00:00")
    return make_live_game(snap, rows(100), rows(200))


def features():
    return [
        {"game_pk":777,"player_id":100,"team_id":1,"market":"HITS","feature_version":HITS_V,"b_rate":.60,"p_rate":.60,"pa_pool":[4,5,4,5]},
        {"game_pk":777,"player_id":100,"team_id":1,"market":"TOTAL_BASES","feature_version":TB_V,"rates":{"s":.20,"d":.08,"t":.01,"hr":.08},"p_h":.35,"p_hr":.06,"park":1.2,"pa_pool":[4,5,4,5]},
        {"game_pk":777,"player_id":11,"team_id":1,"market":"PITCHER_BB","feature_version":"pitcher_bb_features_v1","own_bb":20,"own_bfp":220,"rolling_league_rate":.082,"pool":[22,24,25,27],"league_pool":[20,21,23,24,25,26,27,28]},
    ]


def quote(market, entity, line=.5):
    names={"HITS":"Player Hits","TOTAL_BASES":"Player Total Bases","PITCHER_BB":"Pitcher Walks"}
    return {"game_id":"777","period":"FG","market":market,"entity_id":str(entity),"line":line,"side":"OVER","book_key":"draftkings","is_alternate":False,"raw_market_name":names.get(market,"Unknown"),"american_odds":100,"retrieved_at":NOW,"ttl_seconds":300}


def all_quotes():
    return [quote("HITS",100,.5), quote("TOTAL_BASES",100,.5), quote("PITCHER_BB",11,1.5)]


def registry(path):
    path.write_text(json.dumps({"schema_version":1,"markets":{"HITS":{"eligible":True,"stage":"DEPLOYED","reason":"isolation-test"},"TOTAL_BASES":{"eligible":True,"stage":"DEPLOYED","reason":"isolation-test"},"PITCHER_BB":{"eligible":True,"stage":"DEPLOYED","reason":"isolation-test"}}}))


def key(x): return (x.market, x.entity_id, float(x.line), x.side)


class UnifiedCardIsolationTests(unittest.TestCase):
    def test_unified_matches_each_standalone_pipeline_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"deployments.json"; registry(p); uq=all_quotes()
            unified=run_unified_card(games=[game()],feature_rows=features(),quotes=uq,ingestion_now=NOW,finalization_now=NOW,registry_path=str(p))
            hitter=run_hitter_card(games=[game()],feature_rows=features(),quotes=uq[:2],ingestion_now=NOW,finalization_now=NOW,registry_path=str(p))
            pitcher=run_pitcher_bb_card(games=[game()],feature_rows=features(),quotes=uq[2:],ingestion_now=NOW,finalization_now=NOW,registry_path=str(p))
        standalone={key(x):x for x in [*hitter,*pitcher]}
        self.assertEqual(len(unified),3)
        for x in unified:
            y=standalone[key(x)]; self.assertEqual(x.model_p,y.model_p); self.assertEqual(x.bet_status,y.bet_status)

    def test_malformed_direct_quote_blocks_in_unified_and_standalone(self):
        q=quote("HITS",100); del q["book_key"]
        u=run_unified_card(games=[game()],feature_rows=features(),quotes=[q],ingestion_now=NOW,finalization_now=NOW)
        h=run_hitter_card(games=[game()],feature_rows=features(),quotes=[q],ingestion_now=NOW,finalization_now=NOW)
        self.assertEqual((u[0].bet_status,h[0].bet_status),("BLOCKED","BLOCKED"))
        self.assertIn("QUOTE_IDENTITY_INCOMPLETE",u[0].reason); self.assertIn("QUOTE_IDENTITY_INCOMPLETE",h[0].reason)

    def test_adding_bb_cannot_change_hits_or_tb_probabilities(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"deployments.json"; registry(p)
            base=run_unified_card(games=[game()],feature_rows=features(),quotes=all_quotes()[:2],ingestion_now=NOW,finalization_now=NOW,registry_path=str(p))
            mixed=run_unified_card(games=[game()],feature_rows=features(),quotes=all_quotes(),ingestion_now=NOW,finalization_now=NOW,registry_path=str(p))
        self.assertEqual({key(x):x.model_p for x in base},{key(x):x.model_p for x in mixed if x.market in {"HITS","TOTAL_BASES"}})

    def test_quote_order_does_not_change_candidate_probabilities(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"deployments.json"; registry(p); q=all_quotes()
            a=run_unified_card(games=[game()],feature_rows=features(),quotes=q,ingestion_now=NOW,finalization_now=NOW,registry_path=str(p))
            b=run_unified_card(games=[game()],feature_rows=features(),quotes=list(reversed(q)),ingestion_now=NOW,finalization_now=NOW,registry_path=str(p))
        self.assertEqual({key(x):x.model_p for x in a},{key(x):x.model_p for x in b})

    def test_checked_registry_keeps_all_three_blocked_independently(self):
        out=run_unified_card(games=[game()],feature_rows=features(),quotes=all_quotes(),ingestion_now=NOW,finalization_now=NOW)
        self.assertEqual([x.market for x in out],["HITS","TOTAL_BASES","PITCHER_BB"]); self.assertTrue(all(x.bet_status=="BLOCKED" for x in out))


if __name__ == "__main__": unittest.main()
