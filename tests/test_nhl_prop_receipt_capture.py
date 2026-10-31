from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.nhl.prop_receipt_capture import (
    NHLPropReceiptError,
    receipt_from_mapping,
    write_create_only,
)


NOW = datetime(2026, 10, 8, 22, 0, tzinfo=timezone.utc)


def valid_row(**updates):
    row = {
        "market": "PLAYER_SHOTS",
        "game_id": "2026020001",
        "subject_id": "8478402",
        "line": 2.5,
        "candidate_p": 0.56,
        "baseline_p": 0.51,
        "book": "DraftKings",
        "american_odds": -115,
        "captured_at": "2026-10-08T21:55:00Z",
        "start_time_utc": "2026-10-08T23:00:00Z",
        "role_status": "CONFIRMED",
        "role_source": "official NHL roster/role receipt",
        "model_version": "nhl_player_shots_v1",
        "source": "sportsbook quote receipt",
        "source_sha256": "a" * 64,
    }
    row.update(updates)
    return row


class NHLPropReceiptCaptureTests(unittest.TestCase):
    def test_valid_pre_puck_receipt_is_compatible_with_forward_evaluator(self):
        receipt = receipt_from_mapping(valid_row(), now=NOW)
        payload = receipt.as_dict()
        for field in (
            "market", "game_id", "subject_id", "line", "candidate_p", "baseline_p",
            "captured_at", "start_time_utc", "role_status", "model_version", "source_sha256",
        ):
            self.assertIn(field, payload)
        self.assertEqual(payload["authority"], "EVIDENCE_ONLY_NO_CARD_AUTHORITY")

    def test_goalie_saves_supported(self):
        receipt = receipt_from_mapping(
            valid_row(
                market="GOALIE_SAVES",
                subject_id="8476945",
                line=25.5,
                american_odds=105,
                model_version="nhl_goalie_saves_v1",
            ),
            now=NOW,
        )
        self.assertEqual(receipt.market, "GOALIE_SAVES")

    def test_at_or_after_puck_drop_rejected(self):
        with self.assertRaisesRegex(NHLPropReceiptError, "not pre-puck"):
            receipt_from_mapping(
                valid_row(captured_at="2026-10-08T23:00:00Z"),
                now=datetime(2026, 10, 8, 23, 0, tzinfo=timezone.utc),
            )

    def test_stale_capture_rejected_as_backfill(self):
        with self.assertRaisesRegex(NHLPropReceiptError, "no-backfill"):
            receipt_from_mapping(valid_row(), now=datetime(2026, 10, 8, 22, 20, tzinfo=timezone.utc))

    def test_outside_frozen_window_rejected(self):
        with self.assertRaisesRegex(NHLPropReceiptError, "outside frozen forward window"):
            receipt_from_mapping(
                valid_row(
                    captured_at="2026-10-07T21:55:00Z",
                    start_time_utc="2026-10-07T23:00:00Z",
                ),
                now=datetime(2026, 10, 7, 22, 0, tzinfo=timezone.utc),
            )

    def test_unsupported_market_and_line_rejected(self):
        with self.assertRaisesRegex(NHLPropReceiptError, "unsupported market"):
            receipt_from_mapping(valid_row(market="PLAYER_POINTS"), now=NOW)
        with self.assertRaisesRegex(NHLPropReceiptError, "outside preregistered grid"):
            receipt_from_mapping(valid_row(line=5.5), now=NOW)

    def test_malformed_odds_rejected(self):
        for odds in (-99, 99, 0, 10001, -10001, 110.5):
            with self.subTest(odds=odds):
                with self.assertRaises(NHLPropReceiptError):
                    receipt_from_mapping(valid_row(american_odds=odds), now=NOW)

    def test_role_must_be_explicit_and_sourced(self):
        with self.assertRaisesRegex(NHLPropReceiptError, "explicitly CONFIRMED or PROJECTED"):
            receipt_from_mapping(valid_row(role_status="INFERRED"), now=NOW)
        with self.assertRaisesRegex(NHLPropReceiptError, "role_source required"):
            receipt_from_mapping(valid_row(role_source=""), now=NOW)
        with self.assertRaisesRegex(NHLPropReceiptError, "inferred role/starter state forbidden"):
            receipt_from_mapping(valid_row(role_inferred=True), now=NOW)

    def test_card_authority_fields_are_forbidden(self):
        for field in ("Model_P", "edge", "EV", "score", "kelly", "stake", "official", "actionable"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(NHLPropReceiptError, "card-authority fields forbidden"):
                    receipt_from_mapping(valid_row(**{field: 1}), now=NOW)

    def test_missing_required_field_rejected(self):
        row = valid_row()
        del row["source_sha256"]
        with self.assertRaisesRegex(NHLPropReceiptError, "missing field: source_sha256"):
            receipt_from_mapping(row, now=NOW)

    def test_create_only_write_is_idempotent(self):
        receipt = receipt_from_mapping(valid_row(), now=NOW)
        with tempfile.TemporaryDirectory() as tmp:
            first, first_status = write_create_only(receipt, output_root=tmp)
            second, second_status = write_create_only(receipt, output_root=tmp)
            self.assertEqual(first, second)
            self.assertEqual(first_status, "CAPTURED")
            self.assertEqual(second_status, "ALREADY_CAPTURED")
            payload = json.loads(Path(first).read_text())
            self.assertEqual(payload["receipt_version"], "NHL_PROP_FORWARD_RECEIPT_V1")
            self.assertNotIn("Model_P", payload)
            self.assertNotIn("edge", payload)


if __name__ == "__main__":
    unittest.main()
