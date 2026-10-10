"""Public capper research captures never confer CFB model or staking authority."""
import hashlib
import unittest

from scripts.research_cfb_public_cappers import audit

KICKOFF = "2026-10-17T23:00:00Z"


def _pick(market="SPREAD", *, side=None, game_id="g1"):
    text = "SYNTHETIC TEST ONLY: Home -3.5 -110 CFB pick"
    return {
        "game_id": game_id, "matchup": "Away @ Home",
        "market": market,
        "side": side or ("HOME" if market == "SPREAD" else "OVER"),
        "line": -3.5 if market == "SPREAD" else 48.5,
        "american_odds": -110, "units": 2,
        "source_url": "https://x.com/BeatinTheBookie/status/123456789",
        "source_text": text,
        "source_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "published_at": "2026-10-17T17:00:00Z",
        "captured_at": "2026-10-17T18:00:00Z",
        "kickoff_at": KICKOFF,
    }


def _payload(*picks):
    return {"schema": "CFB_PUBLIC_HANDICAPPER_RESEARCH_V1",
            "handle": "@BeatinTheBookie", "picks": list(picks)}


def _settlement(home=31, away=20):
    return [{"game_id": "g1", "kickoff_at": KICKOFF,
             "settled_at": "2026-10-18T03:00:00Z",
             "home_points": home, "away_points": away}]


class PublicCapperAuditTest(unittest.TestCase):
    def test_independent_context_tracks_outcomes_without_authority(self):
        result = audit(_payload(_pick(), _pick("TOTAL")), settlements=_settlement())
        self.assertEqual(result["settled_picks"], 2)
        self.assertEqual(result["wins"], 2)
        self.assertAlmostEqual(result["claimed_price_unit_roi"], 100 / 110, places=5)
        self.assertEqual(result["validated_markets"], [])
        self.assertFalse(result["bets_enabled"])
        self.assertFalse(result["positive_ev_proven"])
        self.assertFalse(result["model_probabilities_imported"])
        self.assertFalse(result["independent_book_price_attested"])

    def test_missing_outcomes_remain_pending(self):
        result = audit(_payload(_pick()))
        self.assertEqual(result["pending_picks"], 1)
        self.assertIsNone(result["claimed_price_unit_roi"])

    def test_hindsight_capture_is_rejected(self):
        p = _pick()
        p["captured_at"] = KICKOFF
        with self.assertRaisesRegex(ValueError, "NO_PREGAME_CAPTURE"):
            audit(_payload(p))

    def test_source_text_must_be_exactly_hash_bound(self):
        p = _pick()
        p["source_text"] = "edited after kickoff"
        with self.assertRaisesRegex(ValueError, "SOURCE_TEXT_HASH_MISMATCH"):
            audit(_payload(p))

    def test_impostor_social_post_fails_closed(self):
        p = _pick()
        p["source_url"] = "https://x.com/other/status/123456789"
        with self.assertRaisesRegex(ValueError, "PUBLIC_SOURCE_URL_INVALID"):
            audit(_payload(p))

    def test_duplicate_same_market_game_blocks_cherry_picking(self):
        with self.assertRaisesRegex(ValueError, "GAME_MARKET_DUPLICATE"):
            audit(_payload(_pick(), _pick()))

    def test_unsupported_price_and_units_are_rejected(self):
        p = _pick()
        p["american_odds"] = -50
        with self.assertRaisesRegex(ValueError, "AMERICAN_ODDS_INVALID"):
            audit(_payload(p))
        p = _pick()
        p["units"] = 100
        with self.assertRaisesRegex(ValueError, "LINE_OR_UNITS_INVALID"):
            audit(_payload(p))

    def test_bet_result_can_be_loss_and_push(self):
        report = audit(_payload(_pick()), settlements=_settlement(20, 31))
        self.assertEqual(report["losses"], 1)
        report = audit(_payload(_pick("TOTAL")), settlements=_settlement(23, 25))
        self.assertEqual(report["losses"], 1)
        p = _pick()
        p["line"] = -3.0
        report = audit(_payload(p), settlements=_settlement(23, 20))
        self.assertEqual(report["pushes"], 1)

    def test_settlement_identity_must_match(self):
        r = _settlement()
        r[0]["kickoff_at"] = "2026-10-17T22:00:00Z"
        with self.assertRaisesRegex(ValueError, "SETTLEMENT_KICKOFF_MISMATCH"):
            audit(_payload(_pick()), settlements=r)

    def test_empty_dataset_never_claims_profit(self):
        result = audit(_payload())
        self.assertEqual(result["captured_picks"], 0)
        self.assertIsNone(result["claimed_price_unit_roi"])
        self.assertFalse(result["positive_ev_proven"])


if __name__ == "__main__":
    unittest.main()
