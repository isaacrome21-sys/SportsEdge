import hashlib
import json
import unittest

from sportsedge.mlb_prop_official_facts import prop_fact_from_settlement_report
from sportsedge.mlb_prop_outcome_join import bind_archived_quote, build_join_report


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


class MLBPropEvidenceChainTests(unittest.TestCase):
    """End-to-end SYNTHETIC contract fixtures only; never historical evidence."""

    def _settlement_report(self):
        facts = {
            "game_pk": "999001",
            "status": "Final",
            "pitchers": [{"player_id": "p42", "outs": 19, "earned_runs": 2}],
            "batters": [{"player_id": "b42", "rbi": 1}],
        }
        return {
            "state": "SETTLEMENT_SEMANTICS_PASS",
            "game_pk": "999001",
            "source": "SYNTHETIC_MLB_STATSAPI_FIXTURE",
            "facts_sha256": hashlib.sha256(_canonical(facts)).hexdigest(),
            "facts": facts,
        }

    def _quote(self, market="PITCHER_OUTS"):
        player_name = "sample pitcher" if market != "RBI" else "sample batter"
        return {
            "market": market,
            "provider_event_id": "dk-event-1",
            "entity_name_normalized": player_name,
            "line": 17.5 if market == "PITCHER_OUTS" else (2.5 if market == "PITCHER_ER" else 0.5),
            "side": "OVER",
            "quote_retrieved_at": "2026-08-10T18:00:00-05:00",
            "first_pitch_at": "2026-08-10T19:10:00-05:00",
        }

    def _binding(self, market="PITCHER_OUTS"):
        return {
            "provider_event_id": "dk-event-1",
            "entity_name_normalized": "sample pitcher" if market != "RBI" else "sample batter",
            "game_id": "999001",
            "entity_id": "p42" if market != "RBI" else "b42",
            "identity_binding_sha256": "d" * 64,
        }

    def _bundle(self, market="PITCHER_OUTS", settlement_state="SETTLED", reason="NORMAL_FINAL"):
        archived = self._quote(market)
        binding = self._binding(market)
        quote = bind_archived_quote(
            archived,
            binding,
            quote_archive_sha256="a" * 64,
            evidence_origin="SYNTHETIC_FIXTURE",
        )
        fact = prop_fact_from_settlement_report(
            self._settlement_report(),
            market=market,
            game_id=quote["game_id"],
            entity_id=quote["entity_id"],
        )
        settlement = {
            "market": market,
            "game_id": quote["game_id"],
            "entity_id": quote["entity_id"],
            "settlement_state": settlement_state,
            "settlement_reason": reason,
            "settlement_rule_source": "SYNTHETIC_DRAFTKINGS_RULE_FIXTURE",
            "settlement_rule_sha256": "e" * 64,
        }
        model_eval = {
            "market": market,
            "game_id": quote["game_id"],
            "entity_id": quote["entity_id"],
            "history_asof_ts": "2026-08-10T17:59:00-05:00",
            "history_source_hash": "c" * 64,
            "history_sample_size": 10,
            "model_input_sha256": "f" * 64,
            "incumbent_model_version": "synthetic_poisson_incumbent_v1",
            "challenger_model_version": "synthetic_empirical_challenger_v1",
            "incumbent_p": 0.54,
            "challenger_p": 0.62,
        }
        return {"quote": quote, "fact": fact, "settlement": settlement, "model_eval": model_eval}

    def test_complete_synthetic_chain_stays_synthetic(self):
        report = build_join_report([
            self._bundle("PITCHER_OUTS"),
            self._bundle("PITCHER_ER"),
            self._bundle("RBI"),
        ])
        self.assertEqual(report["state"], "SYNTHETIC_CONTRACT_PASS")
        self.assertEqual(report["evidence_class"], "SYNTHETIC_CONTRACT_TEST")
        self.assertEqual(report["joined_row_count"], 3)
        self.assertEqual(report["ambiguous_count"], 0)
        self.assertNotIn("HISTORICAL_PIT_VALIDATED", json.dumps(report))
        for row in report["rows"]:
            self.assertEqual(row["evidence_origin"], "SYNTHETIC_FIXTURE")
            self.assertEqual(len(row["quote_archive_sha256"]), 64)
            self.assertEqual(len(row["identity_binding_sha256"]), 64)
            self.assertEqual(len(row["facts_sha256"]), 64)
            self.assertEqual(len(row["settlement_rule_sha256"]), 64)
            self.assertEqual(len(row["history_source_hash"]), 64)
            self.assertEqual(len(row["model_input_sha256"]), 64)

    def test_complete_chain_with_ambiguous_injury_settlement_blocks(self):
        report = build_join_report([
            self._bundle(
                "PITCHER_OUTS",
                settlement_state="AMBIGUOUS",
                reason="STARTER_REMOVED_FOR_INJURY_RULE_UNRESOLVED",
            )
        ])
        self.assertEqual(report["state"], "BLOCKED_AMBIGUOUS_SETTLEMENT")
        self.assertEqual(report["evidence_class"], "UNAVAILABLE")
        self.assertEqual(report["joined_row_count"], 0)
        self.assertEqual(report["ambiguous_count"], 1)

    def test_complete_chain_with_shortened_game_ambiguity_blocks(self):
        report = build_join_report([
            self._bundle(
                "PITCHER_ER",
                settlement_state="AMBIGUOUS",
                reason="GAME_CALLED_EARLY_BOOK_RULE_UNRESOLVED",
            )
        ])
        self.assertEqual(report["state"], "BLOCKED_AMBIGUOUS_SETTLEMENT")
        self.assertEqual(report["evidence_class"], "UNAVAILABLE")


if __name__ == "__main__":
    unittest.main()
