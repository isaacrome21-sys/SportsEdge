#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path

APPROVED_POLICY = "MODERN_REG_2018_2025"
EXPECTED_PREREG_BLOB = "f8487883186fc85b77f4e632b1aa710327473b8a"
EXPECTED_REFERENCE_BLOB = "7483f6c2a9a09c4b260797010d3765601dedd9ed"
EXPECTED_LEDGER_BLOB = "14022680891de3c3d73013ffabc8aee4611e86e6"
EXPECTED_PROPOSAL_BLOB = "2109c6d7546bbbed2b5c587eb13fd52d9325f488"
EXPECTED_SELECTION_BLOB = "5553078d22bdcd570adfc755a484b4b8b83f5390"
EXPECTED_COMMENT_ID = 5662476744
EXPECTED_COMMENT_BODY_SHA256 = "22598423589abda5ea2ad7754189411477738d07c6911cd468bbcdc57fc55ddf"


def git_blob_sha(path: Path) -> str:
    raw = path.read_bytes()
    return hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--selection", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--prereg", type=Path, required=True)
    p.add_argument("--ledger", type=Path, required=True)
    p.add_argument("--proposal", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()

    bindings = {
        "preregistration_git_blob_sha1": (args.prereg, EXPECTED_PREREG_BLOB),
        "frozen_reference_git_blob_sha1": (args.reference, EXPECTED_REFERENCE_BLOB),
        "attempt_ledger_git_blob_sha1": (args.ledger, EXPECTED_LEDGER_BLOB),
        "report_only_proposal_git_blob_sha1": (args.proposal, EXPECTED_PROPOSAL_BLOB),
        "human_policy_selection_git_blob_sha1": (args.selection, EXPECTED_SELECTION_BLOB),
    }
    for name, (path, expected) in bindings.items():
        actual = git_blob_sha(path)
        if actual != expected:
            raise SystemExit(f"{name.upper()}_MISMATCH:{actual}")

    selection = load(args.selection)
    reference = load(args.reference)
    ledger = load(args.ledger)
    proposal = load(args.proposal)

    if selection.get("status") != "FROZEN_HUMAN_SELECTED":
        raise SystemExit("SELECTION_NOT_FROZEN")
    if selection.get("selected_policy") != APPROVED_POLICY:
        raise SystemExit("SELECTION_POLICY_MISMATCH")
    hp = selection.get("human_provenance") or {}
    if hp.get("github_comment_id") != EXPECTED_COMMENT_ID:
        raise SystemExit("SELECTION_COMMENT_ID_MISMATCH")
    if hp.get("github_comment_body_sha256") != EXPECTED_COMMENT_BODY_SHA256:
        raise SystemExit("SELECTION_COMMENT_SHA_MISMATCH")
    pop = selection.get("population_policy") or {}
    if not pop.get("fit_and_signed_key_reference_population_must_match"):
        raise SystemExit("POPULATION_MATCH_NOT_REQUIRED")
    covid = selection.get("covid_2020_policy") or {}
    required_covid = {
        "status": "COVID_REGIME_FLAGGED",
        "included_in_primary_window": True,
        "primary_weight": "NORMAL_UNCHANGED",
        "may_exclude_from_primary_gate": False,
        "may_downweight_primary_fit": False,
        "may_change_thresholds": False,
        "sensitivity_slice_required": True,
        "sensitivity_slice_authority": "DIAGNOSTIC_ONLY",
        "sensitivity_result_may_retune_candidate": False,
    }
    for key, expected in required_covid.items():
        if covid.get(key) != expected:
            raise SystemExit(f"COVID_POLICY_MISMATCH:{key}")

    if reference.get("status") != "FROZEN_READY":
        raise SystemExit("REFERENCE_NOT_FROZEN_READY")
    if reference.get("selected_policy") != APPROVED_POLICY:
        raise SystemExit("REFERENCE_POLICY_MISMATCH")
    rp = reference.get("reference_policy") or {}
    if rp.get("first_season") != 2018 or rp.get("last_season") != 2025 or rp.get("season_types") != ["REG"]:
        raise SystemExit("REFERENCE_WINDOW_MISMATCH")
    if reference.get("absolute_mass_tolerance") != 0.005:
        raise SystemExit("REFERENCE_TOLERANCE_MISMATCH")

    if ledger.get("attempts_used") != 0 or ledger.get("attempts") != []:
        raise SystemExit("ATTEMPT_LEDGER_NOT_ZERO")
    if ledger.get("untouched_readout_allowed") is not False:
        raise SystemExit("UNTOUCHED_READOUT_ALREADY_ALLOWED")
    if proposal.get("selected_policy") is not None or proposal.get("review_decision") is not None:
        raise SystemExit("REPORT_ONLY_PROPOSAL_MUTATED")

    builder_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    admission = {
        "schema": "NFL_V2K_IMPLEMENTATION_ADMISSION_V3",
        "status": "ADMITTED_RESEARCH_IMPLEMENTATION_ONLY",
        "candidate_family": "NFL_V2K_DRIVE_HIERARCHICAL_JOINT_G1",
        "effective_only_when_merged_to_main": True,
        "selected_policy": APPROVED_POLICY,
        "bindings": {
            **{name: expected for name, (_, expected) in bindings.items()},
            "activation_builder_sha256": builder_sha,
            "human_selection_comment_id": EXPECTED_COMMENT_ID,
            "human_selection_comment_body_sha256": EXPECTED_COMMENT_BODY_SHA256,
        },
        "population_contract": {
            "fit_window": "2018-2025 REG",
            "signed_key_reference_window": "2018-2025 REG",
            "same_population_required": True,
            "covid_2020": "INCLUDED_PRIMARY_NORMAL_WEIGHT_FLAGGED_SENSITIVITY_ONLY",
        },
        "attempt_budget": {
            "max_development_attempts": 5,
            "attempts_used": 0,
            "attempt_consumed_by_activation": False,
            "first_materially_different_fitted_specification_scored_on_development_validation_consumes_attempt_1": True,
        },
        "authority": {
            "research_implementation": True,
            "development_validation_execution": False,
            "untouched_readout": False,
            "model_p": False,
            "pricing": False,
            "promotion": False,
            "staking": False,
            "run_it": False,
            "official": False,
        },
        "admission_conditions": {
            "market_features_forbidden_in_model_fit": True,
            "v2j_untouched_values_for_v2k_tuning_forbidden": True,
            "uploaded_demo_coefficients_as_fitted_parameters_forbidden": True,
            "development_validation_attempt_record_required_before_scoring": True,
            "untouched_readout_requires_separate_frozen_folds_sources_features_rng_seed_simulation_count_thresholds": True,
            "bettor_facing_authority_requires_issue_608_release_bridge": True,
        },
    }
    args.output.write_text(json.dumps(admission, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
