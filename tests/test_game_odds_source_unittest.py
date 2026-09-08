import unittest

from sportsedge.game_odds_source import parse_game_event_odds
from sportsedge.mlb_source import GameSnapshot
from sportsedge.quote_bridge import validate_canonical_quote


class GameOddsSourceTests(unittest.TestCase):
    def _game(self):
        return GameSnapshot(
            game_pk=123,
            game_date="2026-08-11T23:40:00Z",
            status="Preview",
            away_id=10,
            away_name="Texas Rangers",
            home_id=20,
            home_name="Los Angeles Angels",
            away_probable_pitcher_id=101,
            away_probable_pitcher_name="Away SP",
            home_probable_pitcher_id=202,
            home_probable_pitcher_name="Home SP",
            retrieved_at="2026-08-11T23:30:00Z",
            official_date="2026-08-11",
            game_number=1,
        )

    def test_parses_featured_markets_and_exports_binding_identity(self):
        payload={"id":"provider-event","bookmakers":[{"key":"draftkings","title":"DraftKings","last_update":"2026-08-11T23:35:00Z","markets":[
            {"key":"h2h","last_update":"2026-08-11T23:35:00Z","outcomes":[{"name":"Texas Rangers","price":120,"sid":"ml-a"},{"name":"Los Angeles Angels","price":-140,"sid":"ml-h"}]},
            {"key":"spreads","last_update":"2026-08-11T23:35:00Z","outcomes":[{"name":"Texas Rangers","point":1.5,"price":-170},{"name":"Los Angeles Angels","point":-1.5,"price":145}]},
            {"key":"totals","last_update":"2026-08-11T23:35:00Z","outcomes":[{"name":"Over","point":9.0,"price":-105},{"name":"Under","point":9.0,"price":-115}]}
        ]}]}
        snap=parse_game_event_odds(payload,game=self._game())
        self.assertFalse(snap.failures)
        self.assertEqual(len(snap.quotes),6)
        self.assertEqual({q["market"] for q in snap.quotes},{"MONEYLINE","RUN_LINE","TOTALS"})
        for raw in snap.quotes:
            self.assertEqual(raw["event_id"], "123")
            self.assertEqual(raw["game_number"], 1)
            self.assertEqual(raw["event_away_team_id"], "10")
            self.assertEqual(raw["event_home_team_id"], "20")
            self.assertEqual(raw["provider_event_id"], "provider-event")
            normalized = validate_canonical_quote(raw)
            self.assertEqual(normalized["event_id"], "123")
            self.assertEqual(normalized["game_number"], 1)
            self.assertEqual(normalized["provider_event_id"], "provider-event")

    def test_missing_game_number_is_not_manufactured(self):
        game = self._game()
        game = GameSnapshot(**{**game.__dict__, "game_number": None})
        payload={"id":"provider-event","bookmakers":[{"key":"draftkings","last_update":"2026-08-11T23:35:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Texas Rangers","price":120}]}]}]}
        snap=parse_game_event_odds(payload,game=game)
        self.assertEqual(len(snap.quotes), 1)
        self.assertNotIn("game_number", snap.quotes[0])

    def test_wrong_team_fails_closed(self):
        payload={"bookmakers":[{"key":"draftkings","last_update":"2026-08-11T23:35:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Other Team","price":120}]}]}]}
        snap=parse_game_event_odds(payload,game=self._game())
        self.assertTrue(any("ODDS_GAME_TEAM_UNRESOLVED" in x["reason"] for x in snap.failures))
        self.assertFalse(snap.quotes)


if __name__ == "__main__":
    unittest.main()
