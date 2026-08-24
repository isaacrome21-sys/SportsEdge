import hashlib
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge.mlb_acceptance_matrix import build_acceptance_matrix
from sportsedge.mlb_pit_archive_router import join_mlb_pit_archive, F5_TIE_POLICY_AMBIGUITY
from sportsedge.mlb_pit_joiner import observation_key
from sportsedge.mlb_pit_observation import content_sha256
from sportsedge.mlb_run_machine import run_mlb_machine
from sportsedge.mlb_settlement_evidence import canonical_bytes

NOW = datetime(2026, 8, 24, 14, 30, tzinfo=timezone.utc)
SYNTHETIC = "SYNTHETIC_CONTRACT_TEST"
QUOTE_TS = "2026-08-24T00:00:00+00:00"
FIRST_PITCH = "2026-08-24T00:30:00+00:00"


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


def _additional_quote(*, market="NRFI", entity_id="999", side="YES", line=0.0):
    event = _event()
    event_hash = content_sha256(event)
    snapshot = {
        "game_id": "999",
        "first_pitch_at": FIRST_PITCH,
        "away_team_id": 10,
        "away_team_name": "Away Team",
        "home_team_id": 20,
        "home_team_name": "Home Team",
        "away_probable_pitcher_id": 701,
        "home_probable_pitcher_id": 702,
    }
    snapshot_hash = content_sha256(snapshot)
    binding = {
        "provider_event_id": "event-1",
        "provider_event_sha256": event_hash,
        "canonical_game_id": "999",
        "canonical_entity_id": str(entity_id),
        "canonical_game_snapshot_sha256": snapshot_hash,
        "resolver_contract": "EXACT_NORMALIZED_TEAM_TIME_AND_PARTICIPANT_IDENTITY",
    }
    return {
        "game_id": "999",
        "market": market,
        "entity_id": str(entity_id),
        "side": side,
        "line": line,
        "book_key": "draftkings",
        "sportsbook": "DraftKings",
        "retrieved_at": QUOTE_TS,
        "quote_retrieved_at": QUOTE_TS,
        "first_pitch_at": FIRST_PITCH,
        "pit_eligible": True,
        "provider_event_id": "event-1",
        "provider_event_snapshot": event,
        "provider_event_sha256": event_hash,
        "canonical_game_snapshot": snapshot,
        "canonical_game_snapshot_sha256": snapshot_hash,
        "identity_binding_sha256": content_sha256(binding),
    }


def _archive(quote):
    payload = {
        "schema_version": 1,
        "archive_type": "MLB_ADDITIONAL_PIT_QUOTES",
        "evidence_class": SYNTHETIC,
        "provider": "THE_ODDS_API",
        "captured_at": "2026-08-24T00:01:00+00:00",
        "target_markets": [quote["market"]],
        "quotes": [quote],
    }
    payload["payload_sha256"] = content_sha256(payload)
    return payload


def _model(*, market, entity_id, side, line=0.0):
    return {
        "game_id": "999",
        "market": market,
        "entity_id": str(entity_id),
        "line": line,
        "side": side,
        "evidence_class": SYNTHETIC,
        "history_asof_ts": "2026-08-23T23:55:00+00:00",
        "history_source_hash": "4" * 64,
        "model_input_hash": "5" * 64,
        "candidate_p": 0.60,
        "incumbent_p": None,
    }


def _required_rules(market):
    for row in build_acceptance_matrix()["markets"]:
        if row["market"] == market:
            return tuple(row["requirements"]["settlement_semantics"])
    raise AssertionError(market)


def _settlement(*, market, entity_id, side, line=0.0):
    key = observation_key(
        game_id="999",
        market=market,
        entity_id=str(entity_id),
        line=line,
        side=side,
        book_key="draftkings",
        quote_ts=QUOTE_TS,
    )
    evidence = {
        rule: {
            "status": "VALIDATED",
            "sportsbook": "DraftKings",
            "source_sha256": hashlib.sha256(rule.encode()).hexdigest(),
            "captured_at_utc": "2026-08-23T20:00:00+00:00",
            "source_locator": f"fixture://{rule}",
        }
        for rule in _required_rules(market)
    }
    return {
        "observation_key": key,
        "evidence_class": SYNTHETIC,
        "book_rule_evidence": evidence,
        "ambiguity_reasons": [],
        "void_reasons": [],
    }


