from datetime import datetime, timezone
import unittest
from sportsedge.orchestrator import run_candidate

class OrchestratorBindingBoundaryTests(unittest.TestCase):
    def test_missing_event_identity_blocks_before_engine(self):
        called={"engine":False}
        def engine(_):
            called["engine"]=True
            return {"model_p":.55}
        q={"game_id":"1","market":"TOTALS","entity_id":"1","side":"OVER","period":"FG","book_key":"dk","raw_market_name":"total","retrieved_at":datetime.now(timezone.utc),"american_odds":-110,"line":8.5,"is_alternate":False}
        r=run_candidate(model_input={"game_id":"1","market":"TOTALS","entity_id":"1","side":"OVER","period":"FG","probability_threshold":8.5},quote=q,paired_quote=None,deployment={"market":"TOTALS","eligible":False},engine_fn=engine,ingestion_now=datetime.now(timezone.utc),finalization_now=datetime.now(timezone.utc))
        self.assertEqual(r.bet_status,"BLOCKED")
        self.assertIn("BINDING_EVENT_INSTANCE_MISSING",r.reason)
        self.assertFalse(called["engine"])

if __name__=="__main__":unittest.main()
