import json
from hashlib import sha256
from pathlib import Path
import unittest

from sportsedge.sports.cfb.forward_market_pairing import (
    CFBForwardMarketPairingError,
    pair_snapshots,
)


def _payload(*, spread: float = -3.5):
    return [{
        "id": "provider-game-1",
        "commence_time": "2026-09-12T18:00:00Z",
        "bookmakers": [{
            "key": "draftkings",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "Home", "price": -120},
                    {"name": "Away", "price": 100},
                ]},
                {"key": "spreads", "outcomes": [
                    {"name": "Home", "price": -110, "point": spread},
                    {"name": "Away", "price": -110, "point": -spread},
                ]},
                {"key": "totals", "outcomes": [
                    {"name": "Over", "price": -105, "point": 52.5},
                    {"name": "Under", "price": -115, "point": 52.5},
                ]},
            ],
        }],
    }]


def _snapshot(root: Path, name: str, *, captured_at: str, spread: float = -3.5,
              paired_market_evidence: bool = False) -> Path:
    directory = root / name
    directory.mkdir()
    payload = _payload(spread=spread)
    raw = json.dumps(payload, separators=(",", ":")).encode()
    (directory / "snapshot.json").write_bytes(raw)
    meta = {
        "schema": "SPORTSEDGE_CFB_FORWARD_MARKET_SNAPSHOT_V1",
        "source": "THE_ODDS_API_CURRENT",
        "bookmaker": "draftkings",
        "markets": ["h2h", "spreads", "totals"],
        "captured_at_utc": captured_at,
        "payload_sha256": sha256(raw).hexdigest(),
        "forward_only": True,
        "retroactive_point_in_time_claim": False,
        "promotion_authority": False,
        "paired_market_evidence": paired_market_evidence,
        "model_p_created": False,
        "eligibility_changed": False,
    }
    (directory / "snapshot.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return directory


class CFBForwardMarketPairingTests(unittest.TestCase):
    def test_valid_exact_threshold_pair_establishes_market_evidence_only(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            root = Path(td)
            decision = _snapshot(root, "decision", captured_at="2026-09-12T16:30:00Z")
            close = _snapshot(root, "close", captured_at="2026-09-12T17:50:00Z")
            report = pair_snapshots(decision, close)
            self.assertEqual(report["status"], "PAIRED_FORWARD_MARKET_EVIDENCE_AVAILABLE")
            self.assertTrue(report["paired_market_evidence"])
            self.assertEqual(report["valid_market_pair_count"], 3)
            self.assertFalse(report["model_p_created"])
            self.assertFalse(report["promotion_authority"])
            self.assertFalse(report["truth_gate_ready"])
            self.assertFalse(report["official_status_granted"])

    def test_spread_threshold_drift_is_not_forced_into_pair(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            root = Path(td)
            decision = _snapshot(root, "decision", captured_at="2026-09-12T16:30:00Z", spread=-3.5)
            close = _snapshot(root, "close", captured_at="2026-09-12T17:50:00Z", spread=-4.5)
            report = pair_snapshots(decision, close)
            self.assertEqual(report["valid_market_pair_count"], 2)
            self.assertEqual({p["market"] for p in report["pairs"]}, {"h2h", "totals"})
            self.assertEqual(report["unmatched_or_threshold_drift_market_count"], 2)

    def test_same_magnitude_favorite_flip_is_rejected(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            root = Path(td)
            decision = _snapshot(root, "decision", captured_at="2026-09-12T16:30:00Z", spread=-3.5)
            close = _snapshot(root, "close", captured_at="2026-09-12T17:50:00Z", spread=3.5)
            report = pair_snapshots(decision, close)
            self.assertEqual(report["valid_market_pair_count"], 2)
            self.assertEqual({p["market"] for p in report["pairs"]}, {"h2h", "totals"})
            self.assertTrue(any(x["reason"] == "OUTCOME_THRESHOLD_CHANGED" for x in report["rejections"]))

    def test_close_outside_frozen_window_blocks_common_markets(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            root = Path(td)
            decision = _snapshot(root, "decision", captured_at="2026-09-12T16:30:00Z")
            close = _snapshot(root, "close", captured_at="2026-09-12T17:30:00Z")
            report = pair_snapshots(decision, close)
            self.assertEqual(report["status"], "BLOCKED_PAIRED_MARKET_EVIDENCE")
            self.assertEqual(report["valid_market_pair_count"], 0)
            self.assertEqual(report["rejected_common_market_count"], 3)
            self.assertTrue(all(x["reason"] == "CLOSE_OUTSIDE_FROZEN_WINDOW" for x in report["rejections"]))

    def test_tampered_snapshot_fails_sha_binding(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            root = Path(td)
            decision = _snapshot(root, "decision", captured_at="2026-09-12T16:30:00Z")
            close = _snapshot(root, "close", captured_at="2026-09-12T17:50:00Z")
            (decision / "snapshot.json").write_bytes(b"[]")
            with self.assertRaisesRegex(CFBForwardMarketPairingError, "PAYLOAD_SHA_MISMATCH"):
                pair_snapshots(decision, close)

    def test_snapshot_cannot_predeclare_itself_paired(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            root = Path(td)
            decision = _snapshot(root, "decision", captured_at="2026-09-12T16:30:00Z", paired_market_evidence=True)
            close = _snapshot(root, "close", captured_at="2026-09-12T17:50:00Z")
            with self.assertRaisesRegex(CFBForwardMarketPairingError, "PREDECLARED_PAIRING_FORBIDDEN"):
                pair_snapshots(decision, close)

    def test_decision_after_close_is_rejected(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as td:
            root = Path(td)
            decision = _snapshot(root, "decision", captured_at="2026-09-12T17:55:00Z")
            close = _snapshot(root, "close", captured_at="2026-09-12T17:50:00Z")
            with self.assertRaisesRegex(CFBForwardMarketPairingError, "TEMPORAL_ORDER_INVALID"):
                pair_snapshots(decision, close)


if __name__ == "__main__":
    unittest.main()
