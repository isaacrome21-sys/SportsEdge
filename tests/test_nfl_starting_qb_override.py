import unittest

from scripts.run_nfl_production_validation import (
    apply_pinned_starting_qb_overrides,
    audit_starting_qb_coverage,
)


class NFLStartingQBOverrideTests(unittest.TestCase):
    def _schedule(self):
        return [
            {
                "game_id": "2018_01_TB_NO",
                "season": 2018,
                "week": 1,
                "game_type": "REG",
                "game_start_ts": "2018-09-09T13:00:00-04:00",
                "away_team": "TB",
                "home_team": "NO",
            },
            {
                "game_id": "2018_02_PHI_TB",
                "season": 2018,
                "week": 2,
                "game_type": "REG",
                "game_start_ts": "2018-09-16T13:00:00-04:00",
                "away_team": "PHI",
                "home_team": "TB",
            },
        ]

    def _opponent_depth(self):
        return [
            {
                "season": "2018",
                "club_code": "NO",
                "week": "1",
                "game_type": "REG",
                "depth_team": "1",
                "position": "QB",
                "gsis_id": "00-TEST-NO",
            },
            {
                "season": "2018",
                "club_code": "PHI",
                "week": "1",
                "game_type": "REG",
                "depth_team": "1",
                "position": "QB",
                "gsis_id": "00-TEST-PHI",
            },
        ]

    def _payload(self, **changes):
        row = {
            "game_id": "2018_01_TB_NO",
            "season": 2018,
            "week": 1,
            "team": "TB",
            "gsis_id": "00-0023682",
            "source_uri": "https://www.buccaneers.com/news/ryan-fitzpatrick-takes-over-first-team-offense",
            "source_published_ts": "2018-07-26T13:52:00-04:00",
            "identity_source_uri": "https://nflreadr.nflverse.com/",
            "reason": "NFLVERSE_WEEKLY_DEPTH_RANK_ONE_GAP",
        }
        row.update(changes)
        return {
            "schema_version": 1,
            "sport": "nfl",
            "contract": "PINNED_PREGAME_OFFICIAL_STARTER_OVERRIDE_V1",
            "overrides": [row],
        }

    def test_one_pregame_week_one_override_resolves_week_one_and_week_two(self):
        base_depth = self._opponent_depth()
        before = audit_starting_qb_coverage(self._schedule(), base_depth, eligible_seasons=[2018])
        self.assertEqual([(row["team"], row["week"]) for row in before], [("TB", 1), ("TB", 2)])

        depth, applied = apply_pinned_starting_qb_overrides(self._schedule(), base_depth, self._payload())
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["gsis_id"], "00-0023682")
        self.assertEqual(depth[-1]["depth_team"], "1")

        after = audit_starting_qb_coverage(self._schedule(), depth, eligible_seasons=[2018])
        self.assertEqual(after, [])

    def test_override_must_be_strictly_pregame(self):
        with self.assertRaisesRegex(ValueError, "NFL_STARTER_OVERRIDE_NOT_PREGAME"):
            apply_pinned_starting_qb_overrides(
                self._schedule(),
                [],
                self._payload(source_published_ts="2018-09-09T13:00:00-04:00"),
            )

    def test_existing_rank_one_depth_row_cannot_be_overwritten(self):
        depth = [{
            "season": "2018",
            "club_code": "TB",
            "week": "1",
            "game_type": "REG",
            "depth_team": "1",
            "position": "QB",
            "gsis_id": "00-0099999",
        }]
        with self.assertRaisesRegex(ValueError, "NFL_STARTER_OVERRIDE_NOT_NEEDED"):
            apply_pinned_starting_qb_overrides(self._schedule(), depth, self._payload())

    def test_ambiguous_upstream_evidence_cannot_be_repaired_by_override(self):
        depth = [
            {
                "season": "2018",
                "club_code": "TB",
                "week": "1",
                "game_type": "REG",
                "depth_team": "1",
                "position": "QB",
                "gsis_id": "00-0099998",
            },
            {
                "season": "2018",
                "club_code": "TB",
                "week": "1",
                "game_type": "REG",
                "depth_team": "1",
                "position": "QB",
                "gsis_id": "00-0099999",
            },
        ]
        with self.assertRaisesRegex(ValueError, "NFL_STARTER_OVERRIDE_REQUIRES_MISSING"):
            apply_pinned_starting_qb_overrides(self._schedule(), depth, self._payload())

    def test_schedule_identity_must_match_exactly(self):
        with self.assertRaisesRegex(ValueError, "NFL_STARTER_OVERRIDE_SCHEDULE_MISMATCH"):
            apply_pinned_starting_qb_overrides(self._schedule(), [], self._payload(week=2))


if __name__ == "__main__":
    unittest.main()
