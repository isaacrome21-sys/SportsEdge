import unittest

from sportsedge.prediction_journal import PredictionJournalError, build_prediction_journal_record


BASE = {
    "slate_date_ct": "2026-08-25",
    "generated_at_utc": "2026-08-25T12:00:00+00:00",
    "mode": "AUTO",
    "run_status": "SHADOW",
    "card_status": "PASS",
}


def _row(market):
    return {
        "game_id": "123",
        "market": market,
        "entity_id": "222",
        "line": 0.5,
        "side": "YES",
        "american_odds": 120,
        "model_p": 0.4,
        "bet_status": "PASS",
        "reason": "candidate",
        "model_input_hash": "1" * 64,
        "distribution_sha256": "2" * 64,
        "readout_sha256": "3" * 64,
        "readout_version": "v1",
    }


class RebuiltBinaryJournalProvenanceTests(unittest.TestCase):
    def test_first_home_run_requires_distribution_identity(self):
        row = _row("FIRST_HOME_RUN")
        row.pop("distribution_sha256")
        with self.assertRaises(PredictionJournalError):
            build_prediction_journal_record({**BASE, "results": [row]})

    def test_pitcher_record_win_requires_distribution_identity(self):
        row = _row("PITCHER_RECORD_WIN")
        row.pop("readout_sha256")
        with self.assertRaises(PredictionJournalError):
            build_prediction_journal_record({**BASE, "results": [row]})

    def test_complete_rebuilt_binary_provenance_is_persisted(self):
        rows = [_row("FIRST_HOME_RUN"), _row("PITCHER_RECORD_WIN")]
        record = build_prediction_journal_record({**BASE, "results": rows})
        self.assertEqual(record["prediction_count"], 2)
        for row in record["predictions"]:
            self.assertEqual(row["distribution_sha256"], "2" * 64)
            self.assertEqual(row["readout_sha256"], "3" * 64)


if __name__ == "__main__":
    unittest.main()
