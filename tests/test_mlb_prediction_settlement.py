import copy
from pathlib import Path
import tempfile
import unittest

from sportsedge.mlb_prediction_settlement import (
    MLBPredictionSettlementError,
    build_game_prediction_settlement_record,
    prediction_journal_sha256,
    write_game_prediction_settlement,
)
from sportsedge.mlb_settlement_evidence import build_settlement_report
from sportsedge.prediction_journal import build_prediction_journal_record


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
GAME_ID = "822696"


def _prediction(
    market,
    *,
    side,
    line,
    status="PASS",
    readout_sha=SHA_C,
    model_p=0.55,
):
    return {
        "source_index": 0,
        "game_id": GAME_ID,
        "market": market,
        "entity_id": GAME_ID,
        "line": line,
        "side": side,
        "american_odds": -110,
        "model_p": model_p,
        "bet_status": status,
        "reason": "TEST_DECISION",
        "model_input_hash": SHA_A,
        "distribution_sha256": SHA_B,
        "readout_sha256": readout_sha,
        "readout_version": "mlb_v7_game_readout_v1",
    }


def _journal(*rows):
    record = build_prediction_journal_record(
        {
            "mode": "AUTOMATIC",
            "slate_date_ct": "2026-08-25",
            "generated_at_utc": "2026-08-25T10:00:00+00:00",
            "run_status": "PASS",
            "card_status": "PASS",
            "results": list(rows),
        }
    )
    assert record is not None
    return record


def _rule_evidence():
    return {
        "FULL_GAME_FINAL_SCORE_SETTLEMENT": {
            "status": "VALIDATED",
            "sportsbook": "DraftKings",
            "source_sha256": SHA_F,
            "captured_at_utc": "2026-08-25T10:30:00+00:00",
            "source_locator": "fixture://draftkings/full-game-final-score",
        }
    }


def _facts(*, away_runs=3, home_runs=5):
    return {
        "game_pk": GAME_ID,
        "status": "Final",
        "source": "MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED",
        "game": {
            "away_runs": away_runs,
            "home_runs": home_runs,
            "run_diff_home": home_runs - away_runs,
            "total_runs": away_runs + home_runs,
        },
    }


def _report(*, rules=True, evidence_class="LIVE_OFFICIAL_FACT_PROBE", away_runs=3, home_runs=5):
    return build_settlement_report(
        _facts(away_runs=away_runs, home_runs=home_runs),
        source="MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED",
        evidence_class=evidence_class,
        generated_at_utc="2026-08-25T10:45:00+00:00",
        book_rule_evidence=_rule_evidence() if rules else None,
    )


