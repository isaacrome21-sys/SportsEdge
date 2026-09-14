import math
import unittest

from sportsedge.sports.nfl.v2k_drive_core import (
    AUTHORITY,
    DRIVE_OUTCOMES,
    FIELD_BUCKETS,
    OVERTIME_RULE_VERSION,
    STATE_BUCKETS,
    HierarchicalStrength,
    fit_hierarchical_strength,
    simulate_joint_game,
)
from sportsedge.sports.nfl.v2k_drive_source import build_drive_rows_from_pbp

MANIFEST = "a" * 64
CODE_SHA = "b" * 40


def play(game, drive, idx, offense, defense, result, *, order=None, start=75.0, before=(0, 0), after=(0, 0), period=1, clock=900, conversion=0):
    row = {
        "game_id": game, "season": 2024, "week": 1,
        "kickoff_utc": "2024-09-08T17:00:00Z", "drive_id": drive,
        "play_index": idx, "offense": offense, "defense": defense,
        "start_yardline_100": start, "drive_result": result,
        "offense_score_before": before[0], "defense_score_before": before[1],
        "offense_score_after": after[0], "defense_score_after": after[1],
        "period": period, "clock_seconds_remaining_period": clock,
        "conversion_points": conversion,
    }
    if order is not None:
        row["drive_order"] = order
    return row


def training_rows():
    records = []
    order = 0
    # Synthetic chronology is monotone within each game. A has the largest and
    # strongest sample; B is deliberately smaller/weaker for shrinkage testing.
    for i in range(12):
        td = i < 8
        result = "touchdown" if td else "punt"
        conv = 2 if i == 0 else (1 if td else 0)
        period = i // 3 + 1
        clock = 900 - (i % 3) * 300
        before = (14, 14) if i == 11 else (0, 0)
        after = (14, 14) if i == 11 else ((6 + conv) if td else 0, 0)
        records.append(play("G1", f"A{i}", order, "A", "B", result, order=order,
                            start=25.0 if i % 3 == 0 else 75.0, before=before, after=after,
                            period=period, clock=clock, conversion=conv))
        order += 1
    for i in range(3):
        td = i == 0
        result = "touchdown" if td else "punt"
        period, clock = ((1, 900), (3, 500), (4, 180))[i]
        before = (10, 17) if i == 2 else (0, 0)
        after = (10, 17) if i == 2 else (7 if td else 0, 0)
        records.append(play("G2", f"B{i}", order, "B", "A", result, order=order,
                            start=50.0, before=before, after=after, period=period, clock=clock,
                            conversion=1 if td else 0))
        order += 1
    for i in range(8):
        fg = i < 2
        result = "field_goal" if fg else "punt"
        period = i // 2 + 1
        clock = 900 if i % 2 == 0 else 300
        before = (17, 14) if i == 7 else (0, 0)
        after = (17, 14) if i == 7 else (3 if fg else 0, 0)
        records.append(play("G3", f"C{i}", order, "C", "A", result, order=order,
                            start=60.0, before=before, after=after, period=period, clock=clock))
        order += 1
    return build_drive_rows_from_pbp(records, source_manifest_sha256=MANIFEST, source_code_sha=CODE_SHA)


