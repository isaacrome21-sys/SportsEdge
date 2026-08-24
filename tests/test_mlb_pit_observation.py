from datetime import datetime, timezone
import unittest

from sportsedge.mlb_acceptance_matrix import build_acceptance_matrix
from sportsedge.mlb_pit_observation import (
    MLBPITObservationError,
    analyze_pit_observations,
    bind_participant_to_player,
    bind_provider_event_to_game,
    content_sha256,
    normalize_pit_observation,
)
from sportsedge.quote_bridge import SUPPORTED_MARKETS


SYNTHETIC = "SYNTHETIC_CONTRACT_TEST"


def _archived_quote():
    event = {
        "id": 123,
        "name": "Away @ Home",
        "startDate": "2026-08-24T00:10:00Z",
        "participants": [
            {"name": "Away Team", "venueRole": "Away"},
            {"name": "Home Team", "venueRole": "Home"},
        ],
    }
    return {
        "provider_event_snapshot": event,
        "provider_event_sha256": content_sha256(event),
        "first_pitch_at": "2026-08-24T00:10:00+00:00",
    }


def _row(**changes):
    row = {
        "market": "HITS",
        "game_id": "999",
        "entity_id": "42",
        "quote_ts": "2026-08-23T23:45:00+00:00",
        "first_pitch_ts": "2026-08-24T00:10:00+00:00",
        "line": 0.5,
        "side": "OVER",
        "sportsbook": "DraftKings",
        "book_key": "draftkings_direct",
        "source_evidence_class": SYNTHETIC,
        "model_evidence_class": SYNTHETIC,
        "official_fact_evidence_class": SYNTHETIC,
        "book_rule_evidence_class": SYNTHETIC,
        "quote_source_hash": "1" * 64,
        "provider_event_hash": "2" * 64,
        "identity_binding_hash": "3" * 64,
        "history_asof_ts": "2026-08-23T23:40:00+00:00",
        "history_source_hash": "4" * 64,
        "model_input_hash": "5" * 64,
        "official_facts_hash": "6" * 64,
        "settlement_rules_hash": "7" * 64,
        "settlement_state": "SETTLEMENT_ELIGIBLE",
        "settled_outcome": "WIN",
        "candidate_p": 0.65,
        "incumbent_p": 0.55,
    }
    row.update(changes)
    return row


def _live_row(**changes):
    row = _row(
        source_evidence_class="LIVE_PROVIDER_QUOTE_ARCHIVE",
        model_evidence_class="LIVE_PIT_MODEL",
        official_fact_evidence_class="LIVE_OFFICIAL_FACT_PROBE",
        book_rule_evidence_class="LIVE_BOOK_RULE_CAPTURE",
    )
    row.update(changes)
    return row


