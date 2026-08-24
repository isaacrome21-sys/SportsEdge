import unittest

from sportsedge.pit_prop_validation import (
    PITPropValidationError,
    analyze_pit_prop_rows,
    normalize_pit_row,
)


class PITPropValidationTests(unittest.TestCase):
    def _row(self, **changes):
        row = {
            "market": "PITCHER_OUTS",
            "game_id": "g1",
            "entity_id": "p1",
            "quote_ts": "2026-08-10T18:00:00-05:00",
            "first_pitch_ts": "2026-08-10T19:10:00-05:00",
            "line": 17.5,
            "side": "OVER",
            "realized_count": 19,
            "history_asof_ts": "2026-08-10T17:59:00-05:00",
            "history_source_hash": "a" * 64,
            "incumbent_p": 0.55,
            "challenger_p": 0.65,
        }
        row.update(changes)
        return row

    def test_accepts_strictly_pregame_row(self):
        row = normalize_pit_row(self._row())
        self.assertEqual(row.market, "PITCHER_OUTS")
        self.assertTrue(row.realized_win)
        self.assertFalse(row.realized_push)

    def test_rejects_post_first_pitch_quote(self):
        with self.assertRaisesRegex(PITPropValidationError, "quote_ts must be before"):
            normalize_pit_row(self._row(quote_ts="2026-08-10T19:11:00-05:00"))

    def test_rejects_post_first_pitch_history(self):
        with self.assertRaisesRegex(PITPropValidationError, "history_asof_ts must be before"):
            normalize_pit_row(self._row(history_asof_ts="2026-08-10T19:11:00-05:00"))

    def test_rejects_missing_or_fake_source_hash(self):
        with self.assertRaisesRegex(PITPropValidationError, "SHA-256"):
            normalize_pit_row(self._row(history_source_hash="not-a-hash"))

    def test_push_rows_are_not_scored_as_losses(self):
        report = analyze_pit_prop_rows([
            self._row(line=19.0, realized_count=19),
            self._row(game_id="g2", realized_count=20, incumbent_p=0.50, challenger_p=0.70),
        ])
        self.assertEqual(report["source_row_count"], 2)
        self.assertEqual(report["row_count"], 1)
        self.assertEqual(report["push_rows_excluded_from_binary_error"], 1)

    def test_all_pushes_fail_closed(self):
        with self.assertRaisesRegex(PITPropValidationError, "all PIT rows are pushes"):
            analyze_pit_prop_rows([self._row(line=19.0, realized_count=19)])

    def test_report_is_labeled_historical_only_after_contract_passes(self):
        report = analyze_pit_prop_rows([
            self._row(),
            self._row(game_id="g2", entity_id="p2", market="RBI", line=0.5,
                      realized_count=0, incumbent_p=0.60, challenger_p=0.45),
        ])
        self.assertEqual(report["evidence_class"], "HISTORICAL_PIT")
        self.assertEqual(report["markets"], ["PITCHER_OUTS", "RBI"])


if __name__ == "__main__":
    unittest.main()
