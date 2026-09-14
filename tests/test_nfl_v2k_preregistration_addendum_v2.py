import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NFL = ROOT / "sportsedge" / "sports" / "nfl"

EXPECTED = {
    "NFL_V2K_CLEAN_PREREG_2026-09-13.md": "f8487883186fc85b77f4e632b1aa710327473b8a",
    "NFL_V2K_EMPIRICAL_KEY_REFERENCE_V1.json": "7483f6c2a9a09c4b260797010d3765601dedd9ed",
    "NFL_V2K_ATTEMPT_LEDGER_V1.json": "14022680891de3c3d73013ffabc8aee4611e86e6",
    "NFL_V2K_HUMAN_POLICY_SELECTION_V1.json": "5553078d22bdcd570adfc755a484b4b8b83f5390",
    "NFL_V2K_IMPLEMENTATION_ADMISSION_V3.json": "0f836c435cb78586da0cf6f609fcbec008fcad93",
}


def blob_sha(path: Path) -> str:
    raw = path.read_bytes()
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


class TestV2KPreregistrationAddendumV2(unittest.TestCase):
    def test_bound_inputs_are_immutable(self):
        for name, expected in EXPECTED.items():
            self.assertEqual(blob_sha(NFL / name), expected, name)

    def test_addendum_only_versions_identity(self):
        a = json.loads((NFL / "NFL_V2K_PREREGISTRATION_ADDENDUM_V2.json").read_text())
        self.assertEqual(a["status"], "FROZEN_VERSION_IDENTITY_ADDENDUM_ONLY")
        self.assertEqual(a["selected_policy"], "MODERN_REG_2018_2025")
        self.assertEqual(a["reference_prerequisite"]["required_absolute_mass_tolerance"], 0.005)
        self.assertTrue(a["reference_prerequisite"]["fit_and_signed_key_reference_population_must_match"])
        self.assertEqual(a["preserved_semantics"]["max_development_attempts"], 5)
        self.assertTrue(a["preserved_semantics"]["single_shot_untouched_readout"])
        self.assertEqual(a["preserved_semantics"]["2026_use"], "SHADOW_ARCHIVE_ONLY")

    def test_no_authority_is_granted(self):
        a = json.loads((NFL / "NFL_V2K_PREREGISTRATION_ADDENDUM_V2.json").read_text())
        for value in a["authority"].values():
            self.assertIs(value, False)
        ledger = json.loads((NFL / "NFL_V2K_ATTEMPT_LEDGER_V1.json").read_text())
        self.assertEqual(ledger["attempts_used"], 0)
        self.assertFalse(ledger["untouched_readout_allowed"])

    def test_untouched_readout_still_requires_full_freeze(self):
        a = json.loads((NFL / "NFL_V2K_PREREGISTRATION_ADDENDUM_V2.json").read_text())
        p = a["untouched_readout_preconditions"]
        for key in (
            "folds_frozen", "source_manifests_frozen", "feature_allowlist_frozen",
            "rng_algorithm_version_seed_policy_frozen", "simulation_count_frozen",
            "all_thresholds_frozen", "development_validation_attempts_separately_versioned"
        ):
            self.assertTrue(p[key])
        self.assertTrue(a["release_boundary"]["candidate_validity_pass_does_not_grant_bettor_facing_authority"])


if __name__ == "__main__":
    unittest.main()
