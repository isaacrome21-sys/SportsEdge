from datetime import datetime, timezone
import json
import unittest

from sportsedge.free_game_market_acquisition import acquire_mlb_game_markets_free_first
from sportsedge.mlb_source import GameSnapshot

NOW = datetime(2026, 9, 15, 15, 0, tzinfo=timezone.utc)


class Resp:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.payload).encode()


class FreeGameMarketAcquisitionTests(unittest.TestCase):
    def game(self):
        return GameSnapshot(
            game_pk=777, game_date="2026-09-15T23:40:00Z", status="Preview",
            away_id=119, away_name="Los Angeles Dodgers", home_id=115,
            home_name="Colorado Rockies", away_probable_pitcher_id=None,
            away_probable_pitcher_name=None, home_probable_pitcher_id=None,
            home_probable_pitcher_name=None, retrieved_at=NOW.isoformat(), venue_id=19,
            official_date="2026-09-15",
        )

    def opener(self, req, timeout=15):
        return Resp({"events": [{
            "id": "espn1", "date": "2026-09-15T23:40:00Z",
            "competitions": [{
                "competitors": [
                    {"homeAway": "away", "team": {"displayName": "Los Angeles Dodgers"}},
                    {"homeAway": "home", "team": {"displayName": "Colorado Rockies"}},
                ],
                "odds": [{
                    "provider": {"displayName": "DraftKings"},
                    "lastUpdated": "2026-09-15T14:59:30Z",
                    "moneyline": {"home": {"close": {"odds": "+150"}}, "away": {"close": {"odds": "-175"}}},
                    "pointSpread": {"home": {"close": {"line": "+1.5", "odds": "-110"}}, "away": {"close": {"line": "-1.5", "odds": "-110"}}},
                    "total": {"over": {"close": {"line": "o11.5", "odds": "-105"}}, "under": {"close": {"line": "u11.5", "odds": "-115"}}},
                }],
            }],
        }]})

    def test_eligible_espn_game_quotes_avoid_paid_transport(self):
        paid = []
        out = acquire_mlb_game_markets_free_first(
            schedule=[self.game()], opener=self.opener, now=NOW,
            required_book="DraftKings", paid_fetch=lambda: paid.append(True) or [],
        )
        self.assertEqual(len(out.quotes), 6)
        self.assertEqual(paid, [])
        self.assertTrue(all(q["provider_contract"]["provider"] == "ESPN_SCOREBOARD" for q in out.quotes))


if __name__ == "__main__":
    unittest.main()
