import unittest

from sportsedge.mlb_acceptance_matrix import build_acceptance_matrix
from sportsedge.mlb_settlement_evidence import (
    batter_fact,
    build_settlement_report,
    classify_observation_settlement,
    official_fact_coverage,
    pitcher_fact,
    validate_book_rules,
)


def _facts():
    return {
        "game_pk": "synthetic-game",
        "status": "Final",
        "source": "SYNTHETIC_CONTRACT_TEST",
        "game": {"away_runs": 3, "home_runs": 5, "run_diff_home": 2, "total_runs": 8},
        "f5": {"away_runs": 2, "home_runs": 2, "run_diff_home": 0, "total_runs": 4},
        "first_inning": {"away_runs": 0, "home_runs": 1, "nrfi": 0, "yrfi": 1},
        "first_home_run": {
            "occurred": False,
            "batter_id": None,
            "sequence": None,
            "at_bat_index": None,
            "inning": None,
            "half_inning": None,
        },
        "winning_pitcher": {"pitcher_id": "p1"},
        "batters": [
            {
                "player_id": "b1",
                "plate_appearances": 5,
                "hits": 2,
                "singles": 1,
                "doubles": 1,
                "triples": 0,
                "home_runs": 0,
                "total_bases": 3,
                "rbi": 2,
                "runs": 1,
                "walks": 1,
                "strikeouts": 1,
                "stolen_bases": 1,
                "extra_base_hits": 1,
                "hits_runs_rbis": 5,
                "hits_runs_stolen_bases": 4,
                "runs_rbis": 3,
                "hits_stolen_bases": 3,
                "hits_walks_stolen_bases": 4,
            }
        ],
        "pitchers": [
            {
                "player_id": "p1",
                "walks": 2,
                "walks_allowed": 2,
                "strikeouts": 7,
                "hits_allowed": 5,
                "earned_runs": 2,
                "outs": 18,
                "hits_walks_er": 9,
            },
            {
                "player_id": "p2",
                "walks": 1,
                "walks_allowed": 1,
                "strikeouts": 5,
                "hits_allowed": 6,
                "earned_runs": 3,
                "outs": 15,
                "hits_walks_er": 10,
            },
        ],
    }


def _validated_rule_record(rule):
    return {
        "status": "VALIDATED",
        "sportsbook": "SYNTHETIC_BOOK",
        "source_sha256": "a" * 64,
        "captured_at_utc": "2026-08-24T12:00:00+00:00",
        "source_locator": f"synthetic://{rule}",
    }


