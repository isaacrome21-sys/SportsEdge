import hashlib
import unittest

from sportsedge.mlb_acceptance_matrix import build_acceptance_matrix
from sportsedge.mlb_additional_pit_joiner import join_additional_archive
from sportsedge.mlb_pit_archive_router import join_mlb_pit_archive
from sportsedge.mlb_pit_joiner import observation_key
from sportsedge.mlb_pit_observation import analyze_pit_observations, content_sha256
from sportsedge.mlb_settlement_evidence import canonical_bytes

SYNTHETIC = "SYNTHETIC_CONTRACT_TEST"
QUOTE_TS = "2026-08-24T00:00:00+00:00"
FIRST_PITCH = "2026-08-24T00:30:00+00:00"


def game():
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


def event():
    return {
        "id": "odds-event-1",
        "away_team": "Away Team",
        "home_team": "Home Team",
        "commence_time": FIRST_PITCH,
    }


def canonical_snapshot():
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


def quote(*, market, entity_id, side, line=0.0, provider_participant_name=None):
    ev = event()
    snap = canonical_snapshot()
    ev_hash = content_sha256(ev)
    snap_hash = content_sha256(snap)
    binding = {
        "provider_event_id": "odds-event-1",
        "provider_event_sha256": ev_hash,
        "canonical_game_id": "999",
        "canonical_entity_id": str(entity_id),
        "canonical_game_snapshot_sha256": snap_hash,
        "resolver_contract": "EXACT_NORMALIZED_TEAM_TIME_AND_PARTICIPANT_IDENTITY",
    }
    row = {
        "game_id": "999",
        "period": "F5" if market.startswith("F5_") else ("1ST" if market in {"NRFI", "YRFI"} else "FG"),
        "market": market,
        "entity_id": str(entity_id),
        "side": side,
        "line": line,
        "book_key": "draftkings",
        "sportsbook": "DraftKings",
        "retrieved_at": QUOTE_TS,
        "quote_retrieved_at": QUOTE_TS,
        "first_pitch_at": FIRST_PITCH,
        "is_alternate": False,
        "raw_market_name": "fixture",
        "american_odds": -110,
        "ttl_seconds": 300,
        "provider_event_id": "odds-event-1",
        "pit_eligible": True,
        "provider_event_snapshot": ev,
        "provider_event_sha256": ev_hash,
        "canonical_game_snapshot": snap,
        "canonical_game_snapshot_sha256": snap_hash,
        "identity_binding_sha256": content_sha256(binding),
    }
    if provider_participant_name is not None:
        row["provider_participant_name"] = provider_participant_name
        row["provider_participant_name_normalized"] = "".join(
            ch.lower() for ch in provider_participant_name if ch.isalnum()
        )
    return row


def archive(q, *, source_class=SYNTHETIC):
    payload = {
        "schema_version": 1,
        "archive_type": "MLB_ADDITIONAL_PIT_QUOTES",
        "evidence_class": source_class,
        "provider": "THE_ODDS_API",
        "captured_at": "2026-08-24T00:01:00+00:00",
        "target_markets": [q["market"]],
        "quotes": [q],
    }
    payload["payload_sha256"] = content_sha256(payload)
    return payload


def model(*, market, entity_id, side, line=0.0, evidence_class=SYNTHETIC):
    return {
        "game_id": "999",
        "market": market,
        "entity_id": str(entity_id),
        "line": line,
        "side": side,
        "evidence_class": evidence_class,
        "history_asof_ts": "2026-08-23T23:55:00+00:00",
        "history_source_hash": "4" * 64,
        "model_input_hash": "5" * 64,
        "candidate_p": 0.60,
        "incumbent_p": None,
    }


def facts(*, evidence_class=SYNTHETIC):
    payload = {
        "game_pk": "999",
        "status": "Final",
        "f5": {"away_runs": 1, "home_runs": 3},
        "first_inning": {"away_runs": 0, "home_runs": 0, "nrfi": True, "yrfi": False},
        "first_home_run": {"occurred": True, "batter_id": "301"},
        "winning_pitcher": {"pitcher_id": "702"},
        "batters": [],
        "pitchers": [],
    }
    return {
        "evidence_class": evidence_class,
        "facts_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
        "facts": payload,
    }


