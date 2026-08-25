import unittest

from sportsedge.mlb_acceptance_matrix import build_acceptance_matrix
from sportsedge.mlb_catalog_prediction_settlement import build_catalog_prediction_settlement_record, build_catalog_settlement_report
from sportsedge.prediction_journal import build_prediction_journal_record

SHA = "a" * 64
GAME_ID = "822696"


def _rules(sportsbook="DraftKings"):
    required = set()
    for row in build_acceptance_matrix()["markets"]: required.update(row["requirements"]["settlement_semantics"])
    return {rule: {"status": "VALIDATED", "sportsbook": sportsbook, "source_sha256": SHA, "captured_at_utc": "2026-08-25T11:30:00+00:00", "source_locator": f"fixture://{sportsbook}/{rule}"} for rule in sorted(required)}


def _facts():
    ids = {"away_team_id": "10", "home_team_id": "20"}
    return {
        "game_pk": GAME_ID, "status": "Final", "source": "MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED",
        "game": {**ids, "away_runs": 3, "home_runs": 5, "run_diff_home": 2, "total_runs": 8},
        "f5": {**ids, "away_runs": 1, "home_runs": 2, "run_diff_home": 1, "total_runs": 3},
        "first_inning": {"away_runs": 0, "home_runs": 0, "nrfi": True, "yrfi": False},
        "batters": [{"player_id": "10", "plate_appearances": 4, "hits": 2, "singles": 1, "doubles": 0, "triples": 0, "home_runs": 1, "total_bases": 5, "rbi": 2, "runs": 1, "walks": 1, "strikeouts": 1, "stolen_bases": 0, "extra_base_hits": 1, "hits_runs_rbis": 5, "hits_runs_stolen_bases": 3, "runs_rbis": 3, "hits_stolen_bases": 2, "hits_walks_stolen_bases": 3}],
        "pitchers": [
            {"player_id": "20", "walks": 2, "walks_allowed": 2, "strikeouts": 7, "hits_allowed": 4, "earned_runs": 1, "outs": 18, "hits_walks_er": 7},
            {"player_id": "21", "walks": 4, "walks_allowed": 4, "strikeouts": 5, "hits_allowed": 6, "earned_runs": 3, "outs": 15, "hits_walks_er": 13},
        ],
        "first_home_run": {"occurred": True, "batter_id": "10"}, "winning_pitcher": {"pitcher_id": "20"},
    }


def _prediction(market, entity, side, line, *, sportsbook="DraftKings"):
    row = {"source_index": 0, "game_id": GAME_ID, "market": market, "entity_id": entity, "line": line, "side": side, "american_odds": -110, "model_p": 0.55, "bet_status": "PASS", "reason": "TEST"}
    if sportsbook is not None:
        row["sportsbook"] = sportsbook; row["book_key"] = sportsbook.lower().replace(" ", "")
    if market in {"MONEYLINE", "RUN_LINE", "TOTALS", "TEAM_TOTALS", "F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS", "FIRST_HOME_RUN", "PITCHER_RECORD_WIN"}:
        row.update({"model_input_hash": SHA, "distribution_sha256": "b" * 64, "readout_sha256": "c" * 64, "readout_version": "mlb_v7_game_readout_v1"})
    if market in {"HITS", "TOTAL_BASES", "PITCHER_BB"}:
        row.update({"model_input_hash": SHA, "engine_version": "test-engine-v1", "seed_policy": "identity-derived-v1", "mc_paths": 1000})
    return row


def _journal(*rows):
    record = build_prediction_journal_record({"mode": "AUTOMATIC", "slate_date_ct": "2026-08-25", "generated_at_utc": "2026-08-25T10:00:00+00:00", "run_status": "PASS", "card_status": "PASS", "results": list(rows)})
    assert record is not None
    return record


def _report(*, sportsbook="DraftKings", evidence_class="LIVE_OFFICIAL_FACT_PROBE"):
    return build_catalog_settlement_report(_facts(), source="MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED", evidence_class=evidence_class, generated_at_utc="2026-08-25T12:00:00+00:00", book_rule_evidence=_rules(sportsbook))


