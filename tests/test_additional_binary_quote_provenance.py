import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import unittest

from sportsedge.additional_mlb_odds_source import parse_additional_event_odds
from sportsedge.mlb_source import GameSnapshot
from sportsedge.odds_api_source import normalize_name

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "archive_mlb_additional_odds.py"
SPEC = importlib.util.spec_from_file_location("archive_mlb_additional_odds_provenance", SCRIPT)
archive_mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(archive_mod)


class AdditionalBinaryQuoteProvenanceTests(unittest.TestCase):
    def game(self):
        return GameSnapshot(
            game_pk=123,
            game_date="2026-08-11T23:40:00Z",
            status="Preview",
            away_id=10,
            away_name="Texas Rangers",
            home_id=20,
            home_name="Los Angeles Angels",
            away_probable_pitcher_id=101,
            away_probable_pitcher_name="Away Pitcher",
            home_probable_pitcher_id=202,
            home_probable_pitcher_name="Home Pitcher",
            retrieved_at="2026-08-11T23:10:00Z",
            official_date="2026-08-11",
        )

    def event(self):
        return {
            "id": "provider-event",
            "commence_time": "2026-08-11T23:40:00Z",
            "away_team": "Texas Rangers",
            "home_team": "Los Angeles Angels",
        }

    def test_binary_provider_name_survives_parser_and_archive_unchanged(self):
        game = self.game()
        event = self.event()
        participants = {123: {"battera": 301, "awaypitcher": 101}}
        payload = {
            "id": "provider-event",
            "bookmakers": [{
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-08-11T23:20:00Z",
                "markets": [{
                    "key": "batter_first_home_run",
                    "outcomes": [
                        {
                            "name": "Yes",
                            "description": "Batter A",
                            "price": 900,
                            "sid": "binary-offer",
                        }
                    ],
                }],
            }],
        }
        parsed = parse_additional_event_odds(
            payload,
            game=game,
            participant_index=participants,
            provider_event=event,
        )
        self.assertFalse(parsed.failures)
        self.assertEqual(len(parsed.quotes), 1)
        quote = parsed.quotes[0]
        self.assertEqual(quote["entity_id"], "301")
        self.assertEqual(quote["provider_participant_name"], "Batter A")
        self.assertEqual(
            quote["provider_participant_name_normalized"],
            normalize_name("Batter A"),
        )

        archived = archive_mod.build_archive_from_inputs(
            schedule=[game],
            quote_rows=parsed.quotes,
            provider_events=[event],
            participant_index=participants,
            captured_at=datetime(2026, 8, 11, 23, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(archived["pit_quote_count"], 1)
        row = archived["quotes"][0]
        self.assertEqual(row["provider_participant_name"], "Batter A")
        self.assertEqual(row["provider_participant_name_normalized"], "battera")
        self.assertEqual(row["entity_id"], "301")
        self.assertEqual(
            row["provider_event_sha256"],
            archive_mod._sha256_json(row["provider_event_snapshot"]),
        )


if __name__ == "__main__":
    unittest.main()
