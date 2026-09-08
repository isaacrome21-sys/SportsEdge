from datetime import datetime, timezone
import unittest
from sportsedge.quote_bridge import validate_canonical_quote

class QuoteIdentityTests(unittest.TestCase):
    def base(self):return {"game_id":"1","market":"TOTALS","entity_id":"1","side":"OVER","period":"FG","book_key":"dk","raw_market_name":"Total","retrieved_at":datetime.now(timezone.utc),"american_odds":-110,"line":8.5,"is_alternate":False}
    def test_preserves_origin_identity(self):
        q=self.base();q.update(event_id="evt",game_number=2,team_id="10",player_id="20")
        out=validate_canonical_quote(q)
        self.assertEqual(out["event_id"],"evt");self.assertEqual(out["game_number"],2);self.assertEqual(out["team_id"],"10");self.assertEqual(out["player_id"],"20")
    def test_does_not_synthesize_origin_identity(self):
        out=validate_canonical_quote(self.base())
        for key in ("event_id","game_number","team_id","player_id"):self.assertNotIn(key,out)

if __name__=="__main__":unittest.main()