def required_rules(market):
    for row in build_acceptance_matrix()["markets"]:
        if row["market"] == market:
            return tuple(row["requirements"]["settlement_semantics"])
    raise AssertionError(market)


def rules(market, sportsbook="DraftKings"):
    return {
        rule: {
            "status": "VALIDATED",
            "sportsbook": sportsbook,
            "source_sha256": hashlib.sha256(rule.encode()).hexdigest(),
            "captured_at_utc": "2026-08-23T20:00:00+00:00",
            "source_locator": f"fixture://{rule}",
        }
        for rule in required_rules(market)
    }


def settlement(*, market, entity_id, side, line=0.0, evidence_class=SYNTHETIC):
    key = observation_key(
        game_id="999",
        market=market,
        entity_id=str(entity_id),
        line=line,
        side=side,
        book_key="draftkings",
        quote_ts=QUOTE_TS,
    )
    return {
        "observation_key": key,
        "evidence_class": evidence_class,
        "book_rule_evidence": rules(market),
        "ambiguity_reasons": [],
        "void_reasons": [],
    }


def players():
    return {
        "999": [
            {"player_id": "301", "player_name": "Batter A"},
            {"player_id": "701", "player_name": "Away Pitcher"},
            {"player_id": "702", "player_name": "Home Pitcher"},
        ]
    }


def join_case(*, market, entity_id, side, line=0.0, provider_participant_name=None,
              source_class=SYNTHETIC, model_class=SYNTHETIC,
              fact_class=SYNTHETIC, rule_class=SYNTHETIC):
    q = quote(
        market=market,
        entity_id=entity_id,
        side=side,
        line=line,
        provider_participant_name=provider_participant_name,
    )
    return join_additional_archive(
        archive_payload=archive(q, source_class=source_class),
        game_candidates=[game()],
        player_candidates_by_game=players(),
        model_rows=[model(market=market, entity_id=entity_id, side=side, line=line, evidence_class=model_class)],
        official_fact_reports=[facts(evidence_class=fact_class)],
        settlement_rows=[settlement(market=market, entity_id=entity_id, side=side, line=line, evidence_class=rule_class)],
    )


