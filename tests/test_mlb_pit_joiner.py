import hashlib
import unittest

from sportsedge.mlb_acceptance_matrix import build_acceptance_matrix
from sportsedge.mlb_pit_joiner import join_prop_archive, observation_key
from sportsedge.mlb_pit_observation import analyze_pit_observations, content_sha256
from sportsedge.mlb_settlement_evidence import canonical_bytes


SYNTHETIC = "SYNTHETIC_CONTRACT_TEST"


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


def _quote(market="HITS", entity_name="Player A", line=0.5, side="OVER"):
    event = _event()
    return {
        "provider_event_id": "123",
        "market": market,
        "entity_name": entity_name,
        "entity_name_normalized": "playera",
        "side": side,
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


def _archive(*, source_class=SYNTHETIC, quote=None):
    q = quote or _quote()
    payload = {
        "schema_version": 2,
        "archive_type": "MLB_PROP_PIT_QUOTES",
        "evidence_class": source_class,
        "provider": "DRAFTKINGS_WEB_RESEARCH",
        "captured_at": "2026-08-23T23:46:00+00:00",
        "target_markets": [q["market"]],
        "quotes": [q],
    }
    payload["payload_sha256"] = content_sha256(payload)
    return payload


def _rehash_archive(payload):
    payload.pop("payload_sha256", None)
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


def _facts(*, evidence_class=SYNTHETIC):
    facts = {
        "game_pk": "999",
        "status": "Final",
        "batters": [
            {
                "player_id": "42",
                "hits": 2,
                "home_runs": 1,
                "total_bases": 5,
                "rbi": 2,
                "runs": 1,
                "stolen_bases": 0,
                "walks": 1,
                "strikeouts": 1,
                "extra_base_hits": 1,
                "hits_runs_rbis": 5,
                "hits_runs_stolen_bases": 3,
                "runs_rbis": 3,
                "hits_stolen_bases": 2,
                "hits_walks_stolen_bases": 3,
                "singles": 1,
                "doubles": 0,
                "triples": 0,
            }
        ],
        "pitchers": [
            {
                "player_id": "701",
                "strikeouts": 7,
                "outs": 18,
                "earned_runs": 2,
                "hits_allowed": 5,
                "walks_allowed": 2,
                "hits_walks_er": 9,
            },
            {
                "player_id": "702",
                "strikeouts": 5,
                "outs": 17,
                "earned_runs": 3,
                "hits_allowed": 6,
                "walks_allowed": 1,
                "hits_walks_er": 10,
            },
        ],
    }
    return {
        "schema_version": "mlb_settlement_evidence_v3",
        "evidence_class": evidence_class,
        "facts_sha256": hashlib.sha256(canonical_bytes(facts)).hexdigest(),
        "facts": facts,
    }


def _model(market="HITS", entity_id="42", line=0.5, *, evidence_class=SYNTHETIC, history_asof=None):
    return {
        "game_id": "999",
        "market": market,
        "entity_id": entity_id,
        "line": line,
        "side": "OVER",
        "evidence_class": evidence_class,
        "history_asof_ts": history_asof or "2026-08-23T23:40:00+00:00",
        "history_source_hash": "4" * 64,
        "model_input_hash": "5" * 64,
        "candidate_p": 0.65,
        "incumbent_p": 0.55,
    }


def _required_rules(market):
    for row in build_acceptance_matrix()["markets"]:
        if row["market"] == market:
            return tuple(row["requirements"]["settlement_semantics"])
    raise AssertionError(market)


def _rule_evidence(market="HITS", sportsbook="DraftKings"):
    out = {}
    for rule in _required_rules(market):
        out[rule] = {
            "status": "VALIDATED",
            "sportsbook": sportsbook,
            "source_sha256": hashlib.sha256(rule.encode("utf-8")).hexdigest(),
            "captured_at_utc": "2026-08-23T20:00:00+00:00",
            "source_locator": f"fixture://{rule}",
        }
    return out


def _settlement(*, market="HITS", entity_id="42", line=0.5, evidence_class=SYNTHETIC,
                sportsbook="DraftKings", ambiguity_reasons=None, void_reasons=None):
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
        "evidence_class": evidence_class,
        "book_rule_evidence": _rule_evidence(market, sportsbook=sportsbook),
        "ambiguity_reasons": list(ambiguity_reasons or []),
        "void_reasons": list(void_reasons or []),
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

    def test_end_to_end_synthetic_join_derives_win_but_not_historical(self):
        joined = self._join()
        self.assertEqual(joined["joined_observation_count"], 1)
        self.assertEqual(joined["failure_count"], 0)
        row = joined["observations"][0]
        self.assertEqual(row["game_id"], "999")
        self.assertEqual(row["entity_id"], "42")
        self.assertEqual(row["settlement_state"], "SETTLEMENT_ELIGIBLE")
        self.assertEqual(row["settled_outcome"], "WIN")
        report = analyze_pit_observations(joined["observations"])
        self.assertEqual(report["scored_row_count"], 1)
        self.assertFalse(report["counts_as_historical_pit"])

    def test_full_live_chain_is_required_for_historical_label(self):
        joined = self._join(
            archive_payload=_archive(source_class="LIVE_PROVIDER_QUOTE_ARCHIVE"),
            model_rows=[_model(evidence_class="LIVE_PIT_MODEL")],
            official_fact_reports=[_facts(evidence_class="LIVE_OFFICIAL_FACT_PROBE")],
            settlement_rows=[_settlement(evidence_class="LIVE_BOOK_RULE_CAPTURE")],
        )
        report = analyze_pit_observations(joined["observations"])
        self.assertTrue(report["counts_as_historical_pit"])
        self.assertEqual(report["durable_scored_row_count"], 1)

    def test_live_quote_plus_synthetic_model_never_becomes_historical(self):
        joined = self._join(
            archive_payload=_archive(source_class="LIVE_PROVIDER_QUOTE_ARCHIVE"),
            model_rows=[_model(evidence_class=SYNTHETIC)],
            official_fact_reports=[_facts(evidence_class="LIVE_OFFICIAL_FACT_PROBE")],
            settlement_rows=[_settlement(evidence_class="LIVE_BOOK_RULE_CAPTURE")],
        )
        report = analyze_pit_observations(joined["observations"])
        self.assertFalse(report["counts_as_historical_pit"])
        self.assertEqual(report["evidence_class"], "SYNTHETIC_CONTRACT_TEST")

    def test_without_book_rule_row_join_is_unscored_and_book_unvalidated(self):
        joined = self._join(settlement_rows=[])
        self.assertEqual(joined["joined_observation_count"], 1)
        row = joined["observations"][0]
        self.assertEqual(row["settlement_state"], "BOOK_SETTLEMENT_UNVALIDATED")
        self.assertEqual(row["book_rule_evidence_class"], "MISSING")
        self.assertIsNone(row["settled_outcome"])

    def test_wrong_sportsbook_rule_evidence_cannot_make_row_eligible(self):
        joined = self._join(settlement_rows=[_settlement(sportsbook="FanDuel")])
        self.assertEqual(joined["joined_observation_count"], 1)
        self.assertEqual(joined["observations"][0]["settlement_state"], "BOOK_SETTLEMENT_UNVALIDATED")
        self.assertIsNone(joined["observations"][0]["settled_outcome"])

    def test_model_history_after_quote_is_rejected_as_lookahead(self):
        joined = self._join(
            model_rows=[_model(history_asof="2026-08-23T23:46:00+00:00")]
        )
        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertIn("history_asof_ts must be at or before quote_ts", joined["failures"][0]["reason"])

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

    def test_duplicate_settlement_identity_fails_closed(self):
        settlement = _settlement()
        joined = self._join(settlement_rows=[settlement, dict(settlement)])
        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertIn("SETTLEMENT_EVIDENCE_AMBIGUOUS", joined["failures"][0]["reason"])

    def test_unresolved_player_identity_fails_closed(self):
        joined = self._join(player_candidates_by_game={"999": []})
        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertIn("PLAYER_NOT_FOUND", joined["failures"][0]["reason"])

    def test_observation_ambiguity_excludes_row_instead_of_scoring(self):
        joined = self._join(
            settlement_rows=[_settlement(ambiguity_reasons=["RAIN_SHORTENED_RULE_UNRESOLVED"])]
        )
        row = joined["observations"][0]
        self.assertEqual(row["settlement_state"], "AMBIGUOUS_SETTLEMENT")
        self.assertIsNone(row["settled_outcome"])

    def test_validated_void_excludes_row_instead_of_scoring(self):
        joined = self._join(settlement_rows=[_settlement(void_reasons=["DID_NOT_START"])] )
        row = joined["observations"][0]
        self.assertEqual(row["settlement_state"], "VOID")
        self.assertIsNone(row["settled_outcome"])

    def test_either_pitcher_market_remains_ambiguous_until_dedicated_interpreter_exists(self):
        quote = _quote(market="EITHER_PITCHER_ER", entity_name="Either Pitcher", line=2.5)
        archive = _archive(quote=quote)
        model = _model(market="EITHER_PITCHER_ER", entity_id="701|702", line=2.5)
        settlement = _settlement(market="EITHER_PITCHER_ER", entity_id="701|702", line=2.5)
        joined = self._join(
            archive_payload=archive,
            model_rows=[model],
            settlement_rows=[settlement],
        )
        self.assertEqual(joined["joined_observation_count"], 1)
        row = joined["observations"][0]
        self.assertEqual(row["entity_id"], "701|702")
        self.assertEqual(row["settlement_state"], "AMBIGUOUS_SETTLEMENT")
        self.assertIsNone(row["settled_outcome"])

    def test_provider_event_id_must_match_hashed_event_snapshot(self):
        archive = _archive()
        archive["quotes"][0]["provider_event_id"] = "456"
        _rehash_archive(archive)

        joined = self._join(archive_payload=archive)

        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertEqual(joined["failure_count"], 1)
        self.assertIn("PROVIDER_EVENT_ID_SNAPSHOT_MISMATCH", joined["failures"][0]["reason"])
        self.assertNotIn("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])

    def test_archived_first_pitch_must_match_hashed_event_snapshot(self):
        archive = _archive()
        archive["quotes"][0]["first_pitch_at"] = "2026-08-24T01:00:00+00:00"
        _rehash_archive(archive)

        joined = self._join(archive_payload=archive)

        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertEqual(joined["failure_count"], 1)
        self.assertIn("ARCHIVED_FIRST_PITCH_EVENT_MISMATCH", joined["failures"][0]["reason"])
        self.assertNotIn("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])

    def test_rehashed_post_first_pitch_count_quote_cannot_hide_behind_shifted_archive_time(self):
        archive = _archive()
        quote = archive["quotes"][0]
        quote["retrieved_at"] = "2026-08-24T00:20:00+00:00"
        quote["quote_retrieved_at"] = "2026-08-24T00:20:00+00:00"
        quote["first_pitch_at"] = "2026-08-24T01:00:00+00:00"
        _rehash_archive(archive)

        joined = self._join(
            archive_payload=archive,
            model_rows=[_model(history_asof="2026-08-24T00:00:00+00:00")],
            settlement_rows=[],
        )

        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertEqual(joined["failure_count"], 1)
        self.assertIn("QUOTE_NOT_PREGAME_CANONICAL", joined["failures"][0]["reason"])
        self.assertNotIn("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
