#!/usr/bin/env python3
"""Apply the pre-evaluation CFB reconstructed-provider identity repair.

Run #36853200294 stopped before materialization, line fetch, or holdout evaluation
because a CFBD advanced-stat team identity did not match the raw game-score key.
This transformer changes only reconstructed-acquisition identity normalization. It
must not change the model, features, weights, seeds, holdout thresholds, or the
frozen 200-call provider plan.

The repair is intentionally hash-guarded. It patches only the exact acquisition
source that produced the blocked pre-evaluation run, then writes a focused unit test.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/acquire_cfb_reconstructed_selection.py"
TEST = ROOT / "tests/test_cfb_reconstructed_identity_alias.py"
EXPECTED_ORIGINAL_SHA256 = "22e0b57d3a97cdf489005e887b81aa0260d4b3ba39e756f5949f0408f3053108"
PATCH_MARKER = "CFB_RECONSTRUCTED_IDENTITY_ALIAS_V1"


def _sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"CFB_IDENTITY_REPAIR_REPLACEMENT_COUNT:{label}:{count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        print("CFB_RECONSTRUCTED_IDENTITY_REPAIR_ALREADY_APPLIED")
        return 0
    actual = _sha(text)
    if actual != EXPECTED_ORIGINAL_SHA256:
        raise SystemExit(f"CFB_IDENTITY_REPAIR_SOURCE_SHA_MISMATCH:{actual}")

    text = _replace_once(
        text,
        "from sportsedge.sports.cfb.source import normalize_advanced_team_metrics\n",
        "from sportsedge.sports.cfb.source import (\n"
        "    CFBSourceError,\n"
        "    bind_provider_team,\n"
        "    build_team_alias_index,\n"
        "    normalize_advanced_team_metrics,\n"
        ")\n",
        "source_imports",
    )

    old_points = '''def _points_by_team(games: list[Mapping[str, Any]], through_week: int) -> dict[str, float]:
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
            team = str(row.get(team_key) or "").strip()
            points = row.get(points_key)
            if team and points is not None:
                out[team] = out.get(team, 0.0) + float(points)
    return out
'''
    new_points = '''CFB_RECONSTRUCTED_IDENTITY_ALIAS_V1 = "FBS_MEMBERSHIP_ALIAS_CANONICAL_V1"


def _canonical_team_or_none(name: object, alias_index: Mapping[str, str]) -> str | None:
    text = str(name or "").strip()
    if not text:
        return None
    try:
        return bind_provider_team(text, alias_index)
    except CFBSourceError:
        # /games?classification=fbs may include a non-FBS opponent. Only the FBS
        # identity is needed for the advanced-stat points denominator contract.
        return None


def _points_by_team(
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
    text = _replace_once(text, old_points, new_points, "points_by_team")

    old_membership = '''def _membership_set(rows: list[Mapping[str, Any]]) -> set[str]:
    return {
        str(row.get("school") or "").strip()
        for row in rows
        if str(row.get("school") or "").strip()
    }
'''
    new_membership = old_membership + '''

def _canonical_advanced_row(
    raw: Mapping[str, Any],
    *,
    alias_index: Mapping[str, str],
    allow_outside_membership: bool,
) -> dict[str, Any] | None:
    provider_team = str(raw.get("team") or "").strip()
    if not provider_team:
        raise CFBAcquisitionError("CFB_ACQUISITION_ADVANCED_TEAM_MISSING")
    try:
        canonical = bind_provider_team(provider_team, alias_index)
    except CFBSourceError as exc:
        if allow_outside_membership:
            # Prior-year fallback rows are needed only for teams that are FBS in
            # the target season. A team outside next season's membership cannot
            # be selected as a week-1 prior and is intentionally discarded.
            return None
        raise CFBAcquisitionError(
            f"CFB_ACQUISITION_ADVANCED_TEAM_UNRESOLVED:{provider_team}"
        ) from exc
    row = dict(raw)
    row["team"] = canonical
    return row
'''
    text = _replace_once(text, old_membership, new_membership, "advanced_identity_helper")

    old_games = '''    games: list[dict[str, Any]] = []
    for season in range(2015, 2026):
        membership = _membership_set(membership_by_season[season])
        for row in games_by_season[season]:
            if row.get("completed") is not True:
                continue
            home = str(row.get("homeTeam") or "").strip()
            away = str(row.get("awayTeam") or "").strip()
            if home not in membership or away not in membership:
                continue
'''
    new_games = '''    games: list[dict[str, Any]] = []
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
    text = _replace_once(text, old_games, new_games, "selection_game_identity")

    old_prior = '''    metrics: list[dict[str, Any]] = []
    for season in range(2014, 2025):
        advanced, meta = by_identity[("/stats/season/advanced", season, None)]
        if not isinstance(advanced, list):
            raise CFBAcquisitionError(f"CFB_ACQUISITION_ADVANCED_NOT_LIST:{season}:prior")
        points = _points_by_team(games_by_season[season], through_week=99)
        for raw in advanced:
            if isinstance(raw, Mapping):
                metrics.append(normalize_advanced_team_metrics(
                    raw,
                    through_week=99,
                    feature_asof_ts=str(meta["retrieved_at_utc"]),
                    season_points=points,
                    sample_source="PRIOR_SEASON_FALLBACK",
                ).to_dict())
'''
    new_prior = '''    metrics: list[dict[str, Any]] = []
    for season in range(2014, 2025):
        advanced, meta = by_identity[("/stats/season/advanced", season, None)]
        if not isinstance(advanced, list):
            raise CFBAcquisitionError(f"CFB_ACQUISITION_ADVANCED_NOT_LIST:{season}:prior")
        # A season-S prior is consumed only by season S+1 week 1. Canonicalize
        # both scores and advanced rows through the target season's authoritative
        # FBS membership aliases; no extra provider call is needed for 2014.
        alias_index = build_team_alias_index(membership_by_season[season + 1])
        points = _points_by_team(
            games_by_season[season], through_week=99, alias_index=alias_index
        )
        for raw in advanced:
            if isinstance(raw, Mapping):
                canonical_raw = _canonical_advanced_row(
                    raw,
                    alias_index=alias_index,
                    allow_outside_membership=True,
                )
                if canonical_raw is None:
                    continue
                metrics.append(normalize_advanced_team_metrics(
                    canonical_raw,
                    through_week=99,
                    feature_asof_ts=str(meta["retrieved_at_utc"]),
                    season_points=points,
                    sample_source="PRIOR_SEASON_FALLBACK",
                ).to_dict())
'''
    text = _replace_once(text, old_prior, new_prior, "prior_metrics_identity")

    old_current = '''    for season in range(2015, 2026):
        for end_week in range(1, 20):
            advanced, meta = by_identity[("/stats/season/advanced", season, end_week)]
            if not isinstance(advanced, list):
                raise CFBAcquisitionError(f"CFB_ACQUISITION_ADVANCED_NOT_LIST:{season}:{end_week}")
            points = _points_by_team(games_by_season[season], through_week=end_week)
            for raw in advanced:
                if isinstance(raw, Mapping):
                    metrics.append(normalize_advanced_team_metrics(
                        raw,
                        through_week=end_week,
                        feature_asof_ts=str(meta["retrieved_at_utc"]),
                        season_points=points,
                        sample_source="CURRENT_SEASON_PRIOR_WEEKS",
                    ).to_dict())
'''
    new_current = '''    for season in range(2015, 2026):
        alias_index = build_team_alias_index(membership_by_season[season])
        for end_week in range(1, 20):
            advanced, meta = by_identity[("/stats/season/advanced", season, end_week)]
            if not isinstance(advanced, list):
                raise CFBAcquisitionError(f"CFB_ACQUISITION_ADVANCED_NOT_LIST:{season}:{end_week}")
            points = _points_by_team(
                games_by_season[season], through_week=end_week, alias_index=alias_index
            )
            for raw in advanced:
                if isinstance(raw, Mapping):
                    canonical_raw = _canonical_advanced_row(
                        raw,
                        alias_index=alias_index,
                        allow_outside_membership=False,
                    )
                    if canonical_raw is None:
                        raise CFBAcquisitionError("CFB_ACQUISITION_CURRENT_TEAM_FILTERED_UNEXPECTEDLY")
                    metrics.append(normalize_advanced_team_metrics(
                        canonical_raw,
                        through_week=end_week,
                        feature_asof_ts=str(meta["retrieved_at_utc"]),
                        season_points=points,
                        sample_source="CURRENT_SEASON_PRIOR_WEEKS",
                    ).to_dict())
'''
    text = _replace_once(text, old_current, new_current, "current_metrics_identity")

    TARGET.write_text(text, encoding="utf-8")

    TEST.write_text('''from __future__ import annotations

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
''', encoding="utf-8")

    print(f"CFB_RECONSTRUCTED_IDENTITY_REPAIR_APPLIED sha256={_sha(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