class AdditionalPITJoinerTests(unittest.TestCase):
    def test_f5_moneyline_and_run_line_and_total_derive_outcomes(self):
        ml = join_case(market="F5_MONEYLINE", entity_id="20", side="HOME")
        self.assertEqual(ml["observations"][0]["settled_outcome"], "WIN")
        rl = join_case(market="F5_RUN_LINE", entity_id="20", side="HOME", line=-1.5)
        self.assertEqual(rl["observations"][0]["settled_outcome"], "WIN")
        total = join_case(market="F5_TOTALS", entity_id="999", side="UNDER", line=4.0)
        self.assertEqual(total["observations"][0]["settled_outcome"], "PUSH")

    def test_nrfi_and_yrfi_are_derived_from_first_inning_facts(self):
        nrfi = join_case(market="NRFI", entity_id="999", side="YES")
        yrfi = join_case(market="YRFI", entity_id="999", side="YES")
        self.assertEqual(nrfi["observations"][0]["settled_outcome"], "WIN")
        self.assertEqual(yrfi["observations"][0]["settled_outcome"], "LOSS")

    def test_old_binary_archive_without_raw_provider_name_is_ambiguous_even_on_direct_join(self):
        first_hr = join_case(market="FIRST_HOME_RUN", entity_id="301", side="YES")
        pitcher = join_case(market="PITCHER_RECORD_WIN", entity_id="701", side="NO")
        for joined in (first_hr, pitcher):
            row = joined["observations"][0]
            self.assertEqual(row["settlement_state"], "AMBIGUOUS_SETTLEMENT")
            self.assertIsNone(row["settled_outcome"])

    def test_future_binary_archive_with_raw_provider_name_derives_outcome(self):
        first_hr = join_case(
            market="FIRST_HOME_RUN", entity_id="301", side="YES",
            provider_participant_name="Batter A",
        )
        pitcher = join_case(
            market="PITCHER_RECORD_WIN", entity_id="701", side="NO",
            provider_participant_name="Away Pitcher",
        )
        self.assertEqual(first_hr["observations"][0]["settled_outcome"], "WIN")
        self.assertEqual(pitcher["observations"][0]["settled_outcome"], "WIN")

    def test_wrong_raw_provider_name_cannot_reproduce_binary_identity(self):
        joined = join_case(
            market="FIRST_HOME_RUN", entity_id="301", side="YES",
            provider_participant_name="Wrong Player",
        )
        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertIn("PROVIDER_PARTICIPANT_IDENTITY_NOT_REPRODUCIBLE", joined["failures"][0]["reason"])

    def test_tampered_provider_event_is_rejected(self):
        q = quote(market="NRFI", entity_id="999", side="YES")
        payload = archive(q)
        payload["quotes"][0]["provider_event_snapshot"]["home_team"] = "Tampered"
        payload["payload_sha256"] = content_sha256({k: v for k, v in payload.items() if k != "payload_sha256"})
        joined = join_additional_archive(
            archive_payload=payload,
            game_candidates=[game()],
            player_candidates_by_game={"999": []},
            model_rows=[model(market="NRFI", entity_id="999", side="YES")],
            official_fact_reports=[facts()],
            settlement_rows=[settlement(market="NRFI", entity_id="999", side="YES")],
        )
        self.assertEqual(joined["joined_observation_count"], 0)
        self.assertIn("PROVIDER_EVENT_HASH_MISMATCH", joined["failures"][0]["reason"])

    def test_full_live_chain_can_be_durable_for_non_player_additional_market(self):
        joined = join_case(
            market="NRFI",
            entity_id="999",
            side="YES",
            source_class="LIVE_PROVIDER_QUOTE_ARCHIVE",
            model_class="LIVE_PIT_MODEL",
            fact_class="LIVE_OFFICIAL_FACT_PROBE",
            rule_class="LIVE_BOOK_RULE_CAPTURE",
        )
        report = analyze_pit_observations(joined["observations"])
        self.assertTrue(report["counts_as_historical_pit"])
        self.assertEqual(report["durable_scored_row_count"], 1)

    def test_full_live_binary_chain_requires_raw_provider_name_for_durability(self):
        old = join_case(
            market="FIRST_HOME_RUN", entity_id="301", side="YES",
            source_class="LIVE_PROVIDER_QUOTE_ARCHIVE",
            model_class="LIVE_PIT_MODEL",
            fact_class="LIVE_OFFICIAL_FACT_PROBE",
            rule_class="LIVE_BOOK_RULE_CAPTURE",
        )
        old_report = analyze_pit_observations(old["observations"])
        self.assertFalse(old_report["counts_as_historical_pit"])

        future = join_case(
            market="FIRST_HOME_RUN", entity_id="301", side="YES",
            provider_participant_name="Batter A",
            source_class="LIVE_PROVIDER_QUOTE_ARCHIVE",
            model_class="LIVE_PIT_MODEL",
            fact_class="LIVE_OFFICIAL_FACT_PROBE",
            rule_class="LIVE_BOOK_RULE_CAPTURE",
        )
        future_report = analyze_pit_observations(future["observations"])
        self.assertTrue(future_report["counts_as_historical_pit"])

    def test_router_dispatches_additional_archive(self):
        q = quote(market="NRFI", entity_id="999", side="YES")
        joined = join_mlb_pit_archive(
            archive_payload=archive(q),
            game_candidates=[game()],
            player_candidates_by_game={"999": []},
            model_rows=[model(market="NRFI", entity_id="999", side="YES")],
            official_fact_reports=[facts()],
            settlement_rows=[settlement(market="NRFI", entity_id="999", side="YES")],
        )
        self.assertEqual(joined["archive_type"], "MLB_ADDITIONAL_PIT_QUOTES")
        self.assertEqual(joined["joined_observation_count"], 1)


if __name__ == "__main__":
    unittest.main()
