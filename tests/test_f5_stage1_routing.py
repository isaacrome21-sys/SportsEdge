import unittest

from sportsedge.engine_registry import engine_registry, resolve_manual_market_type
from sportsedge.prediction_journal import PredictionJournalError, build_prediction_journal_record


F5_MARKETS = {"F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"}


class F5Stage1RoutingTests(unittest.TestCase):
    def test_all_f5_markets_share_one_engine_session(self):
        registry = engine_registry()
        engines = [registry[market] for market in sorted(F5_MARKETS)]
        self.assertTrue(all(engine is engines[0] for engine in engines))

    def test_manual_alias_includes_f5_team_total(self):
        self.assertEqual(resolve_manual_market_type("FIRST_FIVE_TEAM_TOTAL"), "F5_TEAM_TOTALS")

    def _payload(self, row):
        return {
            "slate_date_ct": "2026-08-25",
            "generated_at_utc": "2026-08-25T12:00:00+00:00",
            "mode": "AUTO",
            "run_status": "READY",
            "card_status": "NO_BETS",
            "results": [row],
        }

    def test_f5_modeled_row_requires_distribution_provenance(self):
        row = {
            "game_id": "1",
            "market": "F5_TOTALS",
            "entity_id": "1",
            "line": 4.5,
            "side": "OVER",
            "american_odds": -110,
            "model_p": 0.51,
            "bet_status": "PASS",
        }
        with self.assertRaises(PredictionJournalError):
            build_prediction_journal_record(self._payload(row))

    def test_f5_modeled_row_persists_complete_distribution_provenance(self):
        row = {
            "game_id": "1",
            "market": "F5_TOTALS",
            "entity_id": "1",
            "line": 4.5,
            "side": "OVER",
            "american_odds": -110,
            "model_p": 0.51,
            "bet_status": "PASS",
            "model_input_hash": "a" * 64,
            "distribution_sha256": "b" * 64,
            "readout_sha256": "c" * 64,
            "readout_version": "mlb_f5_readout_v1",
        }
        record = build_prediction_journal_record(self._payload(row))
        self.assertIsNotNone(record)
        prediction = record["predictions"][0]
        self.assertEqual(prediction["distribution_sha256"], "b" * 64)
        self.assertEqual(prediction["readout_sha256"], "c" * 64)


if __name__ == "__main__":
    unittest.main()
