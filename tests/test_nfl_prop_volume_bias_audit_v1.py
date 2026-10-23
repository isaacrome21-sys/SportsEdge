"""Adversarial receipts/semantics tests for research-only NFL prop bias audit."""
import math
import unittest

from sportsedge.research.nfl_prop_volume_bias_audit_v1 import (
    AUDIT_ID,
    audit_nfl_prop_volume_bias,
)


def row(**changes):
    base = {
        "sport": "NFL",
        "event_id": "CHI@NE-20261022",
        "player_id": "player-1",
        "market": "PASSING_YARDS",
        "event_start": "2026-10-22T19:15:00-05:00",
        "entry_captured_at": "2026-10-22T18:15:00-05:00",
        "quote_captured_at": "2026-10-22T18:13:01-05:00",
        "result_captured_at": "2026-10-22T23:00:00-05:00",
        "model_snapshot_id": "pregame-v1-original",
        "quote_id": "original-dk-quote-1",
        "result_receipt_id": "official-postgame-stats-1",
        "result_status": "FINAL",
        "projected_mean": 240,
        "line": 255.5,
        "actual": 308,
        "published_side": "UNDER",
    }
    base.update(changes)
    return base


class NFLPropVolumeAuditTests(unittest.TestCase):
    def test_signed_bias_is_distinct_from_direction_and_cluster(self):
        rows = [
            row(),
            row(player_id="player-2", market="RUSH_ATTEMPTS", projected_mean=12,
                line=10.5, actual=3, published_side="OVER", quote_id="original-dk-quote-2"),
            row(event_id="DAL@NYG-20261022", player_id="player-3",
                projected_mean=255.5, line=255.5, actual=299,
                published_side="NONE", quote_id="original-dk-quote-3"),
        ]
        result = audit_nfl_prop_volume_bias(rows)
        self.assertEqual(result["audit_id"], AUDIT_ID)
        self.assertEqual(result["overall"]["rows"], 3)
        self.assertEqual(result["overall"]["distinct_games"], 2)
        self.assertEqual(
            (result["overall"]["under"], result["overall"]["over"], result["overall"]["tie"]),
            (1, 1, 1),
        )
        self.assertEqual(result["game_clusters"]["CHI@NE-20261022"]["prop_rows"], 2)
        self.assertEqual(result["overall"]["direction_outcomes"]["UNDER"],
                         {"hit": 0, "loss": 1, "push": 0})
        self.assertEqual(result["overall"]["direction_outcomes"]["OVER"],
                         {"hit": 0, "loss": 1, "push": 0})
        # Passing yards and rush attempts have incompatible units.
        self.assertIsNone(result["overall"]["mean_model_minus_actual"])
        self.assertIsNone(result["overall"]["mean_model_minus_market"])
        self.assertEqual(result["overall"]["mean_error_scope"], "MIXED_MARKETS_NOT_COMPARABLE")
        self.assertAlmostEqual(result["by_market"]["PASSING_YARDS"]["mean_model_minus_actual"],
                               (-68 - 43.5) / 2)
        self.assertEqual(result["by_market"]["RUSH_ATTEMPTS"]["mean_model_minus_actual"], 9)
        self.assertEqual(result["by_market"]["PASSING_YARDS"]["mean_error_scope"], "PER_MARKET")
        self.assertFalse(result["overall"]["one_direction_warning"])
        self.assertFalse(result["forward_validation_counted"])
        self.assertFalse(result["model_p_authority"])
        self.assertFalse(result["play_authority"])

    def test_warning_requires_both_game_diversity_and_direction_skew(self):
        items = [
            row(event_id=f"game-{i // 4}", player_id=f"p-{i}",
                market="RECEIVING_YARDS", projected_mean=50 if i < 17 else 70,
                line=60.5, actual=61, published_side="NONE", quote_id=f"q-{i}")
            for i in range(20)
        ]
        self.assertTrue(audit_nfl_prop_volume_bias(items)["overall"]["one_direction_warning"])
        same_game = [{**item, "event_id": "game-0"} for item in items]
        self.assertFalse(audit_nfl_prop_volume_bias(same_game)["overall"]["one_direction_warning"])

    def test_row_identity_duplicate_fails_even_with_new_quote_id(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_PLAYER_GAME_MARKET"):
            audit_nfl_prop_volume_bias([row(), row(quote_id="different-quote")])

    def test_timestamp_timezone_and_capture_order(self):
        for overrides, reason in [
            ({"event_start": "2026-10-22T19:15:00"}, "EVENT_START_TIMEZONE_REQUIRED"),
            ({"entry_captured_at": "2026-10-22T18:15:00"}, "ENTRY_CAPTURED_AT_TIMEZONE_REQUIRED"),
            ({"quote_captured_at": "2026-10-22T18:13:01"}, "QUOTE_CAPTURED_AT_TIMEZONE_REQUIRED"),
            ({"entry_captured_at": "2026-10-22T19:15:00-05:00"}, "NOT_PROSPECTIVE_PREGAME_PAIR"),
            ({"quote_captured_at": "2026-10-22T18:15:01-05:00"}, "NOT_PROSPECTIVE_PREGAME_PAIR"),
            ({"quote_captured_at": "2026-10-22T18:11:59-05:00"}, "QUOTE_STALE_AT_ENTRY"),
        ]:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, reason):
                    audit_nfl_prop_volume_bias([row(**overrides)])

    def test_exact_180_seconds_and_z_offsets_are_accepted(self):
        entry = row(quote_captured_at="2026-10-22T23:12:00Z")
        result = audit_nfl_prop_volume_bias([entry])
        self.assertEqual(result["overall"]["rows"], 1)
        self.assertEqual(result["overall"]["mean_error_scope"], "PER_MARKET")
        self.assertEqual(result["overall"]["mean_model_minus_actual"], -68)

    def test_results_are_postgame_receipted_not_presented_as_pregame_facts(self):
        with self.assertRaisesRegex(ValueError, "RESULT_BEFORE_GAME_START"):
            audit_nfl_prop_volume_bias([row(result_captured_at="2026-10-22T18:16:00-05:00")])
        with self.assertRaisesRegex(ValueError, "RESULT_BEFORE_GAME_START"):
            audit_nfl_prop_volume_bias([row(result_captured_at="2026-10-22T19:15:00-05:00")])
        with self.assertRaisesRegex(ValueError, "RESULT_CAPTURED_AT_TIMEZONE_REQUIRED"):
            audit_nfl_prop_volume_bias([row(result_captured_at="2026-10-22T23:00:00")])
        with self.assertRaisesRegex(ValueError, "FINAL_RESULT_REQUIRED"):
            audit_nfl_prop_volume_bias([row(result_status="LIVE")])

    def test_one_game_id_must_have_consistent_kickoff_across_props(self):
        with self.assertRaisesRegex(ValueError, "CONFLICTING_GAME_START"):
            audit_nfl_prop_volume_bias([
                row(),
                row(player_id="player-2", quote_id="second-q",
                    event_start="2026-10-22T19:16:00-05:00"),
            ])
        # Equivalent timezone representations describe the same absolute event.
        valid = audit_nfl_prop_volume_bias([
            row(),
            row(player_id="player-2", quote_id="second-q",
                event_start="2026-10-23T00:15:00Z"),
        ])
        self.assertEqual(valid["overall"]["distinct_games"], 1)

    def test_nan_missing_bool_and_negative_results_fail_not_zero_fill(self):
        for field, invalid, reason in [
            ("actual", None, "ACTUAL_INVALID"),
            ("actual", math.nan, "ACTUAL_INVALID"),
            ("actual", -1, "ACTUAL_INVALID"),
            ("projected_mean", math.inf, "PROJECTED_MEAN_INVALID"),
            ("line", True, "MARKET_LINE_INVALID"),
            ("line", "not-a-line", "MARKET_LINE_INVALID"),
        ]:
            with self.subTest(field=field, invalid=invalid):
                with self.assertRaisesRegex(ValueError, reason):
                    audit_nfl_prop_volume_bias([row(**{field: invalid})])
        self.assertEqual(audit_nfl_prop_volume_bias([row(actual=0)])["overall"]["rows"], 1)

    def test_direction_mismatch_is_reported_but_never_corrected(self):
        result = audit_nfl_prop_volume_bias([row(published_side="OVER")])
        self.assertEqual(result["overall"]["under"], 1)
        self.assertEqual(result["overall"]["published_direction_mismatches"], 1)
        with self.assertRaisesRegex(ValueError, "PUBLISHED_SIDE_INVALID"):
            audit_nfl_prop_volume_bias([row(published_side="PLAY")])

    def test_hit_loss_push_counts_are_descriptive_not_bet_profit(self):
        items = [
            row(player_id="under-hit", projected_mean=240, line=250.5,
                actual=220, published_side="UNDER"),
            row(player_id="over-hit", projected_mean=260, line=250.5,
                actual=270, published_side="OVER"),
            row(player_id="under-push", projected_mean=240, line=250,
                actual=250, published_side="UNDER"),
            row(player_id="over-push", projected_mean=260, line=250,
                actual=250, published_side="OVER"),
        ]
        got = audit_nfl_prop_volume_bias(items)
        self.assertEqual(got["overall"]["direction_outcomes"]["UNDER"],
                         {"hit": 1, "loss": 0, "push": 1})
        self.assertEqual(got["overall"]["direction_outcomes"]["OVER"],
                         {"hit": 1, "loss": 0, "push": 1})
        self.assertFalse(got["play_authority"])

    def test_required_provenance_and_nfl_scope(self):
        for overrides, reason in [
            ({"sport": "NBA"}, "SPORT_MUST_BE_NFL"),
            ({"quote_id": ""}, "quote_id_REQUIRED"),
            ({"model_snapshot_id": ""}, "model_snapshot_id_REQUIRED"),
            ({"result_receipt_id": ""}, "result_receipt_id_REQUIRED"),
            ({"player_id": None}, "player_id_REQUIRED"),
        ]:
            with self.subTest(overrides=overrides):
                with self.assertRaisesRegex(ValueError, reason):
                    audit_nfl_prop_volume_bias([row(**overrides)])

    def test_empty_research_audit_never_becomes_a_play(self):
        result = audit_nfl_prop_volume_bias([])
        self.assertEqual(result["overall"]["rows"], 0)
        self.assertIsNone(result["overall"]["under_share"])
        self.assertIsNone(result["overall"]["mean_model_minus_actual"])
        self.assertEqual(result["overall"]["mean_error_scope"], "NO_ROWS")
        self.assertEqual(result["market_admission"], "NOT_VERIFIED")
        self.assertTrue(result["research_only"])


if __name__ == "__main__":
    unittest.main()
