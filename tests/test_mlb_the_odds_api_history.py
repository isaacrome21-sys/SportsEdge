import json
from hashlib import sha256
import unittest

from sportsedge.sports.mlb.the_odds_api_history import (
    MLBTheOddsAPIHistoryError,
    PROVIDER_SCHEMA,
    PROVENANCE,
    normalize_decision_close_pair,
    normalize_snapshot_quote,
)


def _snapshot(timestamp, *, spread=-1.5, total=8.5, book="draftkings", event_id="evt-1", commence="2024-06-10T23:10:00Z"):
    payload = {
        "timestamp": timestamp,
        "previous_timestamp": "2024-06-10T20:50:00Z",
        "next_timestamp": "2024-06-10T21:00:00Z",
        "data": {
            "id": event_id,
            "sport_key": "baseball_mlb",
            "commence_time": commence,
            "home_team": "Chicago Cubs",
            "away_team": "Tampa Bay Rays",
            "bookmakers": [{
                "key": book,
                "title": "DraftKings",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Chicago Cubs", "price": -120},
                        {"name": "Tampa Bay Rays", "price": 105},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": "Chicago Cubs", "price": 145, "point": spread},
                        {"name": "Tampa Bay Rays", "price": -170, "point": -spread},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "price": -110, "point": total},
                        {"name": "Under", "price": -110, "point": total},
                    ]},
                ],
            }],
        },
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return {
        "schema": PROVIDER_SCHEMA,
        "provenance": PROVENANCE,
        "requested_at": timestamp,
        "raw_bytes": raw,
        "raw_sha256": sha256(raw).hexdigest(),
        "interpolated": False,
        "reconstructed": False,
    }


class MLBTheOddsAPIHistoryTests(unittest.TestCase):
    def test_moneyline_pair_normalizes_and_stays_non_promotional(self):
        out = normalize_decision_close_pair(
            _snapshot("2024-06-10T21:00:00Z"),
            _snapshot("2024-06-10T23:00:00Z"),
            event_id="evt-1", book="draftkings", market="MONEYLINE", selection="Chicago Cubs",
        )
        self.assertEqual(out["normalized_pair"]["event_id"], "evt-1")
        self.assertEqual(out["decision_opposite_selection"], "Tampa Bay Rays")
        self.assertFalse(out["promotion_authority"])
        self.assertFalse(out["may_change_market_eligibility"])

    def test_spread_threshold_must_exist_in_both_snapshots(self):
        with self.assertRaisesRegex(MLBTheOddsAPIHistoryError, "SELECTION_THRESHOLD_NOT_FOUND"):
            normalize_decision_close_pair(
                _snapshot("2024-06-10T21:00:00Z", spread=-1.5),
                _snapshot("2024-06-10T23:00:00Z", spread=-2.5),
                event_id="evt-1", book="draftkings", market="SPREAD", selection="Chicago Cubs", threshold=-1.5,
            )

    def test_total_threshold_must_exist_in_both_snapshots(self):
        with self.assertRaisesRegex(MLBTheOddsAPIHistoryError, "SELECTION_THRESHOLD_NOT_FOUND"):
            normalize_decision_close_pair(
                _snapshot("2024-06-10T21:00:00Z", total=8.5),
                _snapshot("2024-06-10T23:00:00Z", total=9.0),
                event_id="evt-1", book="draftkings", market="TOTAL", selection="Over", threshold=8.5,
            )

    def test_snapshot_after_kickoff_is_rejected(self):
        with self.assertRaisesRegex(MLBTheOddsAPIHistoryError, "SNAPSHOT_AFTER_START"):
            normalize_snapshot_quote(
                _snapshot("2024-06-10T23:20:00Z"),
                event_id="evt-1", book="draftkings", market="MONEYLINE", selection="Chicago Cubs", threshold=None,
            )

    def test_wrong_book_and_event_fail_closed(self):
        with self.assertRaisesRegex(MLBTheOddsAPIHistoryError, "BOOK_NOT_FOUND"):
            normalize_snapshot_quote(
                _snapshot("2024-06-10T21:00:00Z"),
                event_id="evt-1", book="circa", market="MONEYLINE", selection="Chicago Cubs", threshold=None,
            )
        with self.assertRaisesRegex(MLBTheOddsAPIHistoryError, "EVENT_ID_MISMATCH"):
            normalize_snapshot_quote(
                _snapshot("2024-06-10T21:00:00Z"),
                event_id="evt-x", book="draftkings", market="MONEYLINE", selection="Chicago Cubs", threshold=None,
            )

    def test_missing_paired_opposite_is_rejected(self):
        snap = _snapshot("2024-06-10T21:00:00Z")
        payload = json.loads(snap["raw_bytes"])
        payload["data"]["bookmakers"][0]["markets"][0]["outcomes"] = [{"name": "Chicago Cubs", "price": -120}]
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        snap["raw_bytes"] = raw
        snap["raw_sha256"] = sha256(raw).hexdigest()
        with self.assertRaisesRegex(MLBTheOddsAPIHistoryError, "PAIRED_OPPOSITE_REQUIRED"):
            normalize_snapshot_quote(snap, event_id="evt-1", book="draftkings", market="MONEYLINE", selection="Chicago Cubs", threshold=None)

    def test_tampered_raw_bytes_are_rejected(self):
        snap = _snapshot("2024-06-10T21:00:00Z")
        snap["raw_bytes"] += b" "
        with self.assertRaisesRegex(MLBTheOddsAPIHistoryError, "RAW_SHA256_MISMATCH"):
            normalize_snapshot_quote(snap, event_id="evt-1", book="draftkings", market="MONEYLINE", selection="Chicago Cubs", threshold=None)

    def test_interpolation_and_reconstruction_are_forbidden(self):
        interpolated = _snapshot("2024-06-10T21:00:00Z")
        interpolated["interpolated"] = True
        with self.assertRaisesRegex(MLBTheOddsAPIHistoryError, "INTERPOLATION_FORBIDDEN"):
            normalize_snapshot_quote(interpolated, event_id="evt-1", book="draftkings", market="MONEYLINE", selection="Chicago Cubs", threshold=None)

        reconstructed = _snapshot("2024-06-10T21:00:00Z")
        reconstructed["reconstructed"] = True
        with self.assertRaisesRegex(MLBTheOddsAPIHistoryError, "RECONSTRUCTION_FORBIDDEN"):
            normalize_snapshot_quote(reconstructed, event_id="evt-1", book="draftkings", market="MONEYLINE", selection="Chicago Cubs", threshold=None)

    def test_provider_snapshot_cannot_be_later_than_requested_at(self):
        snap = _snapshot("2024-06-10T21:00:00Z")
        snap["requested_at"] = "2024-06-10T20:59:00Z"
        with self.assertRaisesRegex(MLBTheOddsAPIHistoryError, "SNAPSHOT_AFTER_REQUESTED_AT"):
            normalize_snapshot_quote(snap, event_id="evt-1", book="draftkings", market="MONEYLINE", selection="Chicago Cubs", threshold=None)


if __name__ == "__main__":
    unittest.main()
