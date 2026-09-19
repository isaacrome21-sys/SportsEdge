from __future__ import annotations

import unittest

from sportsedge.sports.cfb.prop_participation_model import fit_cfb_participation_model
from sportsedge.sports.cfb.prop_state_allocator import (
    CFBPropStateAllocatorError,
    allocate_cfb_player_opportunity,
)

SOURCE_SHA = "a" * 64


def _training_row(index: int, *, group: str, quarter: int, clock: int, margin: float, starter: bool):
    return {
        "game_id": f"g-{group}-{index // 12}",
        "season": 2025,
        "week": 1 + index // 24,
        "event_ts": f"2025-09-{1 + index // 24:02d}T18:{index % 60:02d}:00+00:00",
        "position_group": group,
        "starter_on_play": starter,
        "quarter": quarter,
        "clock_seconds_remaining": clock,
        "score_margin": margin,
        "source_sha256": SOURCE_SHA,
    }


def _group_training_rows(group: str):
    rows = []
    i = 0
    for _ in range(36):
        rows.append(_training_row(i, group=group, quarter=2, clock=450, margin=3, starter=True)); i += 1
    for _ in range(4):
        rows.append(_training_row(i, group=group, quarter=2, clock=450, margin=3, starter=False)); i += 1
    for _ in range(8):
        rows.append(_training_row(i, group=group, quarter=4, clock=300, margin=28, starter=True)); i += 1
    for _ in range(32):
        rows.append(_training_row(i, group=group, quarter=4, clock=300, margin=28, starter=False)); i += 1
    return rows


def _artifact():
    rows = []
    for group in ("QB", "RB", "WR", "TE"):
        rows.extend(_group_training_rows(group))
    return fit_cfb_participation_model(rows, min_rows_per_group=30)


def _players():
    return [
        {
            "player_id": "qb1", "position_group": "QB", "starter": True,
            "baseline_rush_share": 0.22, "baseline_target_share": 0.00,
            "baseline_red_zone_share": 0.24, "source_sha256": SOURCE_SHA,
        },
        {
            "player_id": "qb2", "position_group": "QB", "starter": False,
            "baseline_rush_share": 0.08, "baseline_target_share": 0.00,
            "baseline_red_zone_share": 0.06, "source_sha256": SOURCE_SHA,
        },
        {
            "player_id": "rb1", "position_group": "RB", "starter": True,
            "baseline_rush_share": 0.46, "baseline_target_share": 0.12,
            "baseline_red_zone_share": 0.42, "source_sha256": SOURCE_SHA,
        },
        {
            "player_id": "rb2", "position_group": "RB", "starter": False,
            "baseline_rush_share": 0.14, "baseline_target_share": 0.05,
            "baseline_red_zone_share": 0.12, "source_sha256": SOURCE_SHA,
        },
        {
            "player_id": "wr1", "position_group": "WR", "starter": True,
            "baseline_rush_share": 0.03, "baseline_target_share": 0.28,
            "baseline_red_zone_share": 0.09, "source_sha256": SOURCE_SHA,
        },
        {
            "player_id": "wr2", "position_group": "WR", "starter": False,
            "baseline_rush_share": 0.01, "baseline_target_share": 0.10,
            "baseline_red_zone_share": 0.04, "source_sha256": SOURCE_SHA,
        },
        {
            "player_id": "te1", "position_group": "TE", "starter": True,
            "baseline_rush_share": 0.00, "baseline_target_share": 0.15,
            "baseline_red_zone_share": 0.12, "source_sha256": SOURCE_SHA,
        },
        {
            "player_id": "te2", "position_group": "TE", "starter": False,
            "baseline_rush_share": 0.00, "baseline_target_share": 0.05,
            "baseline_red_zone_share": 0.04, "source_sha256": SOURCE_SHA,
        },
    ]


class CFBPropStateAllocatorTests(unittest.TestCase):
    def test_deterministic_and_zero_authority(self):
        artifact = _artifact()
        first = allocate_cfb_player_opportunity(
            artifact, _players(), quarter=4, clock_seconds_remaining=300,
            score_margin=28, yards_to_endzone=15,
        )
        second = allocate_cfb_player_opportunity(
            artifact, _players(), quarter=4, clock_seconds_remaining=300,
            score_margin=28, yards_to_endzone=15,
        )
        self.assertEqual(first, second)
        self.assertFalse(first["market_inputs_consumed"])
        self.assertFalse(first["promotion_authority"])
        self.assertFalse(first["activation_authority"])
        self.assertFalse(first["official_authority"])
        self.assertEqual(first["validation_status"], "UNVALIDATED_CANDIDATE")

    def test_blowout_moves_opportunity_from_starters_to_backups(self):
        artifact = _artifact()
        competitive = allocate_cfb_player_opportunity(
            artifact, _players(), quarter=2, clock_seconds_remaining=450,
            score_margin=3, yards_to_endzone=50,
        )
        blowout = allocate_cfb_player_opportunity(
            artifact, _players(), quarter=4, clock_seconds_remaining=300,
            score_margin=28, yards_to_endzone=50,
        )
        comp = {row["player_id"]: row for row in competitive["players"]}
        blow = {row["player_id"]: row for row in blowout["players"]}
        self.assertGreater(comp["qb1"]["rush_share"], blow["qb1"]["rush_share"])
        self.assertLess(comp["qb2"]["rush_share"], blow["qb2"]["rush_share"])
        self.assertGreater(comp["wr1"]["target_share"], blow["wr1"]["target_share"])
        self.assertLess(comp["wr2"]["target_share"], blow["wr2"]["target_share"])

    def test_mass_is_conserved_within_each_position_group(self):
        artifact = _artifact()
        result = allocate_cfb_player_opportunity(
            artifact, _players(), quarter=4, clock_seconds_remaining=180,
            score_margin=28, yards_to_endzone=12,
        )
        before = _players()
        after = result["players"]
        mapping = {
            "rush_share": "baseline_rush_share",
            "target_share": "baseline_target_share",
            "red_zone_share": "baseline_red_zone_share",
        }
        for group in ("QB", "RB", "WR", "TE"):
            for after_key, before_key in mapping.items():
                expected = sum(row[before_key] for row in before if row["position_group"] == group)
                actual = sum(row[after_key] for row in after if row["position_group"] == group)
                self.assertAlmostEqual(expected, actual, places=12)

    def test_market_contamination_fails_closed(self):
        players = _players()
        players[0]["spread"] = -28.5
        with self.assertRaisesRegex(
            CFBPropStateAllocatorError,
            "CFB_PROP_STATE_PLAYER_FIELD_FORBIDDEN:spread",
        ):
            allocate_cfb_player_opportunity(
                _artifact(), players, quarter=2, clock_seconds_remaining=300,
                score_margin=7, yards_to_endzone=40,
            )

    def test_missing_backup_share_fails_closed_when_mass_vacates(self):
        players = _players()
        players[1]["baseline_rush_share"] = 0.0
        with self.assertRaisesRegex(
            CFBPropStateAllocatorError,
            "CFB_PROP_STATE_BACKUP_SHARE_REQUIRED:QB:rush_share",
        ):
            allocate_cfb_player_opportunity(
                _artifact(), players, quarter=4, clock_seconds_remaining=120,
                score_margin=35, yards_to_endzone=40,
            )


if __name__ == "__main__":
    unittest.main()
