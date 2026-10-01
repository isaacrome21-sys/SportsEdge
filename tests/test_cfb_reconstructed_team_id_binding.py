from __future__ import annotations

import unittest

from scripts.acquire_cfb_reconstructed_selection import (
    _canonical_game_team,
    _membership_id_index,
    _points_by_team,
)
from sportsedge.sports.cfb.source import build_team_alias_index


class TestCFBReconstructedTeamIdBinding(unittest.TestCase):
    def setUp(self):
        self.membership = [
            {
                "id": 166,
                "school": "New Mexico State",
                "abbreviation": "NMSU",
                "mascot": "Aggies",
                "alternateNames": [],
            }
        ]
        self.alias = build_team_alias_index(self.membership)
        self.ids = _membership_id_index(self.membership)

    def test_game_id_binds_when_historical_name_is_not_an_alias(self):
        row = {
            "completed": True,
            "week": 1,
            "homeId": 166,
            "homeTeam": "New Mexico St.",
            "homePoints": 28,
            "awayId": 999999,
            "awayTeam": "FCS Opponent",
            "awayPoints": 7,
        }
        self.assertEqual(
            _canonical_game_team(
                row,
                team_key="homeTeam",
                id_key="homeId",
                alias_index=self.alias,
                id_index=self.ids,
            ),
            "New Mexico State",
        )
        self.assertEqual(
            _points_by_team([row], 99, alias_index=self.alias, id_index=self.ids),
            {"New Mexico State": 28.0},
        )

    def test_alias_fallback_still_works_without_team_id(self):
        row = {
            "completed": True,
            "week": 1,
            "homeTeam": "NMSU",
            "homePoints": 14,
            "awayTeam": "FCS Opponent",
            "awayPoints": 3,
        }
        self.assertEqual(
            _points_by_team([row], 99, alias_index=self.alias, id_index=self.ids),
            {"New Mexico State": 14.0},
        )


if __name__ == "__main__":
    unittest.main()
