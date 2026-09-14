from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

from sportsedge.draftkings_prop_source import (
    _parse_v5_eventgroup,
    parse_category_payload,
)

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "archive_mlb_prop_odds.py"
SPEC = importlib.util.spec_from_file_location("archive_mlb_prop_odds_live_schema", SCRIPT)
archive = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(archive)


class MLBPropLiveSchemaRegressionTests(unittest.TestCase):
    def test_current_dk_start_event_date_is_accepted(self):
        self.assertEqual(
            archive._event_first_pitch(
                {"id": "34664936", "startEventDate": "2026-09-14T23:10:00.0000000Z"}
            ),
            datetime(2026, 9, 14, 23, 10, tzinfo=timezone.utc),
        )

    def test_league_level_markets_can_bind_event_and_nested_participant(self):
        payload = {
            "events": [
                {"id": "34664936", "startEventDate": "2026-09-14T23:10:00.0000000Z"}
            ],
            "markets": [
                {
                    "id": "m1",
                    "eventId": "34664936",
                    "name": "Player Hits O/U",
                }
            ],
            "selections": [
                {
                    "marketId": "m1",
                    "eventId": "34664936",
                    "participants": [{"id": "p1", "name": "Example Hitter"}],
                    "label": "Over",
                    "outcomeType": "Over",
                    "points": 0.5,
                    "displayOdds": {"american": "-115"},
                }
            ],
        }
        snap = parse_category_payload(
            payload,
            retrieved_at=datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(snap.quotes), 1)
        row = snap.quotes[0]
        self.assertEqual(row["provider_event_id"], "34664936")
        self.assertEqual(row["market"], "HITS")
        self.assertEqual(row["entity_name"], "Example Hitter")
        self.assertEqual(row["american_odds"], -115)

    def test_v5_nested_offer_shape_parses_pitcher_prop(self):
        payload = {
            "eventGroup": {
                "offerCategories": [
                    {
                        "name": "Player Props",
                        "offerSubcategoryDescriptors": [
                            {
                                "name": "Pitcher Strikeouts",
                                "offerSubcategory": {
                                    "offers": [
                                        [
                                            {
                                                "providerOfferId": "o1",
                                                "providerEventId": "34664936",
                                                "label": "Pitcher Strikeouts",
                                                "outcomes": [
                                                    {
                                                        "participant": "Example Pitcher",
                                                        "label": "Over 5.5",
                                                        "outcomeType": "Over",
                                                        "line": 5.5,
                                                        "oddsAmerican": "−105",
                                                    }
                                                ],
                                            }
                                        ]
                                    ]
                                },
                            }
                        ],
                    }
                ]
            }
        }
        snap = _parse_v5_eventgroup(
            payload,
            retrieved_at=datetime(2026, 9, 14, 22, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(snap.quotes), 1)
        row = snap.quotes[0]
        self.assertEqual(row["provider_event_id"], "34664936")
        self.assertEqual(row["market"], "PITCHER_K")
        self.assertEqual(row["line"], 5.5)
        self.assertEqual(row["american_odds"], -105)

    def test_unknown_market_still_fails_closed(self):
        payload = {
            "markets": [{"id": "m1", "eventId": "1", "name": "Mystery Stat"}],
            "selections": [
                {
                    "marketId": "m1",
                    "eventId": "1",
                    "participant": "Player",
                    "label": "Over",
                    "points": 1.5,
                    "oddsAmerican": -110,
                }
            ],
        }
        snap = parse_category_payload(payload)
        self.assertEqual(snap.quotes, ())


if __name__ == "__main__":
    unittest.main()
