from __future__ import annotations

import unittest

from scripts.acquire_cfb_reconstructed_selection import (
    CFBAcquisitionError,
    _canonical_advanced_row,
    _points_by_team,
)
from sportsedge.sports.cfb.source import build_team_alias_index


class TestCFBReconstructedIdentityAlias(unittest.TestCase):
    def setUp(self):
        self.membership = [
            {
                "school": "New Mexico State",
                "abbreviation": "NMSU",
                "mascot": "Aggies",
                "alternateNames": ["New Mexico St."],
            }
        ]
        self.alias = build_team_alias_index(self.membership)

    def test_game_alias_and_advanced_school_share_canonical_points_key(self):
        games = [
            {
                "completed": True,
                "week": 1,
                "homeTeam": "New Mexico St.",
                "homePoints": 24,
                "awayTeam": "FCS Opponent",
                "awayPoints": 10,
            }
        ]
        points = _points_by_team(games, 99, alias_index=self.alias)
        self.assertEqual(points, {"New Mexico State": 24.0})
        row = _canonical_advanced_row(
            {"team": "NMSU"}, alias_index=self.alias, allow_outside_membership=False
        )
        self.assertEqual(row["team"], "New Mexico State")

    def test_prior_row_outside_next_season_membership_is_dropped(self):
        self.assertIsNone(
            _canonical_advanced_row(
                {"team": "Departed FBS Team"},
                alias_index=self.alias,
                allow_outside_membership=True,
            )
        )

    def test_current_unresolved_team_still_fails_closed(self):
        with self.assertRaisesRegex(CFBAcquisitionError, "ADVANCED_TEAM_UNRESOLVED"):
            _canonical_advanced_row(
                {"team": "Unknown Alias"},
                alias_index=self.alias,
                allow_outside_membership=False,
            )


if __name__ == "__main__":
    unittest.main()
