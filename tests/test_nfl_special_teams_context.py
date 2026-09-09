from __future__ import annotations

import unittest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.special_teams_context import build_special_teams_provider


_ROWS = [
    {
        "team_id": "CHI",
        "kicker_active": True,
        "returner_active": True,
        "field_goal_pct_40_49": 0.80,
        "field_goal_pct_50_plus": 0.67,
        "touchback_rate": 0.75,
        "punt_net_yards": 41.2,
    },
    {
        "team_id": "GB",
        "kicker_active": True,
        "returner_active": True,
        "field_goal_pct_40_49": 0.82,
        "field_goal_pct_50_plus": 0.64,
        "touchback_rate": 0.73,
        "punt_net_yards": 42.0,
    },
]


class NFLSpecialTeamsContextTests(unittest.TestCase):
    def test_provider_is_pregame_and_provenance_bound(self):
        result = build_special_teams_provider(
            game_id="2026_01_GB_CHI",
            as_of="2026-09-09T23:00:00+00:00",
            kickoff_ts="2026-09-10T00:00:00+00:00",
            source_uri="https://example.test/nfl-special-teams.csv",
            source_sha256="a" * 64,
            rows=_ROWS,
        )
        self.assertEqual(result["status"], "AVAILABLE")
        self.assertEqual(result["source_sha256"], "a" * 64)
        self.assertEqual(result["observed_at"].isoformat(), "2026-09-09T23:00:00+00:00")
        self.assertEqual(result["kickoff_ts"], "2026-09-10T00:00:00+00:00")
        self.assertEqual([row["team_id"] for row in result["payload"]["teams"]], ["CHI", "GB"])

    def test_at_or_after_kickoff_is_rejected(self):
        for as_of in ("2026-09-10T00:00:00+00:00", "2026-09-10T00:00:01+00:00"):
            with self.subTest(as_of=as_of):
                with self.assertRaisesRegex(NFLContextError, "NFL_SPECIAL_TEAMS_NOT_PREGAME:2026_01_GB_CHI"):
                    build_special_teams_provider(
                        game_id="2026_01_GB_CHI",
                        as_of=as_of,
                        kickoff_ts="2026-09-10T00:00:00+00:00",
                        source_uri="https://example.test/nfl-special-teams.csv",
                        source_sha256="a" * 64,
                        rows=_ROWS,
                    )

    def test_invalid_source_hash_is_rejected(self):
        with self.assertRaisesRegex(NFLContextError, "special teams source_sha256 invalid"):
            build_special_teams_provider(
                game_id="2026_01_GB_CHI",
                as_of="2026-09-09T23:00:00+00:00",
                kickoff_ts="2026-09-10T00:00:00+00:00",
                source_uri="https://example.test/nfl-special-teams.csv",
                source_sha256="not-a-sha",
                rows=_ROWS,
            )

    def test_duplicate_team_identity_is_rejected(self):
        duplicate = [_ROWS[0], dict(_ROWS[0])]
        with self.assertRaisesRegex(NFLContextError, "special teams duplicate team_id"):
            build_special_teams_provider(
                game_id="2026_01_GB_CHI",
                as_of="2026-09-09T23:00:00+00:00",
                kickoff_ts="2026-09-10T00:00:00+00:00",
                source_uri="https://example.test/nfl-special-teams.csv",
                source_sha256="b" * 64,
                rows=duplicate,
            )


if __name__ == "__main__":
    unittest.main()
