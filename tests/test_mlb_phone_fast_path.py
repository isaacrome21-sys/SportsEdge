import importlib.util
import json
import unittest
from dataclasses import asdict
from pathlib import Path

from sportsedge.canonical_manual_mlb import _resolve_game, _resolve_subject, _resolve_subjects
from sportsedge.manual_quote import validate_manual_quote
from sportsedge.mlb_source import GameSnapshot


SPEC = importlib.util.spec_from_file_location(
    "run_manual_mlb_snapshot_fast_path", Path("scripts/run_manual_mlb_snapshot.py")
)
RUNNER = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(RUNNER)


GAME = GameSnapshot(
    849851,
    "2026-09-30T00:00:00+00:00",
    "Preview",
    111,
    "Boston Red Sox",
    147,
    "New York Yankees",
    701234,
    "Payton Tolle",
    808765,
    "Cam Schlittler",
    "2026-09-29T20:00:01+00:00",
    official_date="2026-09-29",
)


def _quote(market_type, *, subject_name=None):
    raw = {
        "game_id": "Boston Red Sox@New York Yankees",
        "market_type": market_type,
        "side": "OVER",
        "line": 1.5,
        "price": -110,
        "paired_side": "UNDER",
        "paired_price": -110,
        "book": "draftkings",
        "observed_at": "2026-09-29T15:00:00-05:00",
        "first_pitch_at": "2026-09-30T00:00:00+00:00",
        "source": "MANUAL",
    }
    if subject_name:
        raw["subject_name"] = subject_name
    return validate_manual_quote(raw)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class MlbPhoneFastPathTest(unittest.TestCase):
    def test_supplied_schedule_avoids_schedule_refetch(self):
        row = _quote("MONEYLINE")

        def no_network(*args, **kwargs):
            raise AssertionError("schedule network fetch should not occur")

        resolved = _resolve_game(row, opener=no_network, schedule=[GAME])
        self.assertEqual(resolved.game_pk, GAME.game_pk)

    def test_probable_pitcher_resolves_from_same_schedule_snapshot(self):
        row = _quote("PITCHER_OUTS", subject_name="Cam Schlittler")

        def no_network(*args, **kwargs):
            raise AssertionError("People API should not be needed for probable pitcher")

        self.assertEqual(
            _resolve_subject(row, opener=no_network, game=GAME),
            (str(GAME.home_probable_pitcher_id), GAME.home_id),
        )

    def test_repeated_player_props_share_one_people_lookup(self):
        rows = [
            _quote("BATTER_HITS", subject_name="Aaron Judge"),
            _quote("BATTER_TOTAL_BASES", subject_name="Aaron Judge"),
        ]
        calls = []

        def opener(url, timeout=15):
            calls.append(url)
            return _Response({
                "people": [{
                    "id": 592450,
                    "fullName": "Aaron Judge",
                    "currentTeam": {"id": GAME.home_id},
                }]
            })

        resolved, errors = _resolve_subjects(rows, GAME, opener=opener)
        self.assertEqual(len(calls), 1)
        self.assertEqual(resolved, [("592450", GAME.home_id), ("592450", GAME.home_id)])
        self.assertEqual(errors, [None, None])

    def test_runner_rehydrates_exact_schedule_snapshot(self):
        schedule = RUNNER._schedule_snapshot({"schedule_snapshot": [asdict(GAME)]})
        self.assertEqual(schedule, [GAME])

    def test_runner_rejects_malformed_schedule_snapshot(self):
        with self.assertRaisesRegex(ValueError, "MANUAL_SCHEDULE_SNAPSHOT_INVALID"):
            RUNNER._schedule_snapshot({"schedule_snapshot": ["not-a-game"]})


if __name__ == "__main__":
    unittest.main()