class MLBSettlementEvidenceTests(unittest.TestCase):
    def test_official_fact_coverage_is_exactly_all_36_markets(self):
        coverage = official_fact_coverage(_facts())
        self.assertEqual(len(coverage), 36)
        self.assertEqual(set(coverage), {row["market"] for row in build_acceptance_matrix()["markets"]})
        self.assertTrue(all(row["state"] == "OFFICIAL_FACTS_PROVEN" for row in coverage.values()))

    def test_default_report_proves_facts_but_not_book_settlement(self):
        report = build_settlement_report(
            _facts(),
            source="SYNTHETIC_CONTRACT_TEST",
            evidence_class="SYNTHETIC_CONTRACT_TEST",
            generated_at_utc="2026-08-24T12:00:00+00:00",
        )
        self.assertEqual(report["market_count"], 36)
        self.assertEqual(report["official_fact_market_count"], 36)
        self.assertEqual(report["official_facts_state"], "OFFICIAL_FACTS_PROVEN")
        self.assertEqual(report["book_settlement_validated_market_count"], 0)
        self.assertEqual(report["book_settlement_state"], "BOOK_SETTLEMENT_UNVALIDATED")
        self.assertEqual(report["settlement_semantics_validation_gate"], "MISSING")
        self.assertFalse(report["counts_as_settlement_semantics_evidence"])
        self.assertFalse(report["sportsbook_data_used"])

    def test_synthetic_fixture_can_never_become_durable_settlement_evidence(self):
        rules = set()
        for row in build_acceptance_matrix()["markets"]:
            rules.update(row["requirements"]["settlement_semantics"])
        rule_evidence = {rule: _validated_rule_record(rule) for rule in rules}
        report = build_settlement_report(
            _facts(),
            source="SYNTHETIC_CONTRACT_TEST",
            evidence_class="SYNTHETIC_CONTRACT_TEST",
            generated_at_utc="2026-08-24T12:00:00+00:00",
            book_rule_evidence=rule_evidence,
        )
        self.assertEqual(report["book_settlement_state"], "BOOK_SETTLEMENT_VALIDATED")
        self.assertEqual(report["settlement_semantics_validation_gate"], "MISSING")
        self.assertFalse(report["counts_as_settlement_semantics_evidence"])

    def test_book_rule_validation_requires_hash_source_sportsbook_and_timestamp(self):
        ok, missing = validate_book_rules(
            ["RULE_A", "RULE_B"],
            {"RULE_A": _validated_rule_record("RULE_A")},
        )
        self.assertFalse(ok)
        self.assertEqual(missing, ["RULE_B"])
        ok2, missing2 = validate_book_rules(
            ["RULE_A"],
            {"RULE_A": _validated_rule_record("RULE_A")},
        )
        self.assertTrue(ok2)
        self.assertEqual(missing2, [])

    def test_observation_ambiguity_fails_closed_even_after_rules_validate(self):
        self.assertEqual(
            classify_observation_settlement(
                official_fact_state="OFFICIAL_FACTS_PROVEN",
                book_rules_validated=True,
                ambiguity_reasons=["PITCHER_REMOVED_FOR_INJURY"],
            ),
            "AMBIGUOUS_SETTLEMENT",
        )
        self.assertEqual(
            classify_observation_settlement(
                official_fact_state="OFFICIAL_FACTS_PROVEN",
                book_rules_validated=True,
                ambiguity_reasons=["RAIN_SHORTENED_GAME"],
            ),
            "AMBIGUOUS_SETTLEMENT",
        )

    def test_missing_book_rules_blocks_before_any_settlement_guess(self):
        self.assertEqual(
            classify_observation_settlement(
                official_fact_state="OFFICIAL_FACTS_PROVEN",
                book_rules_validated=False,
                ambiguity_reasons=[],
            ),
            "BOOK_SETTLEMENT_UNVALIDATED",
        )

    def test_batter_fact_preserves_all_new_combo_arithmetic(self):
        row = batter_fact(
            "b1",
            {
                "plateAppearances": 5,
                "hits": 3,
                "doubles": 1,
                "triples": 0,
                "homeRuns": 1,
                "rbi": 4,
                "runs": 2,
                "baseOnBalls": 1,
                "strikeOuts": 1,
                "stolenBases": 1,
            },
        )
        self.assertEqual(row["singles"], 1)
        self.assertEqual(row["extra_base_hits"], 2)
        self.assertEqual(row["total_bases"], 7)
        self.assertEqual(row["hits_runs_rbis"], 9)
        self.assertEqual(row["hits_runs_stolen_bases"], 6)
        self.assertEqual(row["runs_rbis"], 6)
        self.assertEqual(row["hits_stolen_bases"], 4)
        self.assertEqual(row["hits_walks_stolen_bases"], 5)

    def test_pitcher_fact_preserves_combo_arithmetic_and_out_support(self):
        row = pitcher_fact(
            "p1",
            {
                "baseOnBalls": 2,
                "strikeOuts": 8,
                "hits": 6,
                "earnedRuns": 3,
                "inningsPitched": "6.2",
            },
        )
        self.assertEqual(row["outs"], 20)
        self.assertEqual(row["walks_allowed"], 2)
        self.assertEqual(row["hits_walks_er"], 11)

    def test_no_home_run_is_valid_official_fact_not_missing_data(self):
        coverage = official_fact_coverage(_facts())
        self.assertEqual(coverage["FIRST_HOME_RUN"]["state"], "OFFICIAL_FACTS_PROVEN")


if __name__ == "__main__":
    unittest.main()
