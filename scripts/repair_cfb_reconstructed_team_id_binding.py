#!/usr/bin/env python3
"""Apply the pre-evaluation CFBD game-team ID binding repair.

The first identity repair canonicalized provider names through FBS membership aliases,
but run 36859279486 still stopped before materialization, line fetch, or holdout
evaluation with CFB_SEASON_POINTS_MISSING:New Mexico State. Historical game-name
vintages can differ from the current membership alias surface even when CFBD's stable
team IDs agree.

This transformer changes only reconstructed-acquisition identity binding: historical
game teams are bound by CFBD team ID first, then by the existing alias index. It does
not change the frozen request plan, model, features, weights, seeds, holdout thresholds,
or any evaluation/promotion authority.
"""
from __future__ import annotations

from hashlib import sha1
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/acquire_cfb_reconstructed_selection.py"
TEST = ROOT / "tests/test_cfb_reconstructed_team_id_binding.py"
EXPECTED_INPUT_GIT_BLOB_SHA1 = "b56b975787f7dc299163ead1f84743a45affb569"
PATCH_MARKER = "CFB_RECONSTRUCTED_TEAM_ID_BINDING_V1"


def _git_blob_sha(text: str) -> str:
    raw = text.encode("utf-8")
    return sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"CFB_TEAM_ID_REPAIR_REPLACEMENT_COUNT:{label}:{count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        print("CFB_RECONSTRUCTED_TEAM_ID_REPAIR_ALREADY_APPLIED")
        return 0
    actual = _git_blob_sha(text)
    if actual != EXPECTED_INPUT_GIT_BLOB_SHA1:
        raise SystemExit(f"CFB_TEAM_ID_REPAIR_SOURCE_BLOB_MISMATCH:{actual}")

    text = _replace_once(
        text,
        'CFB_RECONSTRUCTED_IDENTITY_ALIAS_V1 = "FBS_MEMBERSHIP_ALIAS_CANONICAL_V1"\n\n\ndef _canonical_team_or_none',
        'CFB_RECONSTRUCTED_IDENTITY_ALIAS_V1 = "FBS_MEMBERSHIP_ALIAS_CANONICAL_V1"\n'
        'CFB_RECONSTRUCTED_TEAM_ID_BINDING_V1 = "CFBD_TEAM_ID_FIRST_ALIAS_FALLBACK_V1"\n\n\n'
        'def _membership_id_index(rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:\n'
        '    out: dict[str, str] = {}\n'
        '    for row in rows:\n'
        '        team_id = str(row.get("id") or "").strip()\n'
        '        school = str(row.get("school") or "").strip()\n'
        '        if team_id and school:\n'
        '            prior = out.get(team_id)\n'
        '            if prior is not None and prior != school:\n'
        '                raise CFBAcquisitionError(f"CFB_MEMBERSHIP_TEAM_ID_COLLISION:{team_id}")\n'
        '            out[team_id] = school\n'
        '    return out\n\n\n'
        'def _canonical_game_team(\n'
        '    row: Mapping[str, Any],\n'
        '    *,\n'
        '    team_key: str,\n'
        '    id_key: str,\n'
        '    alias_index: Mapping[str, str],\n'
        '    id_index: Mapping[str, str],\n'
        ') -> str | None:\n'
        '    team_id = str(row.get(id_key) or "").strip()\n'
        '    if team_id and team_id in id_index:\n'
        '        return str(id_index[team_id])\n'
        '    return _canonical_team_or_none(row.get(team_key), alias_index)\n\n\n'
        'def _canonical_team_or_none',
        "helpers",
    )

    old_points = '''def _points_by_team(
    games: list[Mapping[str, Any]],
    through_week: int,
    *,
    alias_index: Mapping[str, str],
) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in games:
        if row.get("completed") is not True:
            continue
        try:
            week = int(row.get("week", 0))
        except (TypeError, ValueError):
            continue
        if week > through_week:
            continue
        for team_key, points_key in (("homeTeam", "homePoints"), ("awayTeam", "awayPoints")):
            team = _canonical_team_or_none(row.get(team_key), alias_index)
            points = row.get(points_key)
            if team is not None and points is not None:
                out[team] = out.get(team, 0.0) + float(points)
    return out
'''
    new_points = '''def _points_by_team(
    games: list[Mapping[str, Any]],
    through_week: int,
    *,
    alias_index: Mapping[str, str],
    id_index: Mapping[str, str] | None = None,
) -> dict[str, float]:
    id_index = id_index or {}
    out: dict[str, float] = {}
    for row in games:
        if row.get("completed") is not True:
            continue
        try:
            week = int(row.get("week", 0))
        except (TypeError, ValueError):
            continue
        if week > through_week:
            continue
        for team_key, id_key, points_key in (
            ("homeTeam", "homeId", "homePoints"),
            ("awayTeam", "awayId", "awayPoints"),
        ):
            team = _canonical_game_team(
                row,
                team_key=team_key,
                id_key=id_key,
                alias_index=alias_index,
                id_index=id_index,
            )
            points = row.get(points_key)
            if team is not None and points is not None:
                out[team] = out.get(team, 0.0) + float(points)
    return out
'''
    text = _replace_once(text, old_points, new_points, "points_by_team")

    old_games = '''    games: list[dict[str, Any]] = []
    for season in range(2015, 2026):
        alias_index = build_team_alias_index(membership_by_season[season])
        for row in games_by_season[season]:
            if row.get("completed") is not True:
                continue
            home = _canonical_team_or_none(row.get("homeTeam"), alias_index)
            away = _canonical_team_or_none(row.get("awayTeam"), alias_index)
            if home is None or away is None:
                continue
'''
    new_games = '''    games: list[dict[str, Any]] = []
    for season in range(2015, 2026):
        alias_index = build_team_alias_index(membership_by_season[season])
        id_index = _membership_id_index(membership_by_season[season])
        for row in games_by_season[season]:
            if row.get("completed") is not True:
                continue
            home = _canonical_game_team(
                row, team_key="homeTeam", id_key="homeId", alias_index=alias_index, id_index=id_index
            )
            away = _canonical_game_team(
                row, team_key="awayTeam", id_key="awayId", alias_index=alias_index, id_index=id_index
            )
            if home is None or away is None:
                continue
'''
    text = _replace_once(text, old_games, new_games, "selection_games")

    old_prior = '''        alias_index = build_team_alias_index(membership_by_season[season + 1])
        points = _points_by_team(
            games_by_season[season], through_week=99, alias_index=alias_index
        )
'''
    new_prior = '''        alias_index = build_team_alias_index(membership_by_season[season + 1])
        id_index = _membership_id_index(membership_by_season[season + 1])
        points = _points_by_team(
            games_by_season[season],
            through_week=99,
            alias_index=alias_index,
            id_index=id_index,
        )
'''
    text = _replace_once(text, old_prior, new_prior, "prior_points")

    old_current = '''    for season in range(2015, 2026):
        alias_index = build_team_alias_index(membership_by_season[season])
        for end_week in range(1, 20):
'''
    new_current = '''    for season in range(2015, 2026):
        alias_index = build_team_alias_index(membership_by_season[season])
        id_index = _membership_id_index(membership_by_season[season])
        for end_week in range(1, 20):
'''
    text = _replace_once(text, old_current, new_current, "current_id_index")

    old_current_points = '''            points = _points_by_team(
                games_by_season[season], through_week=end_week, alias_index=alias_index
            )
'''
    new_current_points = '''            points = _points_by_team(
                games_by_season[season],
                through_week=end_week,
                alias_index=alias_index,
                id_index=id_index,
            )
'''
    text = _replace_once(text, old_current_points, new_current_points, "current_points")

    test_text = '''from __future__ import annotations

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
'''

    TARGET.write_text(text, encoding="utf-8")
    TEST.write_text(test_text, encoding="utf-8")
    print("CFB_RECONSTRUCTED_TEAM_ID_REPAIR_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
