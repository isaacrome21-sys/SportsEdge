from datetime import datetime, timezone
import unittest
from sportsedge.mlb_market_binding import validate_quote_binding_identity, BindingError

class PairIdentityPrereqTests(unittest.TestCase):
    def q(self,**kw):
        x={"game_id":"1","event_id":"evt","game_number":1,"market":"TEAM_TOTALS","entity_id":"10","team_id":"10","side":"OVER","period":"FG","book_key":"dk","raw_market_name":"TT","retrieved_at":datetime.now(timezone.utc),"american_odds":-110,"line":4.5,"is_alternate":False};x.update(kw);return x
    def test_team_total_requires_team(self):
        x=self.q();x.pop("team_id")
        with self.assertRaises(BindingError):validate_quote_binding_identity(x)
    def test_event_instance_required(self):
        x=self.q();x.pop("event_id");x.pop("game_number")
        with self.assertRaises(BindingError):validate_quote_binding_identity(x)

if __name__=="__main__":unittest.main()
