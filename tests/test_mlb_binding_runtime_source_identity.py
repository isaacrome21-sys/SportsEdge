from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from sportsedge.game_odds_source import parse_game_event_odds
from sportsedge.mlb_binding_runtime import verify_runtime_binding_context
from sportsedge.mlb_market_binding_v13 import BindingError
from sportsedge.quote_bridge import validate_canonical_quote


def game(game_number=1):
    return SimpleNamespace(
        game_pk=123,
        game_number=game_number,
        home_id=10,
        away_id=20,
        home_team_id=10,
        away_team_id=20,
        home_name="Home Club",
        away_name="Away Club",
    )


def raw_quote(**changes):
    row = {
        "game_id": "123",
        "event_id": "123",
        "provider_event_id": "provider-evt",
        "game_number": 1,
        "event_home_team_id": "10",
        "event_away_team_id": "20",
        "period": "FG",
        "market": "MONEYLINE",
        "entity_id": "10",
        "team_id": "10",
        "side": "HOME",
        "book_key": "dk",
        "raw_market_name": "h2h",
        "retrieved_at": datetime(2026, 9, 8, 3, 0, tzinfo=timezone.utc),
        "american_odds": -110,
        "line": 0.0,
        "is_alternate": False,
    }
    row.update(changes)
    return row


class RuntimeSourceIdentityTests(unittest.TestCase):
    def test_normalization_preserves_but_does_not_create_identity(self):
        q = validate_canonical_quote(raw_quote())
        self.assertEqual(q["event_id"], "123")
        self.assertEqual(q["event_home_team_id"], "10")
        self.assertEqual(q["event_away_team_id"], "20")
        self.assertEqual(q["team_id"], "10")

        missing = raw_quote()
        missing.pop("event_id")
        q2 = validate_canonical_quote(missing)
        self.assertNotIn("event_id", q2)
        with self.assertRaises(BindingError):
            verify_runtime_binding_context(q2, game())

    def test_verifier_rejects_wrong_event_game_number_and_team_identity(self):
        attacks = (
            {"event_id": "999"},
            {"game_number": 2},
            {"event_home_team_id": "999"},
            {"event_away_team_id": "999"},
            {"team_id": "20"},
        )
        for attack in attacks:
            with self.subTest(attack=attack), self.assertRaises(BindingError):
                verify_runtime_binding_context(validate_canonical_quote(raw_quote(**attack)), game())

    def test_team_id_is_not_derived_from_entity_id(self):
        row = raw_quote()
        row.pop("team_id")
        q = validate_canonical_quote(row)
        self.assertNotIn("team_id", q)
        with self.assertRaises(BindingError):
            verify_runtime_binding_context(q, game())

    def test_ordinary_game_uses_event_id_without_fabricating_game_number(self):
        row = raw_quote()
        row.pop("game_number")
        q = validate_canonical_quote(row)
        self.assertNotIn("game_number", q)
        verified = verify_runtime_binding_context(q, game(game_number=None))
        self.assertNotIn("game_number", verified)
        self.assertEqual(verified["event_id"], "123")

    def test_doubleheader_game_number_is_required_when_schedule_supplies_it(self):
        row = raw_quote()
        row.pop("game_number")
        q = validate_canonical_quote(row)
        with self.assertRaisesRegex(BindingError, "game_number"):
            verify_runtime_binding_context(q, game(game_number=1))

    def test_acquisition_stamps_main_line_identity(self):
        payload = {
            "id": "provider-evt",
            "bookmakers": [{
                "key": "draftkings",
                "title": "DraftKings",
                "last_update": "2026-09-08T03:00:00Z",
                "markets": [{
                    "key": "h2h",
                    "last_update": "2026-09-08T03:00:00Z",
                    "outcomes": [
                        {"name": "Home Club", "price": -120, "sid": "h"},
                        {"name": "Away Club", "price": 110, "sid": "a"},
                    ],
                }],
            }],
        }
        snap = parse_game_event_odds(payload, game=game())
        self.assertFalse(snap.failures)
        self.assertEqual(len(snap.quotes), 2)
        for q in snap.quotes:
            self.assertEqual(q["event_id"], "123")
            self.assertEqual(q["provider_event_id"], "provider-evt")
            self.assertEqual(q["game_number"], 1)
            self.assertEqual(q["event_home_team_id"], "10")
            self.assertEqual(q["event_away_team_id"], "20")
            self.assertEqual(q["team_id"], q["entity_id"])


if __name__ == "__main__":
    unittest.main()
