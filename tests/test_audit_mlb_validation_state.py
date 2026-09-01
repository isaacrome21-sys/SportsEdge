import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts.audit_mlb_validation_state import bb_state, nrfi_state, settlement_state


SETTLEMENT_INVARIANTS = {
    "batter_hits_reconciled": True,
    "f5_reconciled": True,
    "facts_present": True,
    "final_status": True,
    "first_inning_reconciled": True,
    "home_run_order_reconciled": True,
    "winning_pitcher_decision_present": True,
}


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def settlement_report():
    return {
        "schema_version": "mlb_settlement_semantics_v2",
        "state": "SETTLEMENT_SEMANTICS_PASS",
        "source": "MLB_STATSAPI_BOX_SCORE_AND_LIVE_FEED",
        "sportsbook_data_used": False,
        "game_pk": "822696",
        "generated_at_utc": "2026-08-31T12:00:00+00:00",
        "facts_sha256": "a" * 64,
        "invariants": dict(SETTLEMENT_INVARIANTS),
        "proven_markets": ["HITS", "MONEYLINE"],
        "excluded_markets": [],
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
    def test_settlement_pass_is_schema_hash_and_invariant_bound(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "SETTLEMENT/latest/report.json", settlement_report())
            out = settlement_state(root)
        self.assertEqual(set(out), {"HITS", "MONEYLINE"})
        evidence = out["MONEYLINE"]["settlement_semantics"]
        self.assertEqual(evidence["status"], "PASS")
        self.assertRegex(evidence["evidence_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(evidence["facts_sha256"], "a" * 64)

    def test_settlement_never_passes_malformed_or_ambiguous_report(self):
        mutations = (
            lambda row: row.update(facts_sha256="not-a-hash"),
            lambda row: row["invariants"].pop("f5_reconciled"),
            lambda row: row.update(proven_markets=["MONEYLINE", "MONEYLINE"]),
            lambda row: row.update(excluded_markets=["MONEYLINE"]),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate), TemporaryDirectory() as tmp:
                root = Path(tmp)
                report = settlement_report()
                mutate(report)
                write_json(root / "SETTLEMENT/latest/report.json", report)
                self.assertEqual(settlement_state(root), {})

    def test_bb_requires_real_boolean_eligibility_and_all_gates(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "PITCHER_BB/latest/bb_v6_forward_shadow_report.json"
            settlement_path = root / "PITCHER_BB/latest/bb_v6_settlements.json"
            write_json(report_path, bb_report())
            write_json(settlement_path, [{"source": "MLB_STATSAPI_BOX_SCORE"}])
            passing = bb_state(root)
            self.assertEqual(passing["settlement_semantics"]["status"], "PASS")
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

    def test_bb_rejects_non_object_settlement_rows(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "PITCHER_BB/latest/bb_v6_forward_shadow_report.json", bb_report())
            write_json(
                root / "PITCHER_BB/latest/bb_v6_settlements.json",
                [{"source": "MLB_STATSAPI_BOX_SCORE"}, "ignored-before-fix"],
            )
            self.assertEqual(bb_state(root)["settlement_semantics"]["status"], "FAIL")

    def test_nrfi_and_yrfi_require_exact_boolean_market_attestations(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_path = root / "NRFI_YRFI/latest/nrfi_v6_forward_shadow_report.json"
            write_json(report_path, nrfi_report())
            write_json(
                root / "NRFI_YRFI/latest/nrfi_v6_settlements.json",
                [{"source": "MLB_STATSAPI_LIVE_FEED_LINESCORE_V2"}],
            )
            passing = nrfi_state(root)
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
