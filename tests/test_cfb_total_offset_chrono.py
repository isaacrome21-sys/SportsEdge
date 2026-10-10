import unittest
from scripts.research_cfb_total_offset_chrono import evaluate_chronological


def sample():
    return [
        {"game_id": f"{week}-{i}", "season": 2026, "week": week,
         "model_total": 50.0, "actual_total": 48.0 + i % 2,
         "closing_total": 44.0 + i % 2,
         "evidence_role": "RECONSTRUCTED_DEVELOPMENT"}
        for week in (2, 3, 4, 5, 6) for i in range(30)
    ]


class TotalsOffsetResearchTest(unittest.TestCase):
    def test_chronological_fit_ignores_closing_lines(self):
        rows = sample()
        first = evaluate_chronological(
            rows, train_through=(2026, 4), holdout_from=(2026, 5))
        self.assertEqual((first["train_n"], first["holdout_n"]), (90, 60))
        self.assertAlmostEqual(first["offset_points"], -1.5)
        self.assertAlmostEqual(first["holdout_adjusted"]["mae_points"], 0.5)
        self.assertFalse(first["calibration_applied_in_production"])
        self.assertFalse(first["positive_ev_proven"])
        for row in rows:
            row["closing_total"] = 110
        second = evaluate_chronological(
            rows, train_through=(2026, 4), holdout_from=(2026, 5))
        self.assertEqual(first["offset_points"], second["offset_points"])

    def test_overlap_blocks(self):
        with self.assertRaisesRegex(ValueError, "CHRONOLOGY"):
            evaluate_chronological(
                sample(), train_through=(2026, 5), holdout_from=(2026, 5))

    def test_duplicate_games_block(self):
        rows = sample()
        rows.append(dict(rows[0]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            evaluate_chronological(
                rows, train_through=(2026, 4), holdout_from=(2026, 5))

    def test_evidence_role_required(self):
        rows = sample()
        del rows[0]["evidence_role"]
        with self.assertRaisesRegex(ValueError, "EVIDENCE_ROLE"):
            evaluate_chronological(
                rows, train_through=(2026, 4), holdout_from=(2026, 5))

    def test_small_holdout_and_bad_offsets_block(self):
        with self.assertRaisesRegex(ValueError, "UNDERSIZED"):
            evaluate_chronological(
                sample()[:35], train_through=(2026, 4),
                holdout_from=(2026, 5))
        rows = sample()
        for row in rows:
            row["actual_total"] = 25.0
        with self.assertRaisesRegex(ValueError, "SUSPECT_MAGNITUDE"):
            evaluate_chronological(
                rows, train_through=(2026, 4), holdout_from=(2026, 5))


if __name__ == "__main__":
    unittest.main()