class TestNFLV2KAttempt0Core(unittest.TestCase):
    def test_source_adapter_is_deterministic_and_bound(self):
        records = [
            play("G", "d2", 20, "B", "A", "field_goal", order=2, before=(0, 7), after=(3, 7), clock=500),
            play("G", "d1", 10, "A", "B", "touchdown", order=1, before=(0, 0), after=(7, 0), conversion=1, clock=900),
        ]
        rows = build_drive_rows_from_pbp(records, source_manifest_sha256=MANIFEST, source_code_sha=CODE_SHA)
        self.assertEqual([r.drive_index for r in rows], [0, 1])
        self.assertEqual([r.offense for r in rows], ["A", "B"])
        self.assertTrue(all(r.source_manifest_sha256 == MANIFEST for r in rows))
        self.assertTrue(all(r.source_code_sha == CODE_SHA for r in rows))

    def test_market_field_fails_closed(self):
        r = play("G", "d1", 1, "A", "B", "punt")
        r["closing_spread"] = -3.0
        with self.assertRaisesRegex(ValueError, "V2K_MARKET_FIELD_FORBIDDEN"):
            build_drive_rows_from_pbp([r], source_manifest_sha256=MANIFEST, source_code_sha=CODE_SHA)

    def test_unknown_outcome_duplicate_play_and_clock_regression_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "V2K_DRIVE_OUTCOME_UNMAPPED"):
            build_drive_rows_from_pbp([play("G", "d1", 1, "A", "B", "mystery")], source_manifest_sha256=MANIFEST, source_code_sha=CODE_SHA)
        dup = [play("G", "d1", 1, "A", "B", "punt"), play("G", "d1", 1, "A", "B", "punt")]
        with self.assertRaisesRegex(ValueError, "V2K_PLAY_INDEX_DUPLICATE"):
            build_drive_rows_from_pbp(dup, source_manifest_sha256=MANIFEST, source_code_sha=CODE_SHA)
        bad_clock = [
            play("G", "d1", 1, "A", "B", "punt", order=1, period=1, clock=300),
            play("G", "d2", 2, "B", "A", "punt", order=2, period=1, clock=600),
        ]
        with self.assertRaisesRegex(ValueError, "V2K_CLOCK_REGRESSION"):
            build_drive_rows_from_pbp(bad_clock, source_manifest_sha256=MANIFEST, source_code_sha=CODE_SHA)

    def test_hierarchical_probabilities_are_finite_normalized_and_unknown_strength_is_neutral(self):
        model = fit_hierarchical_strength(training_rows())
        probs = model.probabilities("A", "B", start_yardline_100=50.0, state_bucket="NORMAL")
        self.assertAlmostEqual(sum(probs.values()), 1.0, places=12)
        self.assertTrue(all(math.isfinite(v) and v >= 0 for v in probs.values()))
        self.assertNotIn("UNKNOWN_O", model.offense_effect)
        self.assertNotIn("UNKNOWN_D", model.defense_effect)
        unknown = model.probabilities("UNKNOWN_O", "UNKNOWN_D", start_yardline_100=50.0, state_bucket="NORMAL")
        expected_raw = {o: max(0.0, model.league_baseline[o] + model.state_effect["NORMAL"][o] + model.field_effect["MID_FIELD"][o]) for o in DRIVE_OUTCOMES}
        z = sum(expected_raw.values())
        for outcome in DRIVE_OUTCOMES:
            self.assertAlmostEqual(unknown[outcome], expected_raw[outcome] / z, places=12)

    def test_small_sample_shrinks_at_least_as_much_as_large_sample(self):
        model = fit_hierarchical_strength(training_rows())
        self.assertGreaterEqual(model.shrinkage_weight["A"], model.shrinkage_weight["B"])

    def test_conversion_field_position_possession_and_state_are_training_derived(self):
        rows = training_rows()
        model = fit_hierarchical_strength(rows)
        td = [r for r in rows if r.outcome == "TD"]
        for points in (0, 1, 2):
            self.assertAlmostEqual(model.conversion_probabilities[points], sum(r.conversion_points == points for r in td) / len(td))
        self.assertEqual(model.start_field_positions, tuple(r.start_yardline_100 for r in rows))
        self.assertEqual(sorted(model.regulation_drive_counts), [3, 8, 12])
        self.assertEqual(set(model.state_effect), set(STATE_BUCKETS))
        self.assertEqual(set(model.field_effect), set(FIELD_BUCKETS))

    def test_joint_simulation_is_deterministic_stateful_and_coherent(self):
        model = fit_hierarchical_strength(training_rows())
        a = simulate_joint_game(model, "A", "B", seed=20260914, regulation_drives=12, max_overtime_drives=4)
        b = simulate_joint_game(model, "A", "B", seed=20260914, regulation_drives=12, max_overtime_drives=4)
        self.assertEqual(a, b)
        self.assertEqual(a.margin, a.home_score - a.away_score)
        self.assertEqual(a.total, a.home_score + a.away_score)
        self.assertEqual(a.team_totals["A"], a.home_score)
        self.assertEqual(a.team_totals["B"], a.away_score)
        for left, right in zip(a.path, a.path[1:]):
            self.assertEqual(left["defense"], right["offense"])
        self.assertTrue(all(0.0 <= p["start_yardline_100"] <= 100.0 for p in a.path))

    def test_empirical_possession_count_is_deterministic_under_seed(self):
        model = fit_hierarchical_strength(training_rows())
        self.assertEqual(
            simulate_joint_game(model, "A", "B", seed=11, max_overtime_drives=2),
            simulate_joint_game(model, "A", "B", seed=11, max_overtime_drives=2),
        )

    def test_2025_regular_season_overtime_gives_both_teams_initial_possession(self):
        baseline = {o: 0.0 for o in DRIVE_OUTCOMES}
        baseline["PUNT_OTHER"] = 1.0
        zero = {o: 0.0 for o in DRIVE_OUTCOMES}
        model = HierarchicalStrength(
            league_baseline=baseline, offense_effect={}, defense_effect={}, shrinkage_weight={},
            state_effect={s: dict(zero) for s in STATE_BUCKETS}, field_effect={f: dict(zero) for f in FIELD_BUCKETS},
            conversion_probabilities={0: 1.0, 1: 0.0, 2: 0.0}, start_field_positions=(75.0,),
            regulation_drive_counts=(4,), exceptional_score_points=(),
        )
        result = simulate_joint_game(model, "A", "B", seed=7, regulation_drives=4, max_overtime_drives=2, opening_possession="A")
        self.assertEqual(len(result.path), 6)
        self.assertTrue(result.path[-1]["overtime"] and result.path[-2]["overtime"])
        self.assertEqual(result.path[-1]["overtime_rule_version"], OVERTIME_RULE_VERSION)
        self.assertEqual(result.home_score, result.away_score)

    def test_attempt_zero_has_literal_zero_downstream_authority(self):
        self.assertTrue(AUTHORITY)
        for value in AUTHORITY.values():
            self.assertIs(value, False)

    def test_no_historical_evaluation_surface_is_imported(self):
        import sportsedge.sports.nfl.v2k_drive_core as core
        forbidden = {"calibration_slope", "signed_key_rmse", "evaluate_candidate", "run_walk_forward"}
        self.assertFalse(set(vars(core)).intersection(forbidden))


if __name__ == "__main__":
    unittest.main()
