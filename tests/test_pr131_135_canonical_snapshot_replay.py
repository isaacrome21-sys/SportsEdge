import unittest

from sportsedge.mlb_additional_pit_joiner import join_additional_archive
from sportsedge.mlb_pit_observation import content_sha256


SYNTHETIC = "SYNTHETIC_CONTRACT_TEST"
FIRST_PITCH = "2026-08-24T00:30:00+00:00"
QUOTE_TS = "2026-08-24T00:00:00+00:00"


def _game():
    return {
        "game_id": "999",
        "away_name": "Away Team",
        "home_name": "Home Team",
        "away_team_id": "10",
        "home_team_id": "20",
        "first_pitch_ts": FIRST_PITCH,
        "away_probable_pitcher_id": "701",
        "home_probable_pitcher_id": "702",
    }


def _event():
    return {
        "id": "event-1",
        "away_team": "Away Team",
        "home_team": "Home Team",
        "commence_time": FIRST_PITCH,
    }


def _snapshot():
    return {
        "game_id": "999",
        "first_pitch_at": FIRST_PITCH,
        "away_team_id": 10,
        "away_team_name": "Away Team",
        "home_team_id": 20,
        "home_team_name": "Home Team",
        "away_probable_pitcher_id": 701,
        "home_probable_pitcher_id": 702,
    }


def _binding_for_quote(quote):
    return {
        "provider_event_id": str(quote.get("provider_event_id") or ""),
        "provider_event_sha256": str(quote.get("provider_event_sha256") or ""),
        "canonical_game_id": str(quote.get("game_id") or ""),
        "canonical_entity_id": str(quote.get("entity_id") or ""),
        "canonical_game_snapshot_sha256": str(
            quote.get("canonical_game_snapshot_sha256") or ""
        ),
        "resolver_contract": "EXACT_NORMALIZED_TEAM_TIME_AND_PARTICIPANT_IDENTITY",
    }


def _rehash_archive(payload):
    payload.pop("payload_sha256", None)
    payload["payload_sha256"] = content_sha256(payload)
    return payload


def _rehash_quote_identity(payload):
    quote = payload["quotes"][0]
    quote["canonical_game_snapshot_sha256"] = content_sha256(
        quote["canonical_game_snapshot"]
    )
    quote["identity_binding_sha256"] = content_sha256(_binding_for_quote(quote))
    return _rehash_archive(payload)


def _archive_with_snapshot(snapshot):
    event = _event()
    event_hash = content_sha256(event)
    snapshot_hash = content_sha256(snapshot)
    binding = {
        "provider_event_id": "event-1",
        "provider_event_sha256": event_hash,
        "canonical_game_id": "999",
        "canonical_entity_id": "999",
        "canonical_game_snapshot_sha256": snapshot_hash,
        "resolver_contract": "EXACT_NORMALIZED_TEAM_TIME_AND_PARTICIPANT_IDENTITY",
    }
    quote = {
        "game_id": "999",
        "period": "1ST",
        "market": "NRFI",
        "entity_id": "999",
        "side": "YES",
        "line": 0.0,
        "book_key": "draftkings",
        "sportsbook": "DraftKings",
        "retrieved_at": QUOTE_TS,
        "quote_retrieved_at": QUOTE_TS,
        "first_pitch_at": FIRST_PITCH,
        "american_odds": -110,
        "ttl_seconds": 300,
        "is_alternate": False,
        "raw_market_name": "adversarial_snapshot_replay",
        "provider_event_id": "event-1",
        "pit_eligible": True,
        "provider_event_snapshot": event,
        "provider_event_sha256": event_hash,
        "canonical_game_snapshot": dict(snapshot),
        "canonical_game_snapshot_sha256": snapshot_hash,
        "identity_binding_sha256": content_sha256(binding),
    }
    payload = {
        "schema_version": 1,
        "archive_type": "MLB_ADDITIONAL_PIT_QUOTES",
        "evidence_class": SYNTHETIC,
        "provider": "THE_ODDS_API",
        "captured_at": "2026-08-24T00:01:00+00:00",
        "target_markets": ["NRFI"],
        "quotes": [quote],
    }
    payload["payload_sha256"] = content_sha256(payload)
    return payload


