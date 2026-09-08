from datetime import datetime, timezone
import unittest
from sportsedge.devig import DevigError,validate_pair

def q(side="OVER",**kw):
    x={"game_id":"1","event_id":"evt","game_number":1,"market":"TEAM_TOTALS","entity_id":"10","team_id":"10","side":side,"period":"FG","book_key":"dk","raw_market_name":"TT","retrieved_at":datetime.now(timezone.utc),"american_odds":-110,"line":4.5,"is_alternate":False};x.update(kw);return x
class DevigBindingTests(unittest.TestCase):
    def test_same_pair_passes(self):validate_pair(q(),q("UNDER"))
    def test_cross_event_blocks(self):
        with self.assertRaises(DevigError):validate_pair(q(),q("UNDER",event_id="other"))
    def test_cross_team_blocks(self):
        with self.assertRaises(DevigError):validate_pair(q(),q("UNDER",team_id="11"))
    def test_missing_timestamp_blocks(self):
        other=q("UNDER");other.pop("retrieved_at")
        with self.assertRaises(DevigError):validate_pair(q(),other)
if __name__=="__main__":unittest.main()
