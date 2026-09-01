import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.audit_mlb_validation_state import bb_state, nrfi_state, settlement_state


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def settlement_report(*, rules=False):
    rows = []
    for market in ("HITS", "MONEYLINE"):
        rows.append({
            "market": market,
            "official_fact_state": "OFFICIAL_FACTS_PROVEN",
            "book_rules_validated": bool(rules),
            "missing_book_rules": [] if rules else ["PLAYER_PROP_PARTICIPATION_VOID_PUSH_RULES" if market == "HITS" else "FULL_GAME_FINAL_SCORE_SETTLEMENT"],
            "settlement_semantics_state": "SETTLEMENT_ELIGIBLE" if rules else "BOOK_SETTLEMENT_UNVALIDATED",
        })
    return {
        "schema_version": "mlb_settlement_evidence_v3",
        "evidence_class": "LIVE_OFFICIAL_FACT_PROBE",
        "source": "MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED",
        "sportsbook_data_used": bool(rules),
        "generated_at_utc": "2026-08-31T12:00:00+00:00",
        "facts_sha256": "a" * 64,
        "market_count": len(rows),
        "markets": rows,
    }


def bb_report(eligible=True):
    return {
        "schema_version": "bb_v6_forward_shadow_evaluation_v1",
        "state": "MODEL_ELIGIBLE" if eligible is True else "MODEL_NOT_ELIGIBLE",
        "sportsbook_data_used": False,
        "settled_unique_pitchers": 150,
        "market": {"PITCHER_BB": {"eligible": eligible}},
        "gates": {"integrity": {"pass": True}, "age_days": {"pass": True}},
    }


def nrfi_report(nrfi=True, yrfi=True):
    both_eligible = nrfi is True and yrfi is True
    return {
        "schema_version": "nrfi_v6_forward_shadow_evaluation_v1",
        "state": "MODEL_ELIGIBLE" if both_eligible else "MODEL_NOT_ELIGIBLE",
        "sportsbook_data_used": False,
        "settled_unique_games": 200,
        "markets": {"NRFI": {"eligible": nrfi}, "YRFI": {"eligible": yrfi}},
        "gates": {"integrity": {"pass": True}, "age_days": {"pass": True}},
    }


class AuditMLBValidationStateTests(unittest.TestCase):
    def test_v3_settlement_pass_requires_official_facts_and_book_rules(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "SETTLEMENT_OFFICIAL_FACTS/latest/report.json", settlement_report(rules=True))
            out = settlement_state(root)
        self.assertEqual(set(out), {"HITS", "MONEYLINE"})
        evidence = out["MONEYLINE"]["settlement_semantics"]
        self.assertEqual(evidence["status"], "PASS")
        self.assertTrue(evidence["sportsbook_rule_evidence"])
        self.assertRegex(evidence["evidence_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(evidence["facts_sha256"], "a" * 64)

    def test_v3_official_facts_without_book_rules_remain_pending(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "SETTLEMENT_OFFICIAL_FACTS/latest/report.json", settlement_report(rules=False))
            out = settlement_state(root)
        self.assertEqual(out["MONEYLINE"]["settlement_semantics"]["status"], "PENDING")
        self.assertEqual(out["MONEYLINE"]["settlement_semantics"]["reason"], "BOOK_SETTLEMENT_RULE_EVIDENCE_REQUIRED")

    def test_obsolete_v2_facts_only_report_cannot_pass_v3_settlement_gate(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "SETTLEMENT/latest/report.json", {
                "schema_version": "mlb_settlement_semantics_v2",
                "state": "SETTLEMENT_SEMANTICS_PASS",
                "source": "MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED",
                "sportsbook_data_used": False,
                "game_pk": "822696",
                "generated_at_utc": "2026-08-31T12:00:00+00:00",
                "facts_sha256": "a" * 64,
                "invariants": {"facts_present": True},
                "proven_markets": ["MONEYLINE"],
                "excluded_markets": [],
            })
            self.assertEqual(settlement_state(root), {})

    def test_settlement_never_passes_malformed_or_duplicate_v3_rows(self):
        mutations = (
            lambda row: row.update(facts_sha256="not-a-hash"),
            lambda row: row.update(market_count=3),
            lambda row: row["markets"].append(dict(row["markets"][0])),
            lambda row: row["markets"][0].update(missing_book_rules="not-a-list"),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate), TemporaryDirectory() as tmp:
                root = Path(tmp)
                report = settlement_report(rules=True)
                mutate(report)
                write_json(root / "SETTLEMENT_OFFICIAL_FACTS/latest/report.json", report)
                self.assertEqual(settlement_state(root), {})

    def test_bb_forward_evidence_is_independent_of_book_rule_gate(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "PITCHER_BB/latest/bb_v6_forward_shadow_report.json"
            settlement_path = root / "PITCHER_BB/latest/bb_v6_settlements.json"
            write_json(report_path, bb_report())
            write_json(settlement_path, [{"source": "MLB_STATSAPI_BOX_SCORE"}])
            passing = bb_state(root)
            self.assertEqual(passing["settlement_semantics"]["status"], "PENDING")
            self.assertEqual(passing["settlement_semantics"]["reason"], "BOOK_SETTLEMENT_RULE_EVIDENCE_REQUIRED")
            self.assertEqual(passing["forward_evidence"]["status"], "PASS")

            truthy = bb_report("true")
            truthy["state"] = "MODEL_ELIGIBLE"
            write_json(report_path, truthy)
            self.assertEqual(bb_state(root)["forward_evidence"]["status"], "FAIL")

            failed_gate = bb_report()
            failed_gate["gates"]["age_days"]["pass"] = False
            write_json(report_path, failed_gate)
            failed = bb_state(root)["forward_evidence"]
            self.assertEqual(failed["status"], "FAIL")
            self.assertIn("age_days", failed["failed_gates"])

            wrong_schema = bb_report()
            wrong_schema["schema_version"] = "legacy"
            write_json(report_path, wrong_schema)
            self.assertEqual(bb_state(root)["forward_evidence"]["status"], "FAIL")

    def test_bb_rejects_non_object_official_fact_rows(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "PITCHER_BB/latest/bb_v6_forward_shadow_report.json", bb_report())
            write_json(root / "PITCHER_BB/latest/bb_v6_settlements.json", [{"source": "MLB_STATSAPI_BOX_SCORE"}, "bad"])
            self.assertEqual(bb_state(root)["settlement_semantics"]["reason"], "OFFICIAL_SETTLEMENT_FACTS_INCOMPLETE")

    def test_nrfi_and_yrfi_forward_attestations_stay_exact_boolean(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "NRFI_YRFI/latest/nrfi_v6_forward_shadow_report.json"
            write_json(report_path, nrfi_report())
            write_json(root / "NRFI_YRFI/latest/nrfi_v6_settlements.json", [{"source": "MLB_STATSAPI_LIVE_FEED_LINESCORE_V2"}])
            passing = nrfi_state(root)
            self.assertEqual(passing["NRFI"]["settlement_semantics"]["status"], "PENDING")
            self.assertEqual(passing["NRFI"]["forward_evidence"]["status"], "PASS")
            self.assertEqual(passing["YRFI"]["forward_evidence"]["status"], "PASS")

            truthy = nrfi_report(True, "true")
            truthy["state"] = "MODEL_ELIGIBLE"
            write_json(report_path, truthy)
            mixed = nrfi_state(root)
            self.assertEqual(mixed["NRFI"]["forward_evidence"]["status"], "PASS")
            self.assertEqual(mixed["YRFI"]["forward_evidence"]["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
