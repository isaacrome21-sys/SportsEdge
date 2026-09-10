"""NFL V2C: expanded training-only bandwidth search for V2A score support.

V2C exists because the prior independently-evaluated nested V2A selected the
lowest preregistered scale (0.50) in every outer fold with enough inner history.
That boundary result motivates a *new* challenger with a wider training-only
search range; it does not retroactively alter the V2A selection contract.

Selection remains nested inside each outer training window and uses only inner
spread/total predictive log loss. Historical signed key-number target frequencies
and outer-test outcomes are not selection inputs.
"""
from __future__ import annotations

from typing import Any, Iterable

from .m2_v2_nested_validation import build_nfl_m2_v2_nested_candidate_evidence

NFL_M2_V2C_VARIANT_ID = "nfl_m2_v2c_expanded_bandwidth_candidate"
NFL_M2_V2C_SELECTION_CONTRACT = "NFL_M2_V2C_EXPANDED_TRAINING_ONLY_KERNEL_SELECTION_V1"
NFL_M2_V2C_KERNEL_GRID = (0.20, 0.30, 0.40, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00)


def build_nfl_m2_v2c_candidate_evidence(
    rows: Iterable[dict[str, Any]],
    *,
    source_manifest_sha256: str,
    min_train_seasons: int = 2,
    min_calibration_fit_seasons: int = 2,
    calibration_bins: int = 10,
    calibration_min_bin_n: int = 25,
    calibration_threshold: float = 0.05,
    fold_win_threshold: float = 0.65,
    ridge_alpha: float = 10.0,
) -> dict[str, Any]:
    evidence = build_nfl_m2_v2_nested_candidate_evidence(
        rows,
        source_manifest_sha256=source_manifest_sha256,
        min_train_seasons=min_train_seasons,
        min_calibration_fit_seasons=min_calibration_fit_seasons,
        calibration_bins=calibration_bins,
        calibration_min_bin_n=calibration_min_bin_n,
        calibration_threshold=calibration_threshold,
        fold_win_threshold=fold_win_threshold,
        ridge_alpha=ridge_alpha,
        candidate_kernel_scales=NFL_M2_V2C_KERNEL_GRID,
    )
    # Underlying score-distribution implementation remains V2A; V2C identifies
    # only the new preregistered hyperparameter-selection policy.
    evidence["candidate_variant_id"] = NFL_M2_V2C_VARIANT_ID
    evidence["selection_contract"] = NFL_M2_V2C_SELECTION_CONTRACT
    evidence["parameters"]["candidate_kernel_scales"] = [
        float(value) for value in NFL_M2_V2C_KERNEL_GRID
    ]
    evidence["selection_guards"].update({
        "prior_v2a_outer_key_target_used_to_choose_grid_values": False,
        "motivation": "PRIOR_INNER_PREDICTIVE_SELECTION_HIT_LOWER_GRID_BOUNDARY",
        "original_v2a_contract_mutated": False,
    })
    evidence["promotion_eligible"] = False
    evidence["production_registry_consumes_this_artifact"] = False
    return evidence
