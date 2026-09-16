import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "audit_mlb_v2_replay_coverage.py"
POLICY = json.loads((ROOT / "config" / "mlb_v2_replay_coverage_policy.json").read_text())
spec = importlib.util.spec_from_file_location("mlb_cov", SCRIPT)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)


class MLBV2ReplayCoverageAuditTests(unittest.TestCase):
    def test_forward_holdout_file_is_not_selected_or_opened(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            good = root / "2026-08-31"; good.mkdir()
            (good / "pit_pairs.jsonl").write_text(json.dumps({"bookmaker":"draftkings","market_family":"MONEYLINE"})+"\n")
            forbidden = root / "2026-09-01"; forbidden.mkdir()
            (forbidden / "pit_pairs.jsonl").write_text("THIS IS INTENTIONALLY INVALID JSON")
            files = mod.selected_files(root, POLICY)
            self.assertEqual(files, [good / "pit_pairs.jsonl"])
            rows = mod.load_rows(files)
            self.assertEqual(len(rows), 1)

    def test_unsupported_absence_claim_falls_back_to_unattributable(self):
        row = {"absence_class":"PINNACLE_NEVER_OFFERED","provider_offer_evidence":False,"decision_available":False}
        self.assertEqual(mod._absence(row, POLICY), "UNATTRIBUTABLE_ABSENCE")
        row = {"absence_class":"ARCHIVE_MISSING","collection_expected_evidence":False,"close_available":False}
        self.assertEqual(mod._absence(row, POLICY), "UNATTRIBUTABLE_ABSENCE")

    def test_joint_below_200_is_structural_under_fixed_archive_window(self):
        rows = [{"bookmaker":"draftkings","market_family":"MONEYLINE","decision_available":True,"close_available":True} for _ in range(199)]
        report = mod.audit(rows, POLICY, [Path("2026-08-31/pit_pairs.jsonl")])
        item = report["featured_core_market_joint"]["MONEYLINE"]
        self.assertEqual(item["n_joint"], 199)
        self.assertTrue(item["structurally_below_minimum_under_fixed_archive_window"])

    def test_pinnacle_absence_is_known_precondition_not_measured_discovery(self):
        report = mod.audit([], POLICY, [])
        self.assertFalse(report["known_preconditions"]["pinnacle_admissible_archive_present"])
        self.assertEqual(report["known_preconditions"]["pinnacle_status"], "KNOWN_PRECONDITION_NOT_AUDIT_DISCOVERY")
        self.assertNotIn("pinnacle", report["measured_providers"])


if __name__ == "__main__":
    unittest.main()