def _join(payload, *, game=None):
    return join_additional_archive(
        archive_payload=payload,
        game_candidates=[game or _game()],
        player_candidates_by_game={"999": []},
        model_rows=[],
        official_fact_reports=[],
        settlement_rows=[],
    )


class PR131135CanonicalSnapshotReplayTests(unittest.TestCase):
    def test_rehashed_non_id_snapshot_tamper_is_rejected_at_identity_layer(self):
        snapshot = _snapshot()
        snapshot["away_team_id"] = 777
        joined = _join(_archive_with_snapshot(snapshot))

        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertEqual(joined["failure_count"], 1)
        self.assertIn(
            "CANONICAL_GAME_SNAPSHOT_REPRODUCTION_MISMATCH:away_team_id",
            joined["failures"][0]["reason"],
        )
        self.assertNotIn("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])

    def test_untampered_snapshot_passes_identity_layer(self):
        joined = _join(_archive_with_snapshot(_snapshot()))

        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertEqual(joined["failure_count"], 1)
        self.assertIn("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])
        self.assertNotIn("CANONICAL_GAME_SNAPSHOT_REPRODUCTION_MISMATCH", joined["failures"][0]["reason"])

    def test_probable_pitcher_change_does_not_break_game_identity_replay(self):
        game = _game()
        game["away_probable_pitcher_id"] = "799"
        game["home_probable_pitcher_id"] = "899"
        joined = _join(_archive_with_snapshot(_snapshot()), game=game)

        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertEqual(joined["failure_count"], 1)
        self.assertIn("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])
        self.assertNotIn("CANONICAL_GAME_SNAPSHOT_REPRODUCTION_MISMATCH", joined["failures"][0]["reason"])

    def test_small_first_pitch_shift_uses_existing_event_binding_tolerance(self):
        game = _game()
        game["first_pitch_ts"] = "2026-08-24T01:00:00+00:00"
        joined = _join(_archive_with_snapshot(_snapshot()), game=game)

        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertEqual(joined["failure_count"], 1)
        self.assertIn("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])
        self.assertNotIn("CANONICAL_GAME_SNAPSHOT_REPRODUCTION_MISMATCH", joined["failures"][0]["reason"])

    def test_provider_event_id_must_match_hashed_snapshot_id(self):
        payload = _archive_with_snapshot(_snapshot())
        quote = payload["quotes"][0]
        quote["provider_event_id"] = "event-other"
        quote["identity_binding_sha256"] = content_sha256(_binding_for_quote(quote))
        _rehash_archive(payload)

        joined = _join(payload)

        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertEqual(joined["failure_count"], 1)
        self.assertIn(
            "PROVIDER_EVENT_ID_SNAPSHOT_MISMATCH",
            joined["failures"][0]["reason"],
        )
        self.assertNotIn("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])

    def test_rehashed_post_first_pitch_quote_cannot_hide_behind_shifted_snapshot(self):
        payload = _archive_with_snapshot(_snapshot())
        quote = payload["quotes"][0]
        quote["retrieved_at"] = "2026-08-24T01:00:00+00:00"
        quote["quote_retrieved_at"] = "2026-08-24T01:00:00+00:00"
        quote["first_pitch_at"] = "2026-08-24T01:30:00+00:00"
        quote["canonical_game_snapshot"]["first_pitch_at"] = "2026-08-24T01:30:00+00:00"
        _rehash_quote_identity(payload)

        joined = _join(payload)

        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertEqual(joined["failure_count"], 1)
        self.assertIn("QUOTE_NOT_PREGAME_CANONICAL", joined["failures"][0]["reason"])
        self.assertNotIn("MODEL_ROW_NOT_FOUND_OR_AMBIGUOUS", joined["failures"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
