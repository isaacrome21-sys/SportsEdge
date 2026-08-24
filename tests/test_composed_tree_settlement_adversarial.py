import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge.mlb_acceptance_matrix import build_acceptance_matrix
from sportsedge.mlb_additional_pit_joiner import join_additional_archive
from sportsedge.mlb_pit_archive_router import join_mlb_pit_archive
from sportsedge.mlb_pit_joiner import MLBPITJoinError, observation_key
from sportsedge.mlb_pit_observation import content_sha256
from sportsedge.mlb_run_machine import run_mlb_machine
from sportsedge.mlb_settlement_evidence import canonical_bytes

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


def _game_snapshot():
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


def _quote(*, market, entity_id, side, line=0.0, provider_name=None):
    event = _event()
    snapshot = _game_snapshot()
    event_hash = content_sha256(event)
    snapshot_hash = content_sha256(snapshot)
    binding = {
        "provider_event_id": "event-1",
        "provider_event_sha256": event_hash,
        "canonical_game_id": "999",
        "canonical_entity_id": str(entity_id),
        "canonical_game_snapshot_sha256": snapshot_hash,
        "resolver_contract": "EXACT_NORMALIZED_TEAM_TIME_AND_PARTICIPANT_IDENTITY",
    }
    row = {
        "game_id": "999",
        "period": "F5" if market.startswith("F5_") else "FG",
        "market": market,
        "entity_id": str(entity_id),
        "side": side,
        "line": line,
        "book_key": "draftkings",
        "sportsbook": "DraftKings",
        "retrieved_at": QUOTE_TS,
        "quote_retrieved_at": QUOTE_TS,
        "first_pitch_at": FIRST_PITCH,
        "american_odds": -110,
        "ttl_seconds": 300,
        "is_alternate": False,
        "raw_market_name": "adversarial_fixture",
        "provider_event_id": "event-1",
        "pit_eligible": True,
        "provider_event_snapshot": event,
        "provider_event_sha256": event_hash,
        "canonical_game_snapshot": snapshot,
        "canonical_game_snapshot_sha256": snapshot_hash,
        "identity_binding_sha256": content_sha256(binding),
    }
    if provider_name is not None:
        row["provider_participant_name"] = provider_name
        row["provider_participant_name_normalized"] = "".join(
            ch.lower() for ch in provider_name if ch.isalnum()
        )
    return row


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


def _facts(*, f5_away=1, f5_home=3, first_hr_occurred=True, first_hr_batter="301"):
    facts = {
        "game_pk": "999",
        "status": "Final",
        "f5": {"away_runs": f5_away, "home_runs": f5_home},
        "first_inning": {"away_runs": 0, "home_runs": 0, "nrfi": True, "yrfi": False},
        "first_home_run": {
            "occurred": first_hr_occurred,
            **({"batter_id": first_hr_batter} if first_hr_occurred else {}),
        },
        "winning_pitcher": {"pitcher_id": "702"},
        "batters": [],
        "pitchers": [],
    }
    return {
        "evidence_class": SYNTHETIC,
        "facts_sha256": hashlib.sha256(canonical_bytes(facts)).hexdigest(),
        "facts": facts,
    }


def _required_rules(market):
    for row in build_acceptance_matrix()["markets"]:
        if row["market"] == market:
            return tuple(row["requirements"]["settlement_semantics"])
    raise AssertionError(market)


def _rule_evidence(market):
    return {
        rule: {
            "status": "VALIDATED",
            "sportsbook": "DraftKings",
            "source_sha256": hashlib.sha256(rule.encode()).hexdigest(),
            "captured_at_utc": "2026-08-23T20:00:00+00:00",
            "source_locator": f"fixture://{rule}",
        }
        for rule in _required_rules(market)
    }


def _settlement(*, market, entity_id, side, line=0.0):
    return {
        "observation_key": observation_key(
            game_id="999",
            market=market,
            entity_id=str(entity_id),
            line=line,
            side=side,
            book_key="draftkings",
            quote_ts=QUOTE_TS,
        ),
        "evidence_class": SYNTHETIC,
        "book_rule_evidence": _rule_evidence(market),
        "ambiguity_reasons": [],
        "void_reasons": [],
    }


