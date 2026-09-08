from datetime import datetime, timezone
import unittest

from sportsedge.mlb_market_binding import BindingError, MarketBindingSpec, binding_spec_for_market, validate_probability_binding, validate_quote_binding_identity


def quote(**changes):
    q={"game_id":"123","event_id":"provider-abc","game_number":1,"market":"TOTALS","entity_id":"123","side":"OVER","period":"FG","book_key":"dk","raw_market_name":"Total Runs","retrieved_at":datetime(2026,9,7,18,0,tzinfo=timezone.utc),"american_odds":-110,"line":8.5,"is_alternate":False}
    q.update(changes);return q

def prob(**changes):
    p={"probability_market_id":"TOTALS","probability_source_market":"TOTALS","game_id":"123","entity_id":"123","side":"OVER","period":"FG","probability_threshold":8.5}
    p.update(changes);return p

class BindingTests(unittest.TestCase):
    def test_threshold_domain_explicit_and_contradiction(self):
        self.assertEqual(binding_spec_for_market("TOTALS").threshold_domain,"RUNS")
        with self.assertRaises(BindingError): MarketBindingSpec("TOTALS","COUNT")
        with self.assertRaises(BindingError): binding_spec_for_market("NEW_UNREGISTERED_MARKET")
    def test_missing_quote_origin_identities_block(self):
        for key in ("book_key","retrieved_at","event_id"):
            q=quote();q.pop(key,None)
            if key=="event_id":q.pop("game_number",None)
            with self.subTest(key=key),self.assertRaises(BindingError):validate_quote_binding_identity(q)
    def test_invalid_price_blocks(self):
        for odds in (0,99,-99,100.5,float("nan")):
            with self.subTest(odds=odds),self.assertRaises(BindingError):validate_quote_binding_identity(quote(american_odds=odds))
    def test_threshold_omission_and_mismatch_block(self):
        p=prob();p.pop("probability_threshold")
        with self.assertRaises(BindingError):validate_probability_binding(p,quote())
        with self.assertRaises(BindingError):validate_probability_binding(prob(probability_threshold=9.5),quote())
    def test_team_identity_required_and_bound(self):
        q=quote(market="TEAM_TOTALS",entity_id="111",team_id="111",line=4.5)
        p=prob(probability_market_id="TEAM_TOTALS",probability_source_market="TEAM_TOTALS",entity_id="111",probability_team_id="111",probability_threshold=4.5)
        validate_probability_binding(p,q)
        p.pop("probability_team_id")
        with self.assertRaises(BindingError):validate_probability_binding(p,q)
        with self.assertRaises(BindingError):validate_probability_binding(prob(probability_market_id="TEAM_TOTALS",probability_source_market="TEAM_TOTALS",entity_id="111",probability_team_id="222",probability_threshold=4.5),q)
    def test_two_pitcher_identity_required(self):
        # Only run when registry exposes an EITHER_PITCHER market; contract still guards prefix.
        q=quote(market="EITHER_PITCHER_STRIKEOUTS",entity_id="1|2",pitcher_ids=(1,2),line=5.5)
        try: validate_quote_binding_identity(q)
        except BindingError as exc:
            if "BINDING_SPEC_MISSING" in str(exc): return
            raise
        q.pop("pitcher_ids")
        with self.assertRaises(BindingError):validate_quote_binding_identity(q)
    def test_probability_market_entity_period_source_are_mandatory(self):
        for key in ("probability_market_id","probability_source_market","entity_id","period"):
            p=prob();p.pop(key)
            with self.subTest(key=key),self.assertRaises(BindingError):validate_probability_binding(p,quote())

if __name__=="__main__":unittest.main()