class MLBCatalogPredictionSettlementTests(unittest.TestCase):
    def test_resolves_representative_market_families_including_team_totals(self):
        journal = _journal(
            _prediction("MONEYLINE", GAME_ID, "HOME", None),
            _prediction("TEAM_TOTALS", "20", "OVER", 4.5),
            _prediction("PITCHER_OUTS", "20", "OVER", 15.5), _prediction("PITCHER_K", "20", "OVER", 5.5),
            _prediction("HOME_RUNS", "10", "OVER", 0.5), _prediction("F5_TOTALS", GAME_ID, "OVER", 2.5),
            _prediction("NRFI", GAME_ID, "YES", 0.0), _prediction("FIRST_HOME_RUN", "10", "YES", 0.0),
            _prediction("PITCHER_RECORD_WIN", "20", "YES", 0.0), _prediction("HITS", "10", "OVER", 1.5),
            _prediction("TOTAL_BASES", "10", "OVER", 3.5), _prediction("PITCHER_BB", "20", "UNDER", 2.5),
        )
        record = build_catalog_prediction_settlement_record(journal, settlement_reports_by_game={GAME_ID: _report()}, settled_at_utc="2026-08-25T12:10:00+00:00")
        self.assertEqual(record["prediction_count"], 12); self.assertEqual(record["resolved_count"], 12); self.assertTrue(record["settlement_complete"])
        self.assertTrue(all(row["settlement_result"] == "WIN" for row in record["outcomes"]))

    def test_team_total_exact_team_identity_is_required(self):
        journal = _journal(_prediction("TEAM_TOTALS", "999", "OVER", 4.5))
        record = build_catalog_prediction_settlement_record(journal, settlement_reports_by_game={GAME_ID: _report()}, settled_at_utc="2026-08-25T12:10:00+00:00")
        row = record["outcomes"][0]
        self.assertEqual(row["settlement_result"], "UNRESOLVED")
        self.assertIn("TEAM_TOTAL_ENTITY_ID_NOT_IN_GAME", row["settlement_reason"])

    def test_f5_team_total_can_be_graded_from_official_f5_identity_but_model_remains_separate_gate(self):
        row = _prediction("F5_TEAM_TOTALS", "20", "UNDER", 2.5)
        journal = _journal(row)
        record = build_catalog_prediction_settlement_record(journal, settlement_reports_by_game={GAME_ID: _report()}, settled_at_utc="2026-08-25T12:10:00+00:00")
        self.assertEqual(record["outcomes"][0]["settlement_result"], "WIN")

    def test_prediction_sportsbook_must_match_validated_rule_sportsbook(self):
        journal = _journal(_prediction("PITCHER_OUTS", "20", "OVER", 15.5, sportsbook="FanDuel"))
        record = build_catalog_prediction_settlement_record(journal, settlement_reports_by_game={GAME_ID: _report(sportsbook="DraftKings")}, settled_at_utc="2026-08-25T12:10:00+00:00")
        self.assertEqual(record["outcomes"][0]["settlement_reason"], "BOOK_RULE_SPORTSBOOK_MISMATCH")

    def test_missing_prediction_sportsbook_identity_fails_closed(self):
        journal = _journal(_prediction("PITCHER_K", "20", "OVER", 5.5, sportsbook=None))
        record = build_catalog_prediction_settlement_record(journal, settlement_reports_by_game={GAME_ID: _report()}, settled_at_utc="2026-08-25T12:10:00+00:00")
        self.assertEqual(record["outcomes"][0]["settlement_reason"], "PREDICTION_SPORTSBOOK_IDENTITY_MISSING")

    def test_synthetic_evidence_never_resolves_real_prediction(self):
        journal = _journal(_prediction("HOME_RUNS", "10", "OVER", 0.5))
        record = build_catalog_prediction_settlement_record(journal, settlement_reports_by_game={GAME_ID: _report(evidence_class="SYNTHETIC_CONTRACT_TEST")}, settled_at_utc="2026-08-25T12:10:00+00:00")
        self.assertEqual(record["outcomes"][0]["settlement_reason"], "SYNTHETIC_SETTLEMENT_EVIDENCE_PROHIBITED")

    def test_either_pitcher_family_remains_unresolved_without_book_specific_semantics(self):
        journal = _journal(_prediction("EITHER_PITCHER_BB", "20|21", "OVER", 2.5))
        record = build_catalog_prediction_settlement_record(journal, settlement_reports_by_game={GAME_ID: _report()}, settled_at_utc="2026-08-25T12:10:00+00:00")
        row = record["outcomes"][0]
        self.assertEqual(row["settlement_result"], "UNRESOLVED")
        self.assertIn("EITHER_PITCHER_BOOK_SPECIFIC_SEMANTICS_REQUIRED", row["settlement_reason"])

    def test_first_home_run_no_hr_game_preserves_policy_ambiguity(self):
        facts = _facts(); facts["first_home_run"] = {"occurred": False}
        report = build_catalog_settlement_report(facts, source="MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED", generated_at_utc="2026-08-25T12:00:00+00:00", book_rule_evidence=_rules())
        journal = _journal(_prediction("FIRST_HOME_RUN", "10", "YES", 0.0))
        record = build_catalog_prediction_settlement_record(journal, settlement_reports_by_game={GAME_ID: report}, settled_at_utc="2026-08-25T12:10:00+00:00")
        self.assertEqual(record["outcomes"][0]["settlement_result"], "UNRESOLVED")
        self.assertEqual(record["outcomes"][0]["settlement_reason"], "FIRST_HOME_RUN_NO_HR_POLICY_NOT_NORMALIZED")


if __name__ == "__main__": unittest.main()
