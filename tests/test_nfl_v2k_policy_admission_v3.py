import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NFL = ROOT / "sportsedge" / "sports" / "nfl"
SELECTION = NFL / "NFL_V2K_HUMAN_POLICY_SELECTION_V1.json"
ADMISSION = NFL / "NFL_V2K_IMPLEMENTATION_ADMISSION_V3.json"
REFERENCE = NFL / "NFL_V2K_EMPIRICAL_KEY_REFERENCE_V1.json"
PREREG = NFL / "NFL_V2K_CLEAN_PREREG_2026-09-13.md"
LEDGER = NFL / "NFL_V2K_ATTEMPT_LEDGER_V1.json"
PROPOSAL = NFL / "NFL_V2K_EMPIRICAL_KEY_REFERENCE_V2_PROPOSAL.json"
BUILDER = ROOT / "scripts" / "build_nfl_v2k_policy_admission_v3.py"


def git_blob_sha(path: Path) -> str:
    raw = path.read_bytes()
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


class TestNFLV2KPolicyAdmissionV3(unittest.TestCase):
    def test_human_selection_is_explicit_and_reference_population_matches(self):
        selection = json.loads(SELECTION.read_text())
        reference = json.loads(REFERENCE.read_text())
        self.assertEqual(selection["status"], "FROZEN_HUMAN_SELECTED")
        self.assertEqual(selection["selected_policy"], "MODERN_REG_2018_2025")
        self.assertEqual(selection["human_provenance"]["github_comment_id"], 5662476744)
        self.assertEqual(reference["status"], "FROZEN_READY")
        self.assertEqual(reference["selected_policy"], selection["selected_policy"])
        self.assertEqual(reference["reference_policy"]["first_season"], 2018)
        self.assertEqual(reference["reference_policy"]["last_season"], 2025)
        self.assertEqual(reference["reference_policy"]["season_types"], ["REG"])
        self.assertTrue(selection["population_policy"]["fit_and_signed_key_reference_population_must_match"])
        self.assertTrue(selection["population_policy"]["broad_2002_2025_reference_for_primary_gate_forbidden"])

    def test_2020_is_primary_included_but_flagged_diagnostic_only(self):
        covid = json.loads(SELECTION.read_text())["covid_2020_policy"]
        self.assertEqual(covid["status"], "COVID_REGIME_FLAGGED")
        self.assertTrue(covid["included_in_primary_window"])
        self.assertEqual(covid["primary_weight"], "NORMAL_UNCHANGED")
        self.assertFalse(covid["may_exclude_from_primary_gate"])
        self.assertFalse(covid["may_downweight_primary_fit"])
        self.assertFalse(covid["may_change_thresholds"])
        self.assertTrue(covid["sensitivity_slice_required"])
        self.assertEqual(covid["sensitivity_slice_authority"], "DIAGNOSTIC_ONLY")
        self.assertFalse(covid["sensitivity_result_may_retune_candidate"])

    def test_frozen_inputs_and_attempt_zero_are_bound(self):
        self.assertEqual(git_blob_sha(PREREG), "f8487883186fc85b77f4e632b1aa710327473b8a")
        self.assertEqual(git_blob_sha(REFERENCE), "7483f6c2a9a09c4b260797010d3765601dedd9ed")
        self.assertEqual(git_blob_sha(LEDGER), "14022680891de3c3d73013ffabc8aee4611e86e6")
        self.assertEqual(git_blob_sha(PROPOSAL), "2109c6d7546bbbed2b5c587eb13fd52d9325f488")
        self.assertEqual(git_blob_sha(SELECTION), "5553078d22bdcd570adfc755a484b4b8b83f5390")
        ledger = json.loads(LEDGER.read_text())
        self.assertEqual(ledger["attempts_used"], 0)
        self.assertEqual(ledger["attempts"], [])
        self.assertFalse(ledger["untouched_readout_allowed"])

    def test_admission_is_research_implementation_only(self):
        admission = json.loads(ADMISSION.read_text())
        self.assertEqual(admission["status"], "ADMITTED_RESEARCH_IMPLEMENTATION_ONLY")
        self.assertEqual(admission["selected_policy"], "MODERN_REG_2018_2025")
        self.assertTrue(admission["authority"]["research_implementation"])
        for key in ("development_validation_execution", "untouched_readout", "model_p", "pricing", "promotion", "staking", "run_it", "official"):
            self.assertIs(admission["authority"][key], False)
        self.assertEqual(admission["attempt_budget"]["attempts_used"], 0)
        self.assertFalse(admission["attempt_budget"]["attempt_consumed_by_activation"])
        self.assertEqual(admission["population_contract"]["fit_window"], admission["population_contract"]["signed_key_reference_window"])

    def test_builder_reproduces_admission_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "admission.json"
            subprocess.run([
                sys.executable, str(BUILDER),
                "--selection", str(SELECTION),
                "--reference", str(REFERENCE),
                "--prereg", str(PREREG),
                "--ledger", str(LEDGER),
                "--proposal", str(PROPOSAL),
                "--output", str(out),
            ], check=True)
            self.assertEqual(out.read_bytes(), ADMISSION.read_bytes())
        admission = json.loads(ADMISSION.read_text())
        self.assertEqual(admission["bindings"]["activation_builder_sha256"], hashlib.sha256(BUILDER.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
