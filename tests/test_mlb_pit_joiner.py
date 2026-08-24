import hashlib
import unittest

from sportsedge.mlb_pit_joiner import join_prop_archive, observation_key
from sportsedge.mlb_pit_observation import analyze_pit_observations, content_sha256
from sportsedge.mlb_settlement_evidence import canonical_bytes


def _event():
    return {
        "id": 123,
        "name": "Away Team @ Home Team",
        "startDate": "2026-08-24T00:10:00Z",
        "participants": [
            {"name": "Away Team", "venueRole": "Away"},
            {"name": "Home Team", "venueRole": "Home"},
        ],
    }


def _quote(market="HITS", entity_name="Player A", line=0.5):
    event = _event()
    return {
        "provider_event_id": "123",
        "market": market,
        "entity_name": entity_name,
        "entity_name_normalized": "playera",
        "side": "OVER",
        "line": line,
        "sportsbook": "DraftKings",
        "book_key": "draftkings_direct",
        "retrieved_at": "2026-08-23T23:45:00+00:00",
        "quote_retrieved_at": "2026-08-23T23:45:00+00:00",
        "first_pitch_at": "2026-08-24T00:10:00+00:00",
        "pit_eligible": True,
        "provider_event_snapshot": event,
        "provider_event_sha256": content_sha256(event),
    }


def _archive(*, source_class="SYNTHETIC_CONTRACT_TEST", quote=None):
    payload = {
        "schema_version": 2,
        "archive_type": "MLB_PROP_PIT_QUOTES",
        "evidence_class": source_class,
        "provider": "DRAFTKINGS_WEB_RESEARCH",
        "captured_at": "2026-08-23T23:46:00+00:00",
        "target_markets": ["HITS"],
        "quotes": [quote or _quote()],
    }
    payload["payload_sha256"] = content_sha256(payload)
    return payload


def _game():
    return {
        "game_id": "999",
        "away_name": "Away Team",
        "home_name": "Home Team",
        "first_pitch_ts": "2026-08-24T00:10:00+00:00",
        "away_probable_pitcher_id": "701",
        "home_probable_pitcher_id": "702",
    }


def _facts():
    facts = {"game_pk": "999", "status": "Final", "source": "SYNTHETIC_CONTRACT_TEST"}
    return {
        "schema_version": "mlb_settlement_evidence_v3",
        "facts_sha256": hashlib.sha256(canonical_bytes(facts)).hexdigest(),
        "facts": facts,
    }


def _model(market="HITS", entity_id="42", line=0.5):
    return {
        "game_id": "999",
        "market": market,
        "entity_id": entity_id,
        "line": line,
        "side": "OVER",
        "history_asof_ts": "2026-08-23T23:40:00+00:00",
        "history_source_hash": "4" * 64,
        "model_input_hash": "5" * 64,
        "candidate_p": 0.65,
        "incumbent_p": 0.55,
    }


def _settlement(*, market="HITS", entity_id="42", line=0.5, state="SETTLEMENT_ELIGIBLE", outcome="WIN"):
    key = observation_key(
        game_id="999",
        market=market,
        entity_id=entity_id,
        line=line,
        side="OVER",
        book_key="draftkings_direct",
        quote_ts="2026-08-23T23:45:00+00:00",
    )
    return {
        "observation_key": key,
        "settlement_state": state,
        "settled_outcome": outcome,
        "settlement_rules_hash": "7" * 64 if state in {"SETTLEMENT_ELIGIBLE", "VOID", "AMBIGUOUS_SETTLEMENT"} else None,
    }


class MLBPITJoinerTests(unittest.TestCase):
    def _join(self, **changes):
        args = {
            "archive_payload": _archive(),
            "game_candidates": [_game()],
            "player_candidates_by_game": {"999": [{"player_id": "42", "player_name": "Player A"}]},
            "model_rows": [_model()],
            "official_fact_reports": [_facts()],
            "settlement_rows": [_settlement()],
        }
        args.update(changes)
        return join_prop_archive(**args)

    def test_end_to_end_synthetic_join_produces_scored_but_not_historical_row(self):
        joined = self._join()
        self.assertEqual(joined["joined_observation_count"], 1)
        self.assertEqual(joined["failure_count"], 0)
        row = joined["observations"][0]
        self.assertEqual(row["game_id"], "999")
        self.assertEqual(row["entity_id"], "42")
        self.assertEqual(row["settlement_state"], "SETTLEMENT_ELIGIBLE")
        report = analyze_pit_observations(joined["observations"])
        self.assertEqual(report["scored_row_count"], 1)
        self.assertFalse(report["counts_as_historical_pit"])

    def test_without_book_settlement_row_join_is_unscored_and_book_unvalidated(self):
        joined = self._join(settlement_rows=[])
        self.assertEqual(joined["joined_observation_count"], 1)
        row = joined["observations"][0]
        self.assertEqual(row["settlement_state"], "BOOK_SETTLEMENT_UNVALIDATED")
        self.assertIsNone(row["settled_outcome"])
        report = analyze_pit_observations(joined["observations"])
        self.assertEqual(report["scored_row_count"], 0)
        self.assertEqual(report["book_unvalidated_rows_excluded"], 1)

    def test_missing_official_fact_artifact_fails_instead_of_faking_hash(self):
        joined = self._join(official_fact_reports=[])
        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertIn("OFFICIAL_FACT_REPORT_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])

    def test_tampered_archive_payload_hash_fails_before_join(self):
        archive = _archive()
        archive["quotes"][0]["line"] = 1.5
        with self.assertRaisesRegex(Exception, "ARCHIVE_PAYLOAD_HASH_MISMATCH"):
            self._join(archive_payload=archive)

    def test_tampered_official_facts_hash_fails_closed(self):
        report = _facts()
        report["facts"]["status"] = "Changed"
        joined = self._join(official_fact_reports=[report])
        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertIn("OFFICIAL_FACTS_HASH_MISMATCH", joined["failures"][0]["reason"])

    def test_duplicate_model_identity_fails_closed(self):
        model = _model()
        joined = self._join(model_rows=[model, dict(model)])
        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertIn("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])

    def test_unresolved_player_identity_fails_closed(self):
        joined = self._join(player_candidates_by_game={"999": []})
        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertIn("PLAYER_NOT_FOUND", joined["failures"][0]["reason"])

    def test_either_pitcher_market_uses_both_canonical_probable_pitcher_ids(self):
        quote = _quote(market="EITHER_PITCHER_ER", entity_name="Either Pitcher", line=2.5)
        archive = _archive(quote=quote)
        archive["target_markets"] = ["EITHER_PITCHER_ER"]
        archive["payload_sha256"] = content_sha256({k: v for k, v in archive.items() if k != "payload_sha256"})
        model = _model(market="EITHER_PITCHER_ER", entity_id="701|702", line=2.5)
        settlement = _settlement(market="EITHER_PITCHER_ER", entity_id="701|702", line=2.5)
        joined = self._join(
            archive_payload=archive,
            model_rows=[model],
            settlement_rows=[settlement],
        )
        self.assertEqual(joined["joined_observation_count"], 1)
        self.assertEqual(joined["observations"][0]["entity_id"], "701|702")


if __name__ == "__main__":
    unittest.main()
