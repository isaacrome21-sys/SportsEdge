import unittest

from sportsedge.additional_mlb_odds_source import (
    CANONICAL_MARKETS,
    parse_additional_event_odds,
)
from sportsedge.mlb_source import GameSnapshot
from sportsedge.quote_bridge import validate_canonical_quote


class AdditionalMLBOddsSourceTests(unittest.TestCase):
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

    def _payload(self, markets):
        return {
            "id": "provider-event",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "last_update": "2026-08-11T23:20:00Z",
                    "markets": markets,
                }
            ],
        }

    def _participants(self):
        return {123: {"awaypitcher": 101, "homespp": 202, "battera": 301}}

    def _parse(self, markets, participant_index=None):
        return parse_additional_event_odds(
            self._payload(markets),
            game=self._game(),
            participant_index=participant_index or self._participants(),
            provider_event={"id": "provider-event"},
        )

    def test_canonical_market_set_is_exactly_seven(self):
        self.assertEqual(
            CANONICAL_MARKETS,
            {
                "F5_MONEYLINE",
                "F5_RUN_LINE",
                "F5_TOTALS",
                "NRFI",
                "YRFI",
                "FIRST_HOME_RUN",
                "PITCHER_RECORD_WIN",
            },
        )

    def test_maps_all_three_f5_market_families(self):
        snap = self._parse(
            [
                {
                    "key": "h2h_1st_5_innings",
                    "outcomes": [
                        {"name": "Texas Rangers", "price": 115},
                        {"name": "Los Angeles Angels", "price": -135},
                    ],
                },
                {
                    "key": "spreads_1st_5_innings",
                    "outcomes": [
                        {"name": "Texas Rangers", "point": 0.5, "price": -120},
                        {"name": "Los Angeles Angels", "point": -0.5, "price": 100},
                    ],
                },
                {
                    "key": "totals_1st_5_innings",
                    "outcomes": [
                        {"name": "Over", "point": 4.5, "price": -105},
                        {"name": "Under", "point": 4.5, "price": -115},
                    ],
                },
            ]
        )
        self.assertFalse(snap.failures)
        self.assertEqual(len(snap.quotes), 6)
        self.assertEqual(
            {q["market"] for q in snap.quotes},
            {"F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS"},
        )
        ml = [q for q in snap.quotes if q["market"] == "F5_MONEYLINE"]
        self.assertEqual({(q["entity_id"], q["side"]) for q in ml}, {("10", "AWAY"), ("20", "HOME")})
        totals = [q for q in snap.quotes if q["market"] == "F5_TOTALS"]
        self.assertTrue(all(q["entity_id"] == "123" and q["period"] == "F5" for q in totals))
        for quote in snap.quotes:
            validate_canonical_quote(quote)

    def test_nrfi_yrfi_are_derived_only_from_exact_first_inning_half_run_total(self):
        snap = self._parse(
            [
                {
                    "key": "totals_1st_1_innings",
                    "outcomes": [
                        {"name": "Over", "point": 0.5, "price": -125},
                        {"name": "Under", "point": 0.5, "price": 105},
                    ],
                }
            ]
        )
        self.assertFalse(snap.failures)
        self.assertEqual(len(snap.quotes), 4)
        by_market_side = {(q["market"], q["side"]): q for q in snap.quotes}
        self.assertEqual(by_market_side[("YRFI", "YES")]["american_odds"], -125)
        self.assertEqual(by_market_side[("NRFI", "NO")]["american_odds"], -125)
        self.assertEqual(by_market_side[("NRFI", "YES")]["american_odds"], 105)
        self.assertEqual(by_market_side[("YRFI", "NO")]["american_odds"], 105)
        self.assertTrue(all(q["provider_line"] == 0.5 for q in snap.quotes))
        self.assertTrue(all(q["period"] == "1ST" for q in snap.quotes))
        for quote in snap.quotes:
            validate_canonical_quote(quote)

    def test_non_half_run_first_inning_total_fails_closed_instead_of_becoming_nrfi_yrfi(self):
        snap = self._parse(
            [
                {
                    "key": "totals_1st_1_innings",
                    "outcomes": [
                        {"name": "Over", "point": 1.5, "price": -110},
                        {"name": "Under", "point": 1.5, "price": -110},
                    ],
                }
            ]
        )
        self.assertFalse(snap.quotes)
        self.assertEqual(len(snap.failures), 2)
        self.assertTrue(all("NRFI_YRFI_REQUIRES_FIRST_INNING_0_5_TOTAL" in f["reason"] for f in snap.failures))

    def test_binary_markets_resolve_exact_player_identity_and_validate_canonical_quote(self):
        participant_index = {123: {"battera": 301, "awaypitcher": 101}}
        snap = self._parse(
            [
                {
                    "key": "batter_first_home_run",
                    "outcomes": [
                        {"name": "Yes", "description": "Batter A", "price": 900, "sid": "hr-y"},
                        {"name": "No", "description": "Batter A", "price": -1800, "sid": "hr-n"},
                    ],
                },
                {
                    "key": "pitcher_record_a_win",
                    "outcomes": [
                        {"name": "Yes", "description": "Away Pitcher", "price": 160, "sid": "win-y"},
                        {"name": "No", "description": "Away Pitcher", "price": -190, "sid": "win-n"},
                    ],
                },
            ],
            participant_index=participant_index,
        )
        self.assertFalse(snap.failures)
        self.assertEqual(len(snap.quotes), 4)
        self.assertEqual(
            {(q["market"], q["entity_id"]) for q in snap.quotes},
            {("FIRST_HOME_RUN", "301"), ("PITCHER_RECORD_WIN", "101")},
        )
        for quote in snap.quotes:
            validate_canonical_quote(quote)

    def test_unresolved_binary_player_fails_closed(self):
        snap = self._parse(
            [
                {
                    "key": "batter_first_home_run",
                    "outcomes": [{"name": "Yes", "description": "Unknown Player", "price": 800}],
                }
            ],
            participant_index={123: {}},
        )
        self.assertFalse(snap.quotes)
        self.assertTrue(any("ODDS_PLAYER_ID_UNRESOLVED" in f["reason"] for f in snap.failures))

    def test_wrong_team_in_f5_market_fails_closed(self):
        snap = self._parse(
            [
                {
                    "key": "h2h_1st_5_innings",
                    "outcomes": [{"name": "Other Team", "price": 110}],
                }
            ]
        )
        self.assertFalse(snap.quotes)
        self.assertTrue(any("ODDS_GAME_TEAM_UNRESOLVED" in f["reason"] for f in snap.failures))


if __name__ == "__main__":
    unittest.main()