def _facts(*, f5_away=1, f5_home=3):
    facts = {
        "game_pk": "999",
        "status": "Final",
        "f5": {"away_runs": f5_away, "home_runs": f5_home},
        "first_inning": {"away_runs": 0, "home_runs": 0, "nrfi": True, "yrfi": False},
        "first_home_run": {"occurred": False},
        "winning_pitcher": {"pitcher_id": "702"},
        "batters": [],
        "pitchers": [],
    }
    return {
        "evidence_class": SYNTHETIC,
        "facts_sha256": hashlib.sha256(canonical_bytes(facts)).hexdigest(),
        "facts": facts,
    }


class PR131133CompositionTests(unittest.TestCase):
    def test_additional_archive_enters_canonical_pit_router(self):
        quote = _additional_quote(market="NRFI", entity_id="999", side="YES")
        joined = join_mlb_pit_archive(
            archive_payload=_archive(quote),
            game_candidates=[_game()],
            player_candidates_by_game={"999": []},
            model_rows=[_model(market="NRFI", entity_id="999", side="YES")],
            official_fact_reports=[_facts()],
            settlement_rows=[_settlement(market="NRFI", entity_id="999", side="YES")],
        )
        self.assertEqual(joined["archive_type"], "MLB_ADDITIONAL_PIT_QUOTES")
        self.assertEqual(joined["joined_observation_count"], 1)
        self.assertEqual(joined["observations"][0]["settled_outcome"], "WIN")

    def test_f5_moneyline_tie_is_ambiguous_until_policy_is_normalized(self):
        quote = _additional_quote(market="F5_MONEYLINE", entity_id="20", side="HOME")
        joined = join_mlb_pit_archive(
            archive_payload=_archive(quote),
            game_candidates=[_game()],
            player_candidates_by_game={"999": []},
            model_rows=[_model(market="F5_MONEYLINE", entity_id="20", side="HOME")],
            official_fact_reports=[_facts(f5_away=2, f5_home=2)],
            settlement_rows=[_settlement(market="F5_MONEYLINE", entity_id="20", side="HOME")],
        )
        row = joined["observations"][0]
        self.assertEqual(row["settlement_state"], "AMBIGUOUS_SETTLEMENT")
        self.assertIsNone(row["settled_outcome"])
        self.assertEqual(joined["failure_count"], 0)
        self.assertEqual(F5_TIE_POLICY_AMBIGUITY, "F5_MONEYLINE_TIE_POLICY_NOT_NORMALIZED")

    @patch("sportsedge.mlb_run_machine.run_auto_mlb_native_odds")
    def test_auto_select_empty_quote_list_means_automatic(self, native):
        native.return_value = SimpleNamespace(
            slate_date_ct="2026-08-24",
            run_status="NO_QUOTES",
            results=(),
            source_failures=(),
        )
        report = run_mlb_machine(quotes=[], odds_api_key="secret", now=NOW)
        self.assertEqual(report.mode, "AUTOMATIC")
        native.assert_called_once()

    @patch("sportsedge.mlb_run_machine.run_auto_joint_mlb")
    def test_hybrid_adds_only_transport_defaults_and_preserves_line_price(self, hybrid):
        captured = {}

        def fake(**kwargs):
            with kwargs["opener"](kwargs["quote_url"]) as response:
                captured["quotes"] = json.loads(response.read())
            return SimpleNamespace(
                slate_date_ct="2026-08-24",
                run_status="PASS",
                results=(),
                source_failures=(),
            )

        hybrid.side_effect = fake
        supplied = {
            "game_id": "123",
            "market": "HITS",
            "entity_id": "301",
            "side": "OVER",
            "line": 1.5,
            "american_odds": 125,
        }
        report = run_mlb_machine(mode="HYBRID", quotes=[supplied], now=NOW)
        self.assertEqual(report.mode, "HYBRID")
        row = captured["quotes"][0]
        self.assertEqual(row["line"], 1.5)
        self.assertEqual(row["american_odds"], 125)
        self.assertEqual(row["game_id"], "123")
        self.assertEqual(row["entity_id"], "301")
        self.assertEqual(row["book_key"], "manual_input")
        self.assertEqual(row["retrieved_at"], NOW.isoformat())


if __name__ == "__main__":
    unittest.main()
