from copy import deepcopy
import unittest

from research.nba_props_forward_20261020.nba_cdn_admission_battery import (
    SECTION3_INTEGRITY_CODES,
    parse_boxscore,
    parse_minutes,
    section3_integrity_pass,
)


GAME_ID = "0022600001"


def _payload(*, game_time="2026-10-20T23:30:00Z", played="1", minutes="PT12M30.00S"):
    player = {
        "personId": 101,
        "name": "Test Player",
        "jerseyNum": "1",
        "position": "G",
        "played": played,
        "statistics": {
            "minutes": minutes,
            "points": 10,
            "reboundsTotal": 4,
            "assists": 3,
        },
    }
    return {
        "game": {
            "gameId": GAME_ID,
            "gameStatus": 3,
            "gameTimeUTC": game_time,
            "period": 4,
            "homeTeam": {
                "teamId": 1610612737,
                "teamTricode": "ATL",
                "players": [player],
            },
            "awayTeam": {
                "teamId": 1610612738,
                "teamTricode": "BOS",
                "players": [],
            },
        }
    }


def _codes(issues):
    return [code for code, _detail in issues]


class NBACDNAdmissionBatteryIntegrityTests(unittest.TestCase):
    def test_timezone_less_game_start_is_integrity_blocking(self):
        record, issues = parse_boxscore(
            _payload(game_time="2026-10-20T23:30:00"), GAME_ID)

        self.assertIsNotNone(record)
        self.assertIn("GAME_DATE_UNKNOWN", _codes(issues))
        self.assertFalse(section3_integrity_pass(1, {"GAME_DATE_UNKNOWN": 1}))

    def test_non_utc_offset_game_start_is_integrity_blocking(self):
        record, issues = parse_boxscore(
            _payload(game_time="2026-10-20T18:30:00-05:00"), GAME_ID)

        self.assertIsNotNone(record)
        self.assertIn("GAME_DATE_UNKNOWN", _codes(issues))

    def test_every_declared_integrity_refusal_blocks_section_three(self):
        for code in SECTION3_INTEGRITY_CODES:
            with self.subTest(code=code):
                self.assertFalse(section3_integrity_pass(1, {code: 1}))
        self.assertTrue(section3_integrity_pass(1, {}))

    def test_nonfinite_negative_or_malformed_minutes_are_rejected(self):
        for value in ("NaN", "Infinity", "-1", "PT", "PT..S", "12:60"):
            with self.subTest(value=value):
                self.assertIsNone(parse_minutes(value))

    def test_malformed_played_state_is_schema_invalid_not_dnp(self):
        for played in ("yes", "2", 2, True, None):
            with self.subTest(played=played):
                record, issues = parse_boxscore(_payload(played=played), GAME_ID)
                self.assertIsNotNone(record)
                self.assertIn("SCHEMA_INVALID", _codes(issues))
                self.assertEqual(record["dnp_count"], 0)
                self.assertEqual(record["observations"], [])

    def test_nonfinite_minutes_are_schema_invalid_not_eligible(self):
        record, issues = parse_boxscore(_payload(minutes="NaN"), GAME_ID)

        self.assertIsNotNone(record)
        self.assertIn("SCHEMA_INVALID", _codes(issues))
        self.assertEqual(record["dnp_count"], 0)
        self.assertEqual(record["observations"], [])

    def test_played_zero_with_positive_minutes_is_schema_invalid(self):
        record, issues = parse_boxscore(_payload(played="0", minutes="PT1M"), GAME_ID)

        self.assertIsNotNone(record)
        self.assertIn("SCHEMA_INVALID", _codes(issues))
        self.assertEqual(record["dnp_count"], 0)

    def test_zero_minute_dnp_is_excluded_without_requiring_position(self):
        payload = deepcopy(_payload(played="0", minutes="PT0S"))
        payload["game"]["homeTeam"]["players"][0]["position"] = ""

        record, issues = parse_boxscore(payload, GAME_ID)

        self.assertIsNotNone(record)
        self.assertEqual(issues, [])
        self.assertEqual(record["dnp_count"], 1)
        self.assertEqual(record["observations"], [])

    def test_valid_played_row_remains_eligible(self):
        record, issues = parse_boxscore(_payload(), GAME_ID)

        self.assertEqual(issues, [])
        self.assertIsNotNone(record)
        self.assertEqual(record["dnp_count"], 0)
        self.assertEqual(len(record["observations"]), 1)
        self.assertAlmostEqual(record["observations"][0]["minutes"], 12.5)


if __name__ == "__main__":
    unittest.main()
