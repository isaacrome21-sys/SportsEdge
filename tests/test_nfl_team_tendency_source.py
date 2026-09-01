from __future__ import annotations

import io
import unittest

from sportsedge.sports.nfl.team_tendency_source import (
    fetch_nflverse_team_stats,
    build_prior_team_tendency_providers,
)


class _Resp:
    def __init__(self, raw: bytes): self.raw = raw
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


CSV = b"""season,week,team,season_type,opponent_team,attempts,carries,sacks_suffered,passing_yards,rushing_yards,def_sacks,def_qb_hits,def_interceptions,penalties,penalty_yards\n2026,1,AAA,REG,BBB,30,25,2,240,110,3,5,1,6,55\n2026,1,BBB,REG,AAA,35,20,3,260,95,2,4,0,7,60\n2026,2,AAA,REG,CCC,40,20,1,310,85,4,6,2,5,40\n2026,2,CCC,REG,AAA,25,30,4,180,140,1,3,1,4,35\n2026,3,AAA,REG,DDD,99,1,0,999,1,9,9,9,1,1\n"""


class NFLTeamTendencyTests(unittest.TestCase):
    def test_fetch_uses_weekly_team_stats_release_and_hashes_exact_bytes(self):
        def opener(req, timeout=25):
            self.assertIn("stats_team_week_2026.csv", req.full_url)
            return _Resp(CSV)
        rows, uri, digest = fetch_nflverse_team_stats(season=2026, opener=opener)
        self.assertEqual(len(rows), 5)
        self.assertTrue(uri.endswith("stats_team_week_2026.csv"))
        self.assertEqual(len(digest), 64)

    def test_target_week_excluded_and_overall_pass_is_not_neutral_pass(self):
        rows, uri, digest = fetch_nflverse_team_stats(season=2026, opener=lambda req, timeout=25: _Resp(CSV))
        coaching, defensive = build_prior_team_tendency_providers(
            rows=rows,
            season=2026,
            target_week=3,
            home_team="AAA",
            away_team="BBB",
            source_uri=uri,
            source_sha256=digest,
        )
        teams = {row["team_id"]: row for row in coaching["payload"]["teams"]}
        aaa = teams["AAA"]
        self.assertEqual(aaa["sample_weeks"], [1, 2])
        self.assertAlmostEqual(aaa["overall_pass_rate"], 70.0 / 115.0)
        self.assertIsNone(aaa["neutral_pass_rate"])
        self.assertIsNone(aaa["early_down_pass_rate"])
        self.assertIsNone(aaa["pace_seconds_per_play"])

        defense_rows = {row["team_id"]: row for row in defensive["payload"]["teams"]}
        d_aaa = defense_rows["AAA"]
        # pass opportunities: BBB attempts 35 + AAA sacks 3, CCC attempts 25 + AAA sacks 4 = 67
        self.assertEqual(d_aaa["sample_plays"], 67)
        self.assertAlmostEqual(d_aaa["sack_rate"], 7.0 / 67.0)
        self.assertAlmostEqual(d_aaa["pressure_rate"], 18.0 / 67.0)
        self.assertIsNone(d_aaa["man_rate"])
        self.assertIsNone(d_aaa["zone_rate"])
        self.assertIsNone(d_aaa["blitz_rate"])


if __name__ == "__main__":
    unittest.main()
