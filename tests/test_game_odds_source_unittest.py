import unittest

from sportsedge.game_odds_source import parse_game_event_odds
from sportsedge.mlb_source import GameSnapshot


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
        )

    def test_parses_featured_markets(self):
        payload={"bookmakers":[{"key":"draftkings","title":"DraftKings","last_update":"2026-08-11T23:35:00Z","markets":[
            {"key":"h2h","last_update":"2026-08-11T23:35:00Z","outcomes":[{"name":"Texas Rangers","price":120},{"name":"Los Angeles Angels","price":-140}]},
            {"key":"spreads","last_update":"2026-08-11T23:35:00Z","outcomes":[{"name":"Texas Rangers","point":1.5,"price":-170},{"name":"Los Angeles Angels","point":-1.5,"price":145}]},
            {"key":"totals","last_update":"2026-08-11T23:35:00Z","outcomes":[{"name":"Over","point":9.0,"price":-105},{"name":"Under","point":9.0,"price":-115}]}
        ]}]}
        snap=parse_game_event_odds(payload,game=self._game())
        self.assertFalse(snap.failures)
        self.assertEqual(len(snap.quotes),6)
        self.assertEqual({q["market"] for q in snap.quotes},{"MONEYLINE","RUN_LINE","TOTALS"})

    def test_wrong_team_fails_closed(self):
        payload={"bookmakers":[{"key":"draftkings","last_update":"2026-08-11T23:35:00Z","markets":[{"key":"h2h","outcomes":[{"name":"Other Team","price":120}]}]}]}
        snap=parse_game_event_odds(payload,game=self._game())
        self.assertTrue(any("ODDS_GAME_TEAM_UNRESOLVED" in x["reason"] for x in snap.failures))
        self.assertFalse(snap.quotes)


if __name__ == "__main__":
    unittest.main()
