from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb.manual_quotes import CFBManualQuoteError, load_manual_cfb_quote_bundle

ROOT = Path(__file__).resolve().parents[1]


class CFBManualQuoteTests(unittest.TestCase):
    def write(self, payload):
        td = tempfile.TemporaryDirectory(); self.addCleanup(td.cleanup)
        path = Path(td.name) / "quotes.json"; path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def base(self):
        return {
            "schema_version": "CFB_MANUAL_QUOTES_V1",
            "book_key": "draftkings",
            "observed_at": "2026-09-11T23:10:00Z",
            "source_evidence_ref": "DK_SCREENSHOT_2026-09-11T23:10Z",
            "quotes": [
                {"game_id":"g1","market":"MONEYLINE","side":"HOME","line":0,"american_odds":-145},
                {"game_id":"g1","market":"MONEYLINE","side":"AWAY","line":0,"american_odds":125},
                {"game_id":"g1","market":"SPREAD","side":"HOME","line":-3.5,"american_odds":-110},
                {"game_id":"g1","market":"SPREAD","side":"AWAY","line":-3.5,"american_odds":-110},
                {"game_id":"g1","market":"TOTAL","side":"OVER","line":51.5,"american_odds":-108},
                {"game_id":"g1","market":"TOTAL","side":"UNDER","line":51.5,"american_odds":-112}
            ]
        }

    def test_valid_file_materializes_paired_quotes_and_byte_provenance(self):
        bundle = load_manual_cfb_quote_bundle(self.write(self.base()))
        self.assertEqual(len(bundle["quotes"]), 6)
        self.assertEqual(bundle["book_key"], "draftkings")
        self.assertEqual(len(bundle["quote_file_sha256"]), 64)
        self.assertTrue(bundle["source_evidence_ref"])

    def test_one_sided_market_is_rejected(self):
        payload=self.base(); payload["quotes"]=payload["quotes"][:-1]
        with self.assertRaisesRegex(CFBManualQuoteError,"TWO_SIDED_PAIR_REQUIRED"):
            load_manual_cfb_quote_bundle(self.write(payload))

    def test_evidence_reference_is_required(self):
        payload=self.base(); payload.pop("source_evidence_ref")
        with self.assertRaisesRegex(CFBManualQuoteError,"SOURCE_EVIDENCE_REF_REQUIRED"):
            load_manual_cfb_quote_bundle(self.write(payload))

    def test_non_dk_book_is_rejected(self):
        payload=self.base(); payload["book_key"]="otherbook"
        with self.assertRaisesRegex(CFBManualQuoteError,"BOOK_MUST_BE_DRAFTKINGS"):
            load_manual_cfb_quote_bundle(self.write(payload))

    def test_spread_pair_uses_same_home_spread_identity(self):
        payload=self.base()
        for row in payload["quotes"]:
            if row["market"]=="SPREAD" and row["side"]=="AWAY": row["line"]=3.5
        with self.assertRaisesRegex(CFBManualQuoteError,"TWO_SIDED_PAIR_REQUIRED"):
            load_manual_cfb_quote_bundle(self.write(payload))

    def test_hybrid_runner_has_no_odds_api_credential_path(self):
        source = (ROOT / "scripts/run_cfb_hybrid.py").read_text(encoding="utf-8")
        self.assertNotIn("SPORTSEDGE_ODDS_API_KEY", source)
        self.assertNotIn("ODDS_API_KEY", source)
        self.assertIn('mode="HYBRID"', source)
        self.assertIn("quotes=bundle[\"quotes\"]", source)
        self.assertIn('"odds_api_used": False', source)


if __name__ == "__main__": unittest.main()
