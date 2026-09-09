from __future__ import annotations

from hashlib import sha256
import unittest

from sportsedge.sports.nfl.auto_context_source import build_nfl_auto_game_context
from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.history import NFLVERSE_SCHEDULE_CSV


class _Response:
    def __init__(self, raw: bytes):
        self.raw = raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.raw


def _schedule() -> bytes:
    return (
        "game_id,season,week,home_team,away_team,game_start_ts,location,home_rest,away_rest,stadium,surface,roof\n"
        "2026_01_GB_CHI,2026,1,CHI,GB,2026-09-10T00:00:00+00:00,Home,7,7,,grass,open\n"
    ).encode()


def _opener(raw: bytes):
    def open_(_request, timeout=20):
        assert timeout == 20
        return _Response(raw)
    return open_


class NFLAutoContextSourceTests(unittest.TestCase):
    def test_pregame_context_binds_schedule_and_registry_provenance(self):
        raw = _schedule()
        result = build_nfl_auto_game_context(
            game_id="2026_01_GB_CHI",
            as_of="2026-09-09T23:00:00+00:00",
            opener=_opener(raw),
        )
        self.assertEqual(result["game_id"], "2026_01_GB_CHI")
        self.assertEqual(result["kickoff_ts"], "2026-09-10T00:00:00+00:00")
        self.assertEqual(result["schedule_source_uri"], NFLVERSE_SCHEDULE_CSV)
        self.assertEqual(result["schedule_source_sha256"], sha256(raw).hexdigest())
        provider = result["auto_rest_travel_provider"]
        self.assertEqual(provider["status"], "AVAILABLE")
        self.assertEqual(len(provider["source_sha256"]), 64)
        self.assertEqual(provider["observed_at"].isoformat(), "2026-09-09T23:00:00+00:00")
        for team in ("CHI", "GB"):
            row = provider["payload"][team]
            self.assertEqual(row["schedule_source_sha256"], sha256(raw).hexdigest())
            self.assertEqual(len(row["stadium_registry_sha256"]), 64)

    def test_at_or_after_kickoff_is_rejected(self):
        raw = _schedule()
        for as_of in ("2026-09-10T00:00:00+00:00", "2026-09-10T00:00:01+00:00"):
            with self.subTest(as_of=as_of):
                with self.assertRaisesRegex(NFLContextError, "NFL_AUTO_CONTEXT_NOT_PREGAME:2026_01_GB_CHI"):
                    build_nfl_auto_game_context(
                        game_id="2026_01_GB_CHI",
                        as_of=as_of,
                        opener=_opener(raw),
                    )

    def test_schedule_bytes_are_the_provenance_unit(self):
        raw = _schedule()
        changed = raw.replace(b",grass,", b",turf,")
        first = build_nfl_auto_game_context(
            game_id="2026_01_GB_CHI",
            as_of="2026-09-09T23:00:00+00:00",
            opener=_opener(raw),
        )
        second = build_nfl_auto_game_context(
            game_id="2026_01_GB_CHI",
            as_of="2026-09-09T23:00:00+00:00",
            opener=_opener(changed),
        )
        self.assertNotEqual(first["schedule_source_sha256"], second["schedule_source_sha256"])
        self.assertNotEqual(
            first["auto_rest_travel_provider"]["source_sha256"],
            second["auto_rest_travel_provider"]["source_sha256"],
        )


if __name__ == "__main__":
    unittest.main()
