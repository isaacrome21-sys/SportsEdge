import unittest

from sportsedge.mlb_source import GameSnapshot
from sportsedge.odds_api_source import MARKETS, build_participant_index, parse_event_odds


def game():
    return GameSnapshot(
        game_pk=777,
        game_date="2026-08-16T20:05:00Z",
        status="Preview",
        away_id=1,
        away_name="Texas Rangers",
        home_id=2,
        home_name="Athletics",
        away_probable_pitcher_id=11,
        away_probable_pitcher_name="Cody Bradford",
        home_probable_pitcher_id=22,
        home_probable_pitcher_name="Jacob Lopez",
        retrieved_at="2026-08-16T17:00:00+00:00",
        game_number=1,
        double_header="N",
        venue_id=10,
        official_date="2026-08-16",
        detailed_status="Scheduled",
    )


class OddsApiMarketCatalogTests(unittest.TestCase):
    def test_required_mlb_prop_markets_are_mapped(self):
        expected = {
            "batter_home_runs": "HOME_RUNS",
            "batter_hits": "HITS",
            "batter_total_bases": "TOTAL_BASES",
            "batter_rbis": "RBI",
            "batter_runs_scored": "RUNS",
            "batter_hits_runs_rbis": "HITS_RUNS_RBIS",
            "batter_singles": "SINGLES",
            "batter_doubles": "DOUBLES",
            "batter_triples": "TRIPLES",
            "batter_walks": "BATTER_BB",
            "batter_strikeouts": "BATTER_K",
            "batter_stolen_bases": "STOLEN_BASES",
            "pitcher_strikeouts": "PITCHER_K",
            "pitcher_hits_allowed": "PITCHER_HITS_ALLOWED",
            "pitcher_walks": "PITCHER_BB",
            "pitcher_earned_runs": "PITCHER_ER",
            "pitcher_outs": "PITCHER_OUTS",
        }
        for provider_key, canonical in expected.items():
            self.assertIn(provider_key, MARKETS)
            self.assertEqual(MARKETS[provider_key][0], canonical)

    def test_expanded_markets_parse_to_canonical_quotes(self):
        idx = build_participant_index(
            schedule=[game()],
            confirmed_names_by_game={777: [(100, "Corey Seager")]},
        )
        payload = {
            "bookmakers": [{
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-08-16T17:30:00Z",
                "markets": [
                    {"key": "batter_home_runs", "outcomes": [
                        {"name": "Over", "description": "Corey Seager", "point": 0.5, "price": 267},
                    ]},
                    {"key": "batter_rbis_alternate", "outcomes": [
                        {"name": "Over", "description": "Corey Seager", "point": 0.5, "price": 119},
                    ]},
                    {"key": "pitcher_strikeouts", "outcomes": [
                        {"name": "Over", "description": "Jacob Lopez", "point": 5.5, "price": -110},
                    ]},
                    {"key": "pitcher_outs", "outcomes": [
                        {"name": "Under", "description": "Jacob Lopez", "point": 15.5, "price": -102},
                    ]},
                    {"key": "pitcher_earned_runs", "outcomes": [
                        {"name": "Over", "description": "Jacob Lopez", "point": 2.5, "price": -105},
                    ]},
                ],
            }],
        }
        snap = parse_event_odds(payload, game=game(), participant_index=idx)
        self.assertEqual(snap.failures, ())
        by_market = {row["market"]: row for row in snap.quotes}
        self.assertEqual(set(by_market), {"HOME_RUNS", "RBI", "PITCHER_K", "PITCHER_OUTS", "PITCHER_ER"})
        self.assertTrue(by_market["RBI"]["is_alternate"])
        self.assertEqual(by_market["PITCHER_K"]["entity_id"], "22")


if __name__ == "__main__":
    unittest.main()