class MLBPredictionSettlementTests(unittest.TestCase):
    def test_resolves_win_loss_push_from_one_final_score(self):
        journal = _journal(
            _prediction("MONEYLINE", side="HOME", line=None, readout_sha=SHA_C),
            _prediction("RUN_LINE", side="AWAY_RL", line=1.5, readout_sha=SHA_D),
            _prediction("TOTALS", side="OVER", line=8.0, readout_sha=SHA_E),
        )
        record = build_game_prediction_settlement_record(
            journal,
            settlement_reports_by_game={GAME_ID: _report()},
            settled_at_utc="2026-08-25T11:00:00+00:00",
            expected_prediction_journal_sha256=prediction_journal_sha256(journal),
        )
        self.assertIsNotNone(record)
        self.assertEqual(
            [row["settlement_result"] for row in record["outcomes"]],
            ["WIN", "LOSS", "PUSH"],
        )
        self.assertEqual(record["win_count"], 1)
        self.assertEqual(record["loss_count"], 1)
        self.assertEqual(record["push_count"], 1)
        self.assertEqual(record["resolved_count"], 3)
        self.assertEqual(record["unresolved_count"], 0)
        self.assertTrue(record["settlement_complete"])
        self.assertTrue(all(row["away_runs"] == 3 for row in record["outcomes"]))
        self.assertTrue(all(row["home_runs"] == 5 for row in record["outcomes"]))

    def test_pass_prediction_is_settled_for_calibration_evidence(self):
        journal = _journal(_prediction("MONEYLINE", side="HOME", line=None, status="PASS"))
        record = build_game_prediction_settlement_record(
            journal,
            settlement_reports_by_game={GAME_ID: _report()},
            settled_at_utc="2026-08-25T11:00:00+00:00",
        )
        self.assertEqual(record["outcomes"][0]["bet_status"], "PASS")
        self.assertEqual(record["outcomes"][0]["settlement_result"], "WIN")

    def test_missing_book_rule_stays_unresolved(self):
        journal = _journal(_prediction("MONEYLINE", side="HOME", line=None))
        record = build_game_prediction_settlement_record(
            journal,
            settlement_reports_by_game={GAME_ID: _report(rules=False)},
            settled_at_utc="2026-08-25T11:00:00+00:00",
        )
        outcome = record["outcomes"][0]
        self.assertEqual(outcome["settlement_result"], "UNRESOLVED")
        self.assertEqual(outcome["settlement_reason"], "BOOK_SETTLEMENT_UNVALIDATED")
        self.assertIsNone(outcome["away_runs"])
        self.assertIsNone(outcome["home_runs"])
        self.assertFalse(record["settlement_complete"])

    def test_synthetic_settlement_evidence_cannot_resolve_prediction(self):
        journal = _journal(_prediction("TOTALS", side="OVER", line=7.5))
        record = build_game_prediction_settlement_record(
            journal,
            settlement_reports_by_game={
                GAME_ID: _report(evidence_class="SYNTHETIC_CONTRACT_TEST")
            },
            settled_at_utc="2026-08-25T11:00:00+00:00",
        )
        outcome = record["outcomes"][0]
        self.assertEqual(outcome["settlement_result"], "UNRESOLVED")
        self.assertEqual(
            outcome["settlement_reason"],
            "SYNTHETIC_SETTLEMENT_EVIDENCE_PROHIBITED",
        )

    def test_tampered_official_facts_hash_stays_unresolved(self):
        journal = _journal(_prediction("TOTALS", side="OVER", line=7.5))
        report = _report()
        report["facts"]["game"]["home_runs"] = 99
        record = build_game_prediction_settlement_record(
            journal,
            settlement_reports_by_game={GAME_ID: report},
            settled_at_utc="2026-08-25T11:00:00+00:00",
        )
        outcome = record["outcomes"][0]
        self.assertEqual(outcome["settlement_result"], "UNRESOLVED")
        self.assertEqual(outcome["settlement_reason"], "SETTLEMENT_FACTS_HASH_MISMATCH")

    def test_missing_game_report_stays_unresolved(self):
        journal = _journal(_prediction("RUN_LINE", side="HOME_RL", line=-1.5))
        record = build_game_prediction_settlement_record(
            journal,
            settlement_reports_by_game={},
            settled_at_utc="2026-08-25T11:00:00+00:00",
        )
        self.assertEqual(record["outcomes"][0]["settlement_result"], "UNRESOLVED")
        self.assertEqual(
            record["outcomes"][0]["settlement_reason"],
            "GAME_SETTLEMENT_EVIDENCE_MISSING",
        )

    def test_expected_prediction_journal_sha_mismatch_is_rejected(self):
        journal = _journal(_prediction("MONEYLINE", side="HOME", line=None))
        with self.assertRaisesRegex(MLBPredictionSettlementError, "journal SHA mismatch"):
            build_game_prediction_settlement_record(
                journal,
                settlement_reports_by_game={GAME_ID: _report()},
                settled_at_utc="2026-08-25T11:00:00+00:00",
                expected_prediction_journal_sha256="0" * 64,
            )

    def test_prediction_count_mismatch_is_rejected(self):
        journal = _journal(_prediction("MONEYLINE", side="HOME", line=None))
        journal["prediction_count"] = 2
        with self.assertRaisesRegex(MLBPredictionSettlementError, "prediction_count mismatch"):
            build_game_prediction_settlement_record(
                journal,
                settlement_reports_by_game={GAME_ID: _report()},
                settled_at_utc="2026-08-25T11:00:00+00:00",
            )

    def test_stage1_provenance_is_revalidated_at_settlement_boundary(self):
        journal = _journal(_prediction("MONEYLINE", side="HOME", line=None))
        journal["predictions"][0]["distribution_sha256"] = "bad"
        journal["prediction_count"] = len(journal["predictions"])
        with self.assertRaisesRegex(MLBPredictionSettlementError, "distribution_sha256"):
            build_game_prediction_settlement_record(
                journal,
                settlement_reports_by_game={GAME_ID: _report()},
                settled_at_utc="2026-08-25T11:00:00+00:00",
            )

    def test_report_key_must_match_official_game_pk(self):
        journal = _journal(_prediction("MONEYLINE", side="HOME", line=None))
        with self.assertRaisesRegex(MLBPredictionSettlementError, "key/game mismatch"):
            build_game_prediction_settlement_record(
                journal,
                settlement_reports_by_game={"1": _report()},
                settled_at_utc="2026-08-25T11:00:00+00:00",
            )

    def test_immutable_settlement_write_is_idempotent_and_never_overwrites(self):
        journal = _journal(_prediction("MONEYLINE", side="HOME", line=None))
        record = build_game_prediction_settlement_record(
            journal,
            settlement_reports_by_game={GAME_ID: _report()},
            settled_at_utc="2026-08-25T11:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as tmp:
            first = write_game_prediction_settlement(record, root=tmp)
            second = write_game_prediction_settlement(record, root=tmp)
            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(first.path, second.path)
            self.assertEqual(first.settlement_sha256, second.settlement_sha256)
            original = Path(first.path).read_bytes()

            changed = copy.deepcopy(record)
            changed["settled_at_utc"] = "2026-08-25T11:05:00+00:00"
            third = write_game_prediction_settlement(changed, root=tmp)
            self.assertTrue(third.created)
            self.assertNotEqual(first.path, third.path)
            self.assertEqual(Path(first.path).read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