def _join(*, market, entity_id, side, line=0.0, fact_report=None, provider_name=None):
    quote = _quote(
        market=market,
        entity_id=entity_id,
        side=side,
        line=line,
        provider_name=provider_name,
    )
    return join_additional_archive(
        archive_payload=_archive(quote),
        game_candidates=[_game()],
        player_candidates_by_game={
            "999": [
                {"player_id": "301", "player_name": "Batter A"},
                {"player_id": "701", "player_name": "Away Pitcher"},
                {"player_id": "702", "player_name": "Home Pitcher"},
            ]
        },
        model_rows=[_model(market=market, entity_id=entity_id, side=side, line=line)],
        official_fact_reports=[fact_report or _facts()],
        settlement_rows=[_settlement(market=market, entity_id=entity_id, side=side, line=line)],
    )


class ComposedTreeSettlementAdversarialTests(unittest.TestCase):
    def test_non_tied_f5_moneyline_still_settles_normally(self):
        joined = _join(market="F5_MONEYLINE", entity_id="20", side="HOME")
        self.assertEqual(joined["failure_count"], 0)
        row = joined["observations"][0]
        self.assertEqual(row["settlement_state"], "SETTLEMENT_ELIGIBLE")
        self.assertEqual(row["settled_outcome"], "WIN")

    def test_f5_moneyline_tie_is_ambiguous_not_push(self):
        joined = _join(
            market="F5_MONEYLINE",
            entity_id="20",
            side="HOME",
            fact_report=_facts(f5_away=2, f5_home=2),
        )
        self.assertEqual(joined["failure_count"], 0)
        row = joined["observations"][0]
        self.assertEqual(row["settlement_state"], "AMBIGUOUS_SETTLEMENT")
        self.assertIsNone(row["settled_outcome"])

    def test_first_home_run_with_actual_selected_batter_still_settles(self):
        joined = _join(
            market="FIRST_HOME_RUN",
            entity_id="301",
            side="YES",
            provider_name="Batter A",
        )
        self.assertEqual(joined["failure_count"], 0)
        row = joined["observations"][0]
        self.assertEqual(row["settlement_state"], "SETTLEMENT_ELIGIBLE")
        self.assertEqual(row["settled_outcome"], "WIN")

    def test_first_home_run_no_hr_is_ambiguous_not_inferred_no_win(self):
        joined = _join(
            market="FIRST_HOME_RUN",
            entity_id="301",
            side="NO",
            provider_name="Batter A",
            fact_report=_facts(first_hr_occurred=False),
        )
        self.assertEqual(joined["failure_count"], 0)
        row = joined["observations"][0]
        self.assertEqual(row["settlement_state"], "AMBIGUOUS_SETTLEMENT")
        self.assertIsNone(row["settled_outcome"])

    def test_router_rejects_unknown_archive_type(self):
        with self.assertRaisesRegex(MLBPITJoinError, "PIT_ARCHIVE_TYPE_UNSUPPORTED"):
            join_mlb_pit_archive(
                archive_payload={"archive_type": "NOT_REAL"},
                game_candidates=[],
                player_candidates_by_game={},
                model_rows=[],
                official_fact_reports=[],
                settlement_rows=[],
            )

    @patch("sportsedge.mlb_run_machine.run_auto_mlb_native_odds")
    def test_empty_quotes_auto_selects_automatic_and_passes_whole_keyring_once(self, native):
        native.return_value = SimpleNamespace(
            slate_date_ct="2026-08-24",
            run_status="PASS",
            results=(),
            source_failures=(),
        )
        report = run_mlb_machine(
            quotes=[],
            odds_api_key="key-one",
            odds_api_keys=("key-two", "key-three"),
        )
        self.assertEqual(report.mode, "AUTOMATIC")
        self.assertEqual(native.call_count, 1)
        kwargs = native.call_args.kwargs
        self.assertEqual(kwargs["odds_api_key"], "key-one")
        self.assertEqual(kwargs["odds_api_keys"], ("key-two", "key-three"))


if __name__ == "__main__":
    unittest.main()
