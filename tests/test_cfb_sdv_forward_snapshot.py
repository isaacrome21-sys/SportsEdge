import unittest
from copy import deepcopy

from scripts.export_cfb_sdv_forward_snapshot import export_snapshot

HASH = "a" * 64


def card():
    return {
        "schema": "CFB_SDV_CARD_V2",
        "model_status": "MODEL_SDV_PUBLIC_LIVE_UNVALIDATED",
        "scored_at_utc": "2026-10-09T23:00:00Z",
        "live_source_provenance": {
            "capture_time": "2026-10-09T22:58:00Z",
            "source_contract": "CFB_SDV_PUBLIC_PROSPECTIVE_2026_V1",
            "file_sha256": {f"asset_{i}.csv": f"{i + 1:x}" * 64 for i in range(8)},
        },
        "validated_markets": [], "bets": 0,
        "results": [
            {"game_id": "123", "matchup": "Away @ Home", "market": "SPREAD",
             "side": "HOME", "line": -3.5, "home_mean": 28, "away_mean": 22,
             "start_ts": "2026-10-10T01:00:00Z"},
            {"game_id": "123", "matchup": "Away @ Home", "market": "SPREAD",
             "side": "AWAY", "line": 3.5, "home_mean": 28, "away_mean": 22,
             "start_ts": "2026-10-10T01:00:00Z"},
            {"game_id": "123", "matchup": "Away @ Home", "market": "TOTAL",
             "side": "OVER", "line": 48.5, "home_mean": 28, "away_mean": 22,
             "start_ts": "2026-10-10T01:00:00Z"},
        ],
    }


class ForwardSnapshotTest(unittest.TestCase):
    def test_prospective_model_prediction_is_research_only(self):
        out = export_snapshot(card(), original_card_sha256=HASH)
        self.assertEqual(out["status"], "PREGAME_MODEL_SNAPSHOTS_UNVALIDATED")
        self.assertEqual(len(out["games"]), 1)
        self.assertEqual(out["games"][0]["model_margin"], 6)
        self.assertEqual(out["games"][0]["model_total"], 50)
        self.assertFalse(out["positive_ev_proven"])
        self.assertFalse(out["source_run_independently_attested"])
        self.assertFalse(out["sportsbook_price_receipt_verified"])
        self.assertFalse(out["bets_enabled"])

    def test_pregame_quote_prices_are_preserved_without_betting_authority(self):
        inp = card()
        for row in inp["results"]:
            row.update({"american_odds": -110, "model_p": 0.57,
                        "market_p": 0.5, "devig": "PAIRED_PROPORTIONAL",
                        "bet_status": "LEAN"})
        inp["results"][2]["devig"] = "UNPAIRED_RAW_IMPLIED"
        quote_rows = export_snapshot(inp, original_card_sha256=HASH)["games"][0]["quoted_selections"]
        self.assertEqual(len(quote_rows), 3)
        self.assertEqual(quote_rows[0]["american_odds"], -110)
        self.assertEqual(quote_rows[0]["quote_evidence"], "UNATTESTED_MANUAL_BOARD")
        self.assertFalse(quote_rows[0]["betting_authority"])

    def test_forged_opposing_quote_pair_is_rejected(self):
        inp = card()
        inp["results"] = [inp["results"][0]]
        inp["results"][0].update({"american_odds": -110, "model_p": 0.57,
                                  "market_p": 0.50, "devig": "PAIRED_PROPORTIONAL"})
        with self.assertRaisesRegex(ValueError, "CFB_FORWARD_QUOTE_PAIRED_IDENTITY_INVALID"):
            export_snapshot(inp, original_card_sha256=HASH)

    def test_invalid_quote_price_or_probability_rejected(self):
        inp = card()
        inp["results"][0].update({"american_odds": -50, "model_p": 0.5,
                                  "market_p": 0.5, "devig": "UNPAIRED_RAW_IMPLIED"})
        with self.assertRaisesRegex(ValueError, "CFB_FORWARD_QUOTE_ODDS_INVALID"):
            export_snapshot(inp, original_card_sha256=HASH)
        inp["results"][0]["american_odds"] = -110
        inp["results"][0]["model_p"] = 1.5
        with self.assertRaisesRegex(ValueError, "CFB_FORWARD_QUOTE_PROBABILITY_INVALID"):
            export_snapshot(inp, original_card_sha256=HASH)

    def test_kicked_off_prediction_is_not_backfilled(self):
        inp = card()
        inp["scored_at_utc"] = "2026-10-10T01:00:00Z"
        out = export_snapshot(inp, original_card_sha256=HASH)
        self.assertEqual(out["games"], [])
        self.assertEqual(out["status"], "NO_PREGAME_MODEL_ROWS")

    def test_market_only_fallback_never_creates_predictions(self):
        inp = card()
        inp["model_status"] = "MARKET_ONLY:CFBD_RATE_LIMITED"
        out = export_snapshot(inp, original_card_sha256=HASH)
        self.assertEqual(out["games"], [])
        self.assertEqual(out["status"], "NO_MODEL_PREGAME_FORECASTS")

    def test_missing_scored_time_rejected(self):
        inp = card()
        del inp["scored_at_utc"]
        with self.assertRaisesRegex(ValueError, "CFB_FORWARD_TIMESTAMP_INVALID"):
            export_snapshot(inp, original_card_sha256=HASH)

    def test_missing_source_receipt_rejected(self):
        inp = card()
        inp["live_source_provenance"]["file_sha256"] = {}
        with self.assertRaisesRegex(ValueError, "CFB_FORWARD_SOURCE_RECEIPTS_REQUIRED"):
            export_snapshot(inp, original_card_sha256=HASH)

    def test_selection_identity_or_mean_mismatch_rejected(self):
        inp = card()
        inp["results"][1]["away_mean"] = 12
        with self.assertRaisesRegex(ValueError, "CFB_FORWARD_SELECTION_SCORE_MISMATCH"):
            export_snapshot(inp, original_card_sha256=HASH)

    def test_no_prior_source_time_after_score(self):
        inp = card()
        inp["live_source_provenance"]["capture_time"] = "2026-10-10T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "CFB_FORWARD_SCORED_BEFORE_SOURCE"):
            export_snapshot(inp, original_card_sha256=HASH)

    def test_no_staking_authority_even_with_validated_market_flag(self):
        inp = card()
        inp["validated_markets"] = ["TOTAL"]
        with self.assertRaisesRegex(ValueError, "CFB_FORWARD_ZERO_BET_AUTHORITY_REQUIRED"):
            export_snapshot(inp, original_card_sha256=HASH)

    def test_naive_kickoff_rejected(self):
        inp = card()
        for row in inp["results"]:
            row["start_ts"] = "2026-10-10T01:00:00"
        with self.assertRaisesRegex(ValueError, "CFB_FORWARD_TIMESTAMP_INVALID"):
            export_snapshot(inp, original_card_sha256=HASH)


if __name__ == "__main__":
    unittest.main()
