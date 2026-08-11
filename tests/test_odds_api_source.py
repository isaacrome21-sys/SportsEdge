import unittest
from datetime import datetime, timezone

from sportsedge.mlb_source import GameSnapshot
from sportsedge.odds_api_source import (
    OddsApiSourceError,
    bind_provider_event,
    build_participant_index,
    normalize_name,
    parse_event_odds,
)

UTC = timezone.utc


def game(pk=777, start="2026-08-11T23:10:00Z", number=1, double_header="N"):
    return GameSnapshot(
        game_pk=pk,
        game_date=start,
        status="Preview",
        away_id=1,
        away_name="Chicago Cubs",
        home_id=2,
        home_name="New York Yankees",
        away_probable_pitcher_id=11,
        away_probable_pitcher_name="José Acevedo",
        home_probable_pitcher_id=22,
        home_probable_pitcher_name="John Smith",
        retrieved_at="2026-08-11T15:00:00+00:00",
        game_number=number,
        double_header=double_header,
        venue_id=10,
        official_date="2026-08-11",
        detailed_status="Scheduled",
    )


def event(start="2026-08-11T23:10:00Z"):
    return {
        "id": "provider-event",
        "commence_time": start,
        "away_team": "Chicago Cubs",
        "home_team": "New York Yankees",
    }


class OddsApiSourceTests(unittest.TestCase):
    def test_name_normalization_removes_accents_and_punctuation(self):
        self.assertEqual(normalize_name("José Acevedo Jr."), "joseacevedojr")

    def test_provider_event_binds_to_exact_schedule_game(self):
        self.assertEqual(bind_provider_event(event(), [game()]).game_pk, 777)

    def test_doubleheader_time_ambiguity_fails_closed(self):
        games = [
            game(777, "2026-08-11T23:00:00Z", 1, "Y"),
            game(778, "2026-08-12T00:00:00Z", 2, "Y"),
        ]
        with self.assertRaises(OddsApiSourceError) as cm:
            bind_provider_event(event("2026-08-11T23:30:00Z"), games)
        self.assertEqual(str(cm.exception), "ODDS_EVENT_GAME_AMBIGUOUS")

    def test_participant_index_is_game_scoped_and_ambiguous_names_removed(self):
        idx = build_participant_index(
            schedule=[game()],
            confirmed_names_by_game={777: [(100, "Ian Happ"), (101, "Same Name"), (102, "Same Name")]},
        )
        self.assertEqual(idx[777]["ianhapp"], 100)
        self.assertNotIn("samename", idx[777])
        self.assertEqual(idx[777]["joseacevedo"], 11)

    def test_regular_and_alternate_props_become_canonical_quote_rows(self):
        idx = build_participant_index(schedule=[game()], confirmed_names_by_game={777: [(100, "Ian Happ")]})
        payload = {
            "bookmakers": [{
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-08-11T15:39:00Z",
                "markets": [
                    {"key": "batter_hits", "outcomes": [
                        {"name": "Over", "description": "Ian Happ", "point": 0.5, "price": -115, "sid": "a"},
                        {"name": "Under", "description": "Ian Happ", "point": 0.5, "price": -105, "sid": "b"},
                    ]},
                    {"key": "batter_total_bases_alternate", "outcomes": [
                        {"name": "Over", "description": "Ian Happ", "point": 1.5, "price": 130},
                    ]},
                    {"key": "pitcher_walks", "outcomes": [
                        {"name": "Over", "description": "Jose Acevedo", "point": 1.5, "price": -110},
                    ]},
                ],
            }],
        }
        snap = parse_event_odds(payload, game=game(), participant_index=idx)
        self.assertEqual(len(snap.failures), 0)
        self.assertEqual(len(snap.quotes), 4)
        hit = snap.quotes[0]
        self.assertEqual((hit["game_id"], hit["market"], hit["entity_id"], hit["period"]), ("777", "HITS", "100", "FG"))
        self.assertFalse(hit["is_alternate"])
        self.assertTrue(any(q["market"] == "TOTAL_BASES" and q["is_alternate"] for q in snap.quotes))
        self.assertTrue(any(q["market"] == "PITCHER_BB" and q["entity_id"] == "11" for q in snap.quotes))

    def test_unresolved_player_is_failure_not_guessed(self):
        payload = {"bookmakers": [{"key": "draftkings", "last_update": "2026-08-11T15:39:00Z", "markets": [
            {"key": "batter_hits", "outcomes": [{"name": "Over", "description": "Unknown Player", "point": 0.5, "price": -110}]}
        ]}]}
        snap = parse_event_odds(payload, game=game(), participant_index={777: {}})
        self.assertEqual(snap.quotes, ())
        self.assertEqual(len(snap.failures), 1)
        self.assertIn("ODDS_PLAYER_ID_UNRESOLVED", snap.failures[0]["reason"])


if __name__ == "__main__":
    unittest.main()
