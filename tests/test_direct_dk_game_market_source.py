import json
import unittest
from datetime import datetime, timezone
from sportsedge.draftkings_game_market_source import RawDraftKingsBoard, normalize_board, board_url, DraftKingsGameMarketError

UTC=timezone.utc

def fixture():
    return {
      "events":[{"id":"e1","name":"Away Team @ Home Team","startEventDate":"2026-09-15T01:00:00Z"}],
      "markets":[
        {"id":"m1","eventId":"e1","name":"Moneyline"},
        {"id":"m2","eventId":"e1","name":"Spread"},
        {"id":"m3","eventId":"e1","name":"Total"},
      ],
      "selections":[
        {"marketId":"m1","label":"Away Team","displayOdds":{"american":"+120"}},
        {"marketId":"m1","label":"Home Team","displayOdds":{"american":"-140"}},
        {"marketId":"m2","label":"Away Team +3.5","points":3.5,"displayOdds":{"american":"-110"}},
        {"marketId":"m2","label":"Home Team -3.5","points":-3.5,"displayOdds":{"american":"-110"}},
        {"marketId":"m3","label":"Over 47.5","points":47.5,"displayOdds":{"american":"-105"}},
        {"marketId":"m3","label":"Under 47.5","points":47.5,"displayOdds":{"american":"-115"}},
      ]}

class DirectDKSourceTests(unittest.TestCase):
    def board(self,payload=None):
        payload=payload or fixture(); raw=json.dumps(payload).encode()
        return RawDraftKingsBoard("americanfootball_nfl","https://example.test",raw,datetime(2026,9,14,tzinfo=UTC),payload)

    def test_exact_three_two_sided_markets(self):
        rows=normalize_board(self.board())
        self.assertEqual(len(rows),6)
        self.assertEqual({r['market'] for r in rows},{'h2h','spreads','totals'})
        for market in ('h2h','spreads','totals'):
            self.assertEqual(len([r for r in rows if r['market']==market]),2)
        self.assertTrue(all(r['sportsbook']=='draftkings' for r in rows))

    def test_one_sided_market_is_not_imputed(self):
        p=fixture(); p['selections']=[s for s in p['selections'] if not (s['marketId']=='m3' and s['label'].startswith('Under'))]
        rows=normalize_board(self.board(p))
        self.assertFalse(any(r['market']=='totals' for r in rows))

    def test_ambiguous_event_name_fails_that_event_closed(self):
        p=fixture(); p['events'][0]['name']='Away Team vs Home Team'
        self.assertEqual(normalize_board(self.board(p)),[])

    def test_supported_urls_use_live_game_lines_category_and_unknown_sport(self):
        self.assertIn('/88808/categories/492',board_url('americanfootball_nfl'))
        self.assertIn('/87637/categories/492',board_url('americanfootball_ncaaf'))
        self.assertIn('/84240/categories/492',board_url('baseball_mlb'))
        with self.assertRaisesRegex(DraftKingsGameMarketError,'UNSUPPORTED'):
            board_url('unknown')

    def test_metadata_only_board_never_synthesizes_quotes(self):
        # Regression shape from the obsolete /categories/493 route: HTTP/JSON was
        # valid and advertised Game Lines=492, but carried no event-market rows.
        payload={
            'events':[],
            'markets':[],
            'selections':[],
            'categories':[{'id':492,'name':'Game Lines'}],
        }
        self.assertEqual(normalize_board(self.board(payload)),[])

if __name__=='__main__': unittest.main()