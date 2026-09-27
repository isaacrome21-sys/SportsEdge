import json
from hashlib import sha1
from pathlib import Path
from unittest import TestCase

import sportsedge.sports.cfb.dispersion_only_evaluator as evaluator

ROOT = Path(__file__).resolve().parents[1]
PREREG = ROOT / "config/cfb_dispersion_only_prereg_v1.json"


def _load(path):
    return json.loads(Path(path).read_text())


def _git_blob(path):
    raw = Path(path).read_bytes()
    return sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


class TestCFBDispersionOnlyPreregV1(TestCase):
    def test_status_and_parent_budget_remain_unspent(self):
        prereg = _load(PREREG)
        parent = _load(ROOT / "config/cfb_model_selection_policy_v1.json")
        candidate_prereg = _load(ROOT / "config/cfb_model_candidate_prereg_v1.json")
        self.assertEqual(prereg["status"], "FROZEN_BEFORE_DISPERSION_EVALUATION")
        self.assertEqual(parent["attempts_consumed"], 0)
        self.assertEqual(candidate_prereg["governance"]["attempts_consumed"], 0)
        self.assertFalse(candidate_prereg["governance"]["evaluation_performed"])
        self.assertEqual(prereg["budget_neutral_basis"]["attempts_consumed_by_this_diagnostic"], 0)

    def test_all_bound_git_blobs_match(self):
        prereg = _load(PREREG)
        for key in ("parent_policy", "bakeoff_v3_config", "bakeoff_v3_evaluator", "v2_reference", "dispersion_evaluator", "dispersion_evaluator_tests"):
            binding = prereg["bindings"][key]
            self.assertEqual(_git_blob(ROOT / binding["path"]), binding["git_blob"], key)
        for rel, expected in prereg["bindings"]["direct_dispersion_dependency_blobs"].items():
            self.assertEqual(_git_blob(ROOT / rel), expected, rel)

    def test_parent_provenance_warning_and_budget_rule_are_inherited_exactly(self):
        prereg = _load(PREREG)
        parent = _load(ROOT / "config/cfb_model_selection_policy_v1.json")
        self.assertEqual(prereg["data_provenance"]["class"], parent["training_provenance_class"])
        self.assertEqual(prereg["data_provenance"]["provider_metric_model_vintage"], parent["provider_metric_model_vintage"])
        self.assertEqual(prereg["data_provenance"]["provider_metric_materialization_mode"], parent["provider_metric_materialization_mode"])
        self.assertEqual(prereg["data_provenance"]["provider_vintage_warning"], parent["provider_vintage_warning"])
        self.assertEqual(prereg["budget_neutral_basis"]["parent_rule_verbatim"], parent["controls_budget_rule"])

    def test_v3_capture_contract_is_bound_without_new_mean_fit(self):
        prereg = _load(PREREG)
        v3 = _load(ROOT / "config/cfb_candidate_bakeoff_evaluator_v3.json")
        self.assertEqual(v3["schema"], prereg["bindings"]["bakeoff_v3_config"]["required_schema"])
        self.assertEqual(v3["status"], prereg["bindings"]["bakeoff_v3_config"]["required_status"])
        self.assertEqual(v3["evaluator_code_git_blob"], prereg["bindings"]["bakeoff_v3_evaluator"]["git_blob"])
        self.assertEqual(v3["capture"]["capture_pass"], prereg["capture_contract"]["capture_pass"])
        self.assertFalse(v3["capture"]["new_mean_fit_allowed"])
        self.assertFalse(v3["capture"]["post_bakeoff_reproduction_allowed"])
        self.assertEqual(v3["outer_validation_seasons"], prereg["capture_contract"]["required_outer_folds"])

    def test_frozen_evaluator_constants_match_prereg(self):
        prereg = _load(PREREG)
        sim = prereg["simulation"]
        boot = prereg["paired_cluster_bootstrap"]
        folds = prereg["folds"]
        self.assertEqual(evaluator.N_PATHS, sim["n_paths_per_game_per_model"])
        self.assertEqual(evaluator.BASE_SEED, sim["base_seed"])
        self.assertEqual(evaluator.PIT_SEED, sim["pit_randomization_seed"])
        self.assertEqual(evaluator.BOOTSTRAP_SEED, boot["seed"])
        self.assertEqual(evaluator.BOOTSTRAP_RESAMPLES, boot["resamples"])
        self.assertEqual(list(evaluator.SCORING_SEASONS), list(range(folds["first_scored_dispersion_season"], folds["last_scored_dispersion_season"] + 1)))
        self.assertEqual(evaluator.RESIDUAL_SEED_SEASON, 2018)
        self.assertEqual(tuple(evaluator.KEY_MARGINS), (3, 7))

    def test_decision_has_zero_model_or_betting_authority(self):
        prereg = _load(PREREG)
        self.assertTrue(all(value is False for value in prereg["authority"].values()))
        effect = prereg["decision_effect"]
        for key in ("may_change_bakeoff_winner", "may_rerank_mean_models", "may_veto_bakeoff_winner", "may_restore_eliminated_candidate", "may_consume_model_selection_attempt", "may_modify_parent_policy", "may_create_model_p", "may_pass_truth_gate", "may_authorize_official_output", "automatic_production_promotion"):
            self.assertFalse(effect[key], key)
        self.assertEqual(prereg["null_bakeoff_rule"].split(",")[0], "If the parent bakeoff returns NO_CANDIDATE_DEMONSTRATED_SIGNAL_AT_THIS_SAMPLE")


if __name__ == "__main__":
    import unittest
    unittest.main()