class MLBPITObservationTests(unittest.TestCase):
    def test_supported_market_surface_matches_acceptance_matrix(self):
        catalog = {row["market"] for row in build_acceptance_matrix()["markets"]}
        self.assertEqual(set(SUPPORTED_MARKETS), catalog)
        self.assertEqual(len(catalog), 36)

    def test_provider_event_binds_only_unique_exact_team_time_match(self):
        quote = _archived_quote()
        game_id = bind_provider_event_to_game(
            quote,
            [
                {
                    "game_id": "999",
                    "away_name": "Away Team",
                    "home_name": "Home Team",
                    "first_pitch_ts": "2026-08-24T00:12:00+00:00",
                },
                {
                    "game_id": "998",
                    "away_name": "Other Away",
                    "home_name": "Other Home",
                    "first_pitch_ts": "2026-08-24T00:10:00+00:00",
                },
            ],
        )
        self.assertEqual(game_id, "999")

    def test_provider_event_hash_mismatch_fails_closed(self):
        quote = _archived_quote()
        quote["provider_event_sha256"] = "a" * 64
        with self.assertRaisesRegex(MLBPITObservationError, "HASH_MISMATCH"):
            bind_provider_event_to_game(quote, [])

    def test_provider_event_multiple_matches_fail_closed(self):
        quote = _archived_quote()
        candidates = [
            {
                "game_id": gid,
                "away_name": "Away Team",
                "home_name": "Home Team",
                "first_pitch_ts": "2026-08-24T00:10:00+00:00",
            }
            for gid in ("1", "2")
        ]
        with self.assertRaisesRegex(MLBPITObservationError, "GAME_AMBIGUOUS"):
            bind_provider_event_to_game(quote, candidates)

    def test_participant_binding_requires_unique_exact_normalized_name(self):
        self.assertEqual(
            bind_participant_to_player(
                "José Ramírez",
                [
                    {"player_id": "10", "player_name": "Jose Ramirez"},
                    {"player_id": "11", "player_name": "Different Player"},
                ],
            ),
            "10",
        )
        with self.assertRaisesRegex(MLBPITObservationError, "PLAYER_AMBIGUOUS"):
            bind_participant_to_player(
                "John Smith",
                [
                    {"player_id": "10", "player_name": "John Smith"},
                    {"player_id": "11", "player_name": "John Smith"},
                ],
            )

    def test_quote_side_contract_is_reused(self):
        with self.assertRaisesRegex(MLBPITObservationError, "unsupported side for HITS"):
            normalize_pit_observation(_row(side="HOME"))

    def test_quote_and_model_history_are_strictly_point_in_time(self):
        with self.assertRaisesRegex(MLBPITObservationError, "quote_ts must be before"):
            normalize_pit_observation(_row(quote_ts="2026-08-24T00:11:00+00:00"))
        with self.assertRaisesRegex(MLBPITObservationError, "at or before quote_ts"):
            normalize_pit_observation(_row(history_asof_ts="2026-08-23T23:46:00+00:00"))

    def test_settlement_eligible_requires_scored_outcome_rule_hash_and_rule_class(self):
        with self.assertRaisesRegex(MLBPITObservationError, "requires WIN, LOSS, or PUSH"):
            normalize_pit_observation(_row(settled_outcome=None))
        with self.assertRaisesRegex(MLBPITObservationError, "settlement_rules_hash"):
            normalize_pit_observation(_row(settlement_rules_hash=None))
        with self.assertRaisesRegex(MLBPITObservationError, "requires book-rule evidence"):
            normalize_pit_observation(_row(book_rule_evidence_class="MISSING"))

    def test_ambiguous_or_void_rows_cannot_carry_scored_outcome(self):
        for state in ("AMBIGUOUS_SETTLEMENT", "VOID", "BOOK_SETTLEMENT_UNVALIDATED"):
            kwargs = {"settlement_state": state, "settled_outcome": None}
            if state == "BOOK_SETTLEMENT_UNVALIDATED":
                kwargs["settlement_rules_hash"] = None
                kwargs["book_rule_evidence_class"] = "MISSING"
            normalized = normalize_pit_observation(_row(**kwargs))
            self.assertFalse(normalized.is_scored)
            with self.assertRaisesRegex(MLBPITObservationError, "must not carry a scored outcome"):
                normalize_pit_observation(_row(**kwargs, settled_outcome="LOSS"))

    def test_push_void_and_ambiguity_are_excluded_not_scored_as_losses(self):
        report = analyze_pit_observations(
            [
                _row(game_id="1", settled_outcome="WIN", candidate_p=0.7),
                _row(game_id="2", settled_outcome="PUSH", candidate_p=0.5),
                _row(game_id="3", settlement_state="VOID", settled_outcome=None, candidate_p=0.4),
                _row(game_id="4", settlement_state="AMBIGUOUS_SETTLEMENT", settled_outcome=None, candidate_p=0.4),
            ]
        )
        self.assertEqual(report["source_row_count"], 4)
        self.assertEqual(report["scored_row_count"], 1)
        self.assertEqual(report["push_rows_excluded_from_binary_error"], 1)
        self.assertEqual(report["void_rows_excluded"], 1)
        self.assertEqual(report["ambiguous_rows_excluded"], 1)

    def test_any_synthetic_component_blocks_historical_label(self):
        report = analyze_pit_observations(
            [_live_row(model_evidence_class=SYNTHETIC)]
        )
        self.assertEqual(report["evidence_class"], "SYNTHETIC_CONTRACT_TEST")
        self.assertFalse(report["counts_as_historical_pit"])
        self.assertEqual(report["scored_row_count"], 1)
        self.assertEqual(report["synthetic_component_row_count"], 1)

    def test_fully_proven_live_row_can_be_labeled_historical_pit(self):
        report = analyze_pit_observations([_live_row()])
        self.assertEqual(report["evidence_class"], "HISTORICAL_PIT")
        self.assertTrue(report["counts_as_historical_pit"])
        self.assertEqual(report["scored_row_count"], 1)
        self.assertEqual(report["durable_scored_row_count"], 1)
        self.assertIsNotNone(report["candidate_metrics"])
        self.assertIsNotNone(report["incumbent_challenger_comparison"])

    def test_new_market_can_score_without_fake_incumbent(self):
        report = analyze_pit_observations(
            [_live_row(market="EXTRA_BASE_HITS", incumbent_p=None)]
        )
        self.assertTrue(report["counts_as_historical_pit"])
        self.assertIsNotNone(report["candidate_metrics"])
        self.assertIsNone(report["incumbent_challenger_comparison"])


if __name__ == "__main__":
    unittest.main()
