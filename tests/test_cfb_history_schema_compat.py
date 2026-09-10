from __future__ import annotations

import unittest

from sportsedge.sports.cfb.history_schema_compat import (
    REQUIRED_TEAM_METRICS,
    audit_cfb_history_schema_compat,
)


_CAPTURED_COLUMNS = {
    "adv_team": {
        "EPA_rushing_per_play",
        "EPA_passing_per_play",
        "EPA_explosive_rate",
    },
    "adv_situational": {
        "EPA_success_rate",
        "EPA_standard_down_per_play",
        "EPA_success_passing_down_rate",
    },
    "adv_drives": {"avg_field_position"},
}


class TestCFBHistorySchemaCompat(unittest.TestCase):
    def test_current_public_release_surface_fails_closed_on_missing_frozen_inputs(self):
        report = audit_cfb_history_schema_compat(columns_by_dataset=_CAPTURED_COLUMNS)
        self.assertEqual(report.status, "SOURCE_SCHEMA_INCOMPLETE")
        self.assertEqual(
            set(report.missing_required_metrics),
            {"eckel_rate", "points_per_eckel", "points_per_drive"},
        )
        self.assertFalse(report.point_in_time_proven)
        self.assertFalse(report.promotion_evidence)
        self.assertFalse(report.model_p_created)
        self.assertFalse(report.eligibility_changed)

    def test_opponent_join_fields_are_derivable_only_when_base_source_columns_exist(self):
        report = audit_cfb_history_schema_compat(columns_by_dataset=_CAPTURED_COLUMNS)
        for metric in (
            "def_ppa_rush_allowed",
            "def_ppa_dropback_allowed",
            "def_success_rate_allowed",
        ):
            self.assertIn(metric, report.directly_or_opponent_derivable)

    def test_missing_source_column_is_reported_not_imputed(self):
        columns = {key: set(value) for key, value in _CAPTURED_COLUMNS.items()}
        columns["adv_team"].remove("EPA_passing_per_play")
        report = audit_cfb_history_schema_compat(columns_by_dataset=columns)
        self.assertIn("off_ppa_dropback", report.missing_required_metrics)
        self.assertIn("def_ppa_dropback_allowed", report.missing_required_metrics)

    def test_required_contract_does_not_silently_shrink(self):
        self.assertEqual(len(REQUIRED_TEAM_METRICS), 13)
        self.assertIn("points_per_eckel", REQUIRED_TEAM_METRICS)
        self.assertIn("points_per_drive", REQUIRED_TEAM_METRICS)

    def test_pit_flag_does_not_turn_schema_audit_into_promotion_evidence(self):
        report = audit_cfb_history_schema_compat(
            columns_by_dataset=_CAPTURED_COLUMNS,
            point_in_time_proven=True,
        )
        self.assertTrue(report.point_in_time_proven)
        self.assertFalse(report.promotion_evidence)

    def test_pit_flag_requires_real_boolean(self):
        with self.assertRaisesRegex(ValueError, "PIT_BOOL_REQUIRED"):
            audit_cfb_history_schema_compat(
                columns_by_dataset=_CAPTURED_COLUMNS,
                point_in_time_proven=1,
            )


if __name__ == "__main__":
    unittest.main()
