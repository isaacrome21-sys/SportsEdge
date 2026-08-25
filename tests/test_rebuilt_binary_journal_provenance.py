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
        "readout_version": "v2",
        "engine_version": "state_engine_v2",
        "seed_policy": "identity_sha256_256bit",
        "mc_paths": 50000,
    }


class RebuiltBinaryJournalProvenanceTests(unittest.TestCase):
    def test_rebuilt_binary_requires_distribution_and_engine_identity(self):
        required = (
            "model_input_hash", "distribution_sha256", "readout_sha256",
            "readout_version", "engine_version", "seed_policy", "mc_paths",
        )
        for market in ("FIRST_HOME_RUN", "PITCHER_RECORD_WIN"):
            for field in required:
                row = _row(market)
                row.pop(field)
                with self.subTest(market=market, field=field):
                    with self.assertRaises(PredictionJournalError):
                        build_prediction_journal_record({**BASE, "results": [row]})

    def test_complete_rebuilt_binary_provenance_is_persisted(self):
        rows = [_row("FIRST_HOME_RUN"), _row("PITCHER_RECORD_WIN")]
        record = build_prediction_journal_record({**BASE, "results": rows})
        self.assertEqual(record["prediction_count"], 2)
        for row in record["predictions"]:
            self.assertEqual(row["distribution_sha256"], "2" * 64)
            self.assertEqual(row["readout_sha256"], "3" * 64)
            self.assertEqual(row["engine_version"], "state_engine_v2")
            self.assertEqual(row["seed_policy"], "identity_sha256_256bit")
            self.assertEqual(row["mc_paths"], 50000)


if __name__ == "__main__":
    unittest.main()
