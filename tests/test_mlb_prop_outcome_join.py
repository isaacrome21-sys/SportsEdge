import unittest

from sportsedge.mlb_prop_outcome_join import (
    PropOutcomeJoinError,
    bind_archived_quote,
    build_join_report,
    join_evidence_row,
)


class MLBPropOutcomeJoinTests(unittest.TestCase):
    """Synthetic contract tests only. These are not historical evidence."""

    def _bundle(self, *, market="PITCHER_OUTS", realized=19, line=17.5,
                settlement_state="SETTLED", settlement_reason="NORMAL_FINAL",
                origin="SYNTHETIC_FIXTURE"):
        quote = {
            "market": market,
            "game_id": "g-synth-1",
            "entity_id": "p-synth-1" if market != "RBI" else "b-synth-1",
            "line": line,
            "side": "OVER",
            "quote_ts": "2026-08-10T18:00:00-05:00",
            "first_pitch_ts": "2026-08-10T19:10:00-05:00",
            "quote_archive_sha256": "a" * 64,
            "identity_binding_sha256": "d" * 64,
            "evidence_origin": origin,
        }
        fact = {
            "market": market,
            "game_id": quote["game_id"],
            "entity_id": quote["entity_id"],
            "realized_count": realized,
            "fact_state": "FINAL_OFFICIAL",
            "facts_sha256": "b" * 64,
        }
        settlement = {
            "market": market,
            "game_id": quote["game_id"],
            "entity_id": quote["entity_id"],
            "settlement_state": settlement_state,
            "settlement_reason": settlement_reason,
        }
        model_eval = {
            "market": market,
            "game_id": quote["game_id"],
            "entity_id": quote["entity_id"],
            "history_asof_ts": "2026-08-10T17:59:00-05:00",
            "history_source_hash": "c" * 64,
            "incumbent_p": 0.55,
            "challenger_p": 0.63,
        }
        return {"quote": quote, "fact": fact, "settlement": settlement, "model_eval": model_eval}

    # Ambiguous-settlement tests intentionally come before the happy path.
    def test_ambiguous_injury_settlement_blocks_batch(self):
        bundle = self._bundle(
            settlement_state="AMBIGUOUS",
            settlement_reason="STARTER_REMOVED_FOR_INJURY_RULE_UNRESOLVED",
        )
        report = build_join_report([bundle])
        self.assertEqual(report["state"], "BLOCKED_AMBIGUOUS_SETTLEMENT")
        self.assertEqual(report["evidence_class"], "UNAVAILABLE")
        self.assertEqual(report["joined_row_count"], 0)
        self.assertEqual(report["ambiguous_count"], 1)

    def test_ambiguous_shortened_game_settlement_blocks_batch(self):
        bundle = self._bundle(
            market="PITCHER_ER",
            realized=2,
            line=2.5,
            settlement_state="AMBIGUOUS",
            settlement_reason="GAME_CALLED_EARLY_BOOK_RULE_UNRESOLVED",
        )
        report = build_join_report([bundle])
        self.assertEqual(report["state"], "BLOCKED_AMBIGUOUS_SETTLEMENT")
        self.assertIn("GAME_CALLED_EARLY", report["ambiguous"][0]["reason"])

    def test_ambiguous_rain_delay_eligibility_blocks_batch(self):
        bundle = self._bundle(
            settlement_state="AMBIGUOUS",
            settlement_reason="RAIN_DELAY_BEFORE_REQUIRED_APPEARANCE_RULE_UNRESOLVED",
        )
        report = build_join_report([bundle])
        self.assertEqual(report["state"], "BLOCKED_AMBIGUOUS_SETTLEMENT")

    def test_known_void_is_excluded_not_scored(self):
        bundle = self._bundle(
            market="PITCHER_ER",
            settlement_state="VOID",
            settlement_reason="BOOK_DECLARED_VOID",
        )
        report = build_join_report([bundle])
        self.assertEqual(report["state"], "BLOCKED_NO_SCORABLE_ROWS")
        self.assertEqual(report["void_excluded_count"], 1)
        self.assertEqual(report["joined_row_count"], 0)

    def test_push_is_preserved_for_downstream_push_semantics(self):
        bundle = self._bundle(market="PITCHER_ER", realized=2, line=2.0)
        row = join_evidence_row(**bundle)
        self.assertTrue(row.realized_push)
        self.assertFalse(row.realized_win)
        report = build_join_report([bundle])
        self.assertEqual(report["push_row_count"], 1)

    def test_binding_requires_verified_provider_event_and_player_identity(self):
        archived = {
            "market": "RBI",
            "provider_event_id": "dk-123",
            "entity_name_normalized": "sample batter",
            "line": 0.5,
            "side": "OVER",
            "quote_retrieved_at": "2026-08-10T18:00:00-05:00",
            "first_pitch_at": "2026-08-10T19:10:00-05:00",
        }
        binding = {
            "provider_event_id": "dk-123",
            "entity_name_normalized": "sample batter",
            "game_id": "mlb-999",
            "entity_id": "mlb-player-42",
            "identity_binding_sha256": "d" * 64,
        }
        quote = bind_archived_quote(
            archived,
            binding,
            quote_archive_sha256="a" * 64,
            evidence_origin="SYNTHETIC_FIXTURE",
        )
        self.assertEqual(quote["game_id"], "mlb-999")
        self.assertEqual(quote["entity_id"], "mlb-player-42")
        self.assertEqual(quote["evidence_origin"], "SYNTHETIC_FIXTURE")

    def test_binding_rejects_player_name_mismatch_instead_of_fuzzy_matching(self):
        archived = {
            "market": "RBI",
            "provider_event_id": "dk-123",
            "entity_name_normalized": "sample batter",
            "line": 0.5,
            "side": "OVER",
            "quote_retrieved_at": "2026-08-10T18:00:00-05:00",
            "first_pitch_at": "2026-08-10T19:10:00-05:00",
        }
        binding = {
            "provider_event_id": "dk-123",
            "entity_name_normalized": "different batter",
            "game_id": "mlb-999",
            "entity_id": "mlb-player-42",
            "identity_binding_sha256": "d" * 64,
        }
        with self.assertRaisesRegex(PropOutcomeJoinError, "player identity mismatch"):
            bind_archived_quote(
                archived,
                binding,
                quote_archive_sha256="a" * 64,
                evidence_origin="SYNTHETIC_FIXTURE",
            )

    def test_synthetic_happy_path_cannot_claim_historical_pit(self):
        report = build_join_report([
            self._bundle(),
            self._bundle(market="RBI", realized=1, line=0.5),
        ])
        self.assertEqual(report["state"], "SYNTHETIC_CONTRACT_PASS")
        self.assertEqual(report["evidence_class"], "SYNTHETIC_CONTRACT_TEST")
        self.assertEqual(report["joined_row_count"], 2)

    def test_real_origin_only_reaches_candidate_not_validated_label(self):
        report = build_join_report([self._bundle(origin="REAL_ARCHIVE")])
        self.assertEqual(report["state"], "JOIN_READY_FOR_PIT_VALIDATION")
        self.assertEqual(report["evidence_class"], "HISTORICAL_PIT_CANDIDATE")
        self.assertNotEqual(report["evidence_class"], "HISTORICAL_PIT_VALIDATED")

    def test_identity_mismatch_fails_closed(self):
        bundle = self._bundle()
        bundle["fact"] = {**bundle["fact"], "entity_id": "wrong-player"}
        with self.assertRaisesRegex(PropOutcomeJoinError, "identity mismatch"):
            join_evidence_row(**bundle)

    def test_post_first_pitch_quote_fails_closed(self):
        bundle = self._bundle()
        bundle["quote"] = {**bundle["quote"], "quote_ts": "2026-08-10T19:11:00-05:00"}
        with self.assertRaisesRegex(PropOutcomeJoinError, "quote_ts must be before"):
            join_evidence_row(**bundle)

    def test_nonfinal_official_fact_fails_closed(self):
        bundle = self._bundle()
        bundle["fact"] = {**bundle["fact"], "fact_state": "LIVE"}
        with self.assertRaisesRegex(PropOutcomeJoinError, "FINAL_OFFICIAL"):
            join_evidence_row(**bundle)


if __name__ == "__main__":
    unittest.main()
