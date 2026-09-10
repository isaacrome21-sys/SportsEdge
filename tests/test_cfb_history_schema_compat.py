from __future__ import annotations

import unittest

from sportsedge.sports.cfb.history_schema_compat import (
    REQUIRED_TEAM_METRICS,
    audit_cfb_history_schema_compat,
)


_CAPTURED_COLUMNS = {
    "schedules": {"home_score", "away_score"},
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
    "adv_drives": {"avg_field_position", "drives"},
}


class TestCFBHistorySchemaCompat(unittest.TestCase):
    def test_current_public_release_surface_fails_closed_on_missing_and_uncertified_inputs(self):
        report = audit_cfb_history_schema_compat(columns_by_dataset=_CAPTURED_COLUMNS)
        self.assertEqual(report.status, "SOURCE_SCHEMA_OR_SEMANTICS_INCOMPLETE")
        self.assertEqual(
            set(report.raw_source_fields_missing),
            {"eckel_rate", "points_per_eckel"},
        )
        self.assertIn("points_per_drive", report.candidate_source_coverage)
        self.assertIn("net_field_position", report.candidate_source_coverage)
        self.assertIn("explosive_rate", report.semantic_equivalence_unproven)
        self.assertFalse(report.point_in_time_proven)
        self.assertFalse(report.promotion_evidence)
        self.assertFalse(report.model_p_created)
        self.assertFalse(report.eligibility_changed)

    def test_opponent_join_fields_need_base_source_columns_and_remain_semantically_unproven(self):
        report = audit_cfb_history_schema_compat(columns_by_dataset=_CAPTURED_COLUMNS)
        for metric in (
            "def_ppa_rush_allowed",
            "def_ppa_dropback_allowed",
            "def_success_rate_allowed",
        ):
            self.assertIn(metric, report.candidate_source_coverage)
            self.assertIn(metric, report.semantic_equivalence_unproven)

    def test_missing_source_column_is_reported_not_imputed(self):
        columns = {key: set(value) for key, value in _CAPTURED_COLUMNS.items()}
        columns["adv_team"].remove("EPA_passing_per_play")
        report = audit_cfb_history_schema_compat(columns_by_dataset=columns)
        self.assertIn("off_ppa_dropback", report.raw_source_fields_missing)
        self.assertIn("def_ppa_dropback_allowed", report.raw_source_fields_missing)

    def test_semantic_certification_without_source_fails_closed(self):
        columns = {key: set(value) for key, value in _CAPTURED_COLUMNS.items()}
        columns["adv_team"].remove("EPA_passing_per_play")
        with self.assertRaisesRegex(ValueError, "CERTIFICATION_WITHOUT_SOURCE"):
            audit_cfb_history_schema_compat(
                columns_by_dataset=columns,
                semantic_equivalence_proven=("off_ppa_dropback",),
            )

    def test_unknown_semantic_certification_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_SEMANTIC_CERTIFICATION"):
            audit_cfb_history_schema_compat(
                columns_by_dataset=_CAPTURED_COLUMNS,
                semantic_equivalence_proven=("made_up_metric",),
            )

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
