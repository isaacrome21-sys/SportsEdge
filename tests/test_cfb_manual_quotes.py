from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb.manual_quotes import CFBManualQuoteError, load_manual_cfb_quotes


class CFBManualQuoteTests(unittest.TestCase):
    def write(self, payload):
        td = tempfile.TemporaryDirectory()
        path = Path(td.name) / "quotes.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.addCleanup(td.cleanup)
        return path

    def base(self):
        return {
            "schema_version": "CFB_MANUAL_QUOTES_V1",
            "book_key": "draftkings",
            "observed_at": "2026-09-11T23:10:00Z",
            "quotes": [
                {"game_id": "g1", "market": "MONEYLINE", "side": "HOME", "line": 0, "american_odds": -145},
                {"game_id": "g1", "market": "MONEYLINE", "side": "AWAY", "line": 0, "american_odds": 125},
                {"game_id": "g1", "market": "SPREAD", "side": "HOME", "line": -3.5, "american_odds": -110},
                {"game_id": "g1", "market": "SPREAD", "side": "AWAY", "line": -3.5, "american_odds": -110},
                {"game_id": "g1", "market": "TOTAL", "side": "OVER", "line": 51.5, "american_odds": -108},
                {"game_id": "g1", "market": "TOTAL", "side": "UNDER", "line": 51.5, "american_odds": -112},
            ],
        }

    def test_valid_file_materializes_canonical_paired_quotes(self):
        rows = load_manual_cfb_quotes(self.write(self.base()))
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r.book_key == "draftkings" for r in rows))
        self.assertTrue(all(r.retrieved_at.endswith("+00:00") for r in rows))
        self.assertEqual(len({r.offer_id for r in rows}), 6)

    def test_one_sided_market_is_rejected(self):
        payload = self.base()
        payload["quotes"] = payload["quotes"][:-1]
        with self.assertRaisesRegex(CFBManualQuoteError, "TWO_SIDED_PAIR_REQUIRED"):
            load_manual_cfb_quotes(self.write(payload))

    def test_non_dk_book_is_rejected(self):
        payload = self.base(); payload["book_key"] = "otherbook"
        with self.assertRaisesRegex(CFBManualQuoteError, "BOOK_MUST_BE_DRAFTKINGS"):
            load_manual_cfb_quotes(self.write(payload))

    def test_naive_observation_time_is_rejected(self):
        payload = self.base(); payload["observed_at"] = "2026-09-11T23:10:00"
        with self.assertRaisesRegex(CFBManualQuoteError, "TIMEZONE_REQUIRED"):
            load_manual_cfb_quotes(self.write(payload))

    def test_spread_pair_uses_same_home_spread_identity(self):
        payload = self.base()
        for row in payload["quotes"]:
            if row["market"] == "SPREAD" and row["side"] == "AWAY":
                row["line"] = 3.5
        with self.assertRaisesRegex(CFBManualQuoteError, "TWO_SIDED_PAIR_REQUIRED"):
            load_manual_cfb_quotes(self.write(payload))


if __name__ == "__main__":
    unittest.main()
