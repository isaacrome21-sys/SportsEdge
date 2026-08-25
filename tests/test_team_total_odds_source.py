import unittest

from sportsedge.mlb_source import GameSnapshot
from sportsedge.quote_bridge import validate_canonical_quote
from sportsedge.team_total_odds_source import parse_team_total_event_odds


class TeamTotalOddsSourceTests(unittest.TestCase):
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

    def _payload(self, outcomes):
        return {
            "id": "provider-event",
            "bookmakers": [{
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-08-11T23:20:00Z",
                "markets": [{"key": "team_totals", "outcomes": outcomes}],
            }],
        }

    def test_maps_both_teams_and_both_sides_with_exact_team_identity(self):
        snap = parse_team_total_event_odds(
            self._payload([
                {"name": "Over", "description": "Texas Rangers", "point": 4.5, "price": -115, "sid": "a1"},
                {"name": "Under", "description": "Texas Rangers", "point": 4.5, "price": -105, "sid": "a2"},
                {"name": "Over", "description": "Los Angeles Angels", "point": 3.5, "price": 100, "sid": "h1"},
                {"name": "Under", "description": "Los Angeles Angels", "point": 3.5, "price": -120, "sid": "h2"},
            ]),
            game=self._game(),
            provider_event={"id": "provider-event"},
        )
        self.assertFalse(snap.failures)
        self.assertEqual(len(snap.quotes), 4)
        self.assertEqual(
            {(q["entity_id"], q["team_side"], q["side"], float(q["line"])) for q in snap.quotes},
            {
                ("10", "AWAY", "OVER", 4.5), ("10", "AWAY", "UNDER", 4.5),
                ("20", "HOME", "OVER", 3.5), ("20", "HOME", "UNDER", 3.5),
            },
        )
        self.assertEqual({q["market"] for q in snap.quotes}, {"TEAM_TOTALS"})
        self.assertEqual({q["book_key"] for q in snap.quotes}, {"draftkings"})
        self.assertEqual({q["sportsbook"] for q in snap.quotes}, {"DraftKings"})
        self.assertEqual({q["provider_event_id"] for q in snap.quotes}, {"provider-event"})
        self.assertEqual({q["offer_id"] for q in snap.quotes}, {"a1", "a2", "h1", "h2"})
        for quote in snap.quotes:
            validate_canonical_quote(quote)

    def test_unknown_team_fails_closed_instead_of_guessing_side(self):
        snap = parse_team_total_event_odds(
            self._payload([
                {"name": "Over", "description": "Unknown Club", "point": 4.5, "price": -110},
            ]),
            game=self._game(),
        )
        self.assertFalse(snap.quotes)
        self.assertEqual(len(snap.failures), 1)
        self.assertIn("ODDS_GAME_TEAM_UNRESOLVED", snap.failures[0]["reason"])

    def test_non_over_under_side_fails_closed(self):
        snap = parse_team_total_event_odds(
            self._payload([
                {"name": "Yes", "description": "Texas Rangers", "point": 4.5, "price": -110},
            ]),
            game=self._game(),
        )
        self.assertFalse(snap.quotes)
        self.assertIn("ODDS_SIDE_UNSUPPORTED", snap.failures[0]["reason"])


if __name__ == "__main__":
    unittest.main()
