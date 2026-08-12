import pytest

from sportsedge.statcast_contract import (
    GAME_STATCAST_FEATURES,
    NRFI_STATCAST_FEATURES,
    STATCAST_CONTRACT_VERSION,
    StatcastContractError,
    require_statcast_artifact,
    require_statcast_row,
)


def test_legacy_game_artifact_cannot_masquerade_as_statcast_model():
    legacy = {"run_features": ("off_rf_pg", "opp_ra_pg")}
    with pytest.raises(StatcastContractError, match="STATCAST_CONTRACT_MISSING_OR_WRONG_VERSION"):
        require_statcast_artifact(legacy, kind="game")


def test_metadata_claim_is_not_enough_statcast_must_be_in_actual_model_contract():
    fake = {
        "statcast_contract_version": STATCAST_CONTRACT_VERSION,
        "statcast_consumed_by_model": True,
        "statcast_features": GAME_STATCAST_FEATURES,
        "run_features": ("off_rf_pg", "opp_ra_pg"),
    }
    with pytest.raises(StatcastContractError, match="STATCAST_NOT_IN_MODEL_FEATURE_CONTRACT"):
        require_statcast_artifact(fake, kind="game")


def test_complete_game_artifact_contract_passes():
    artifact = {
        "statcast_contract_version": STATCAST_CONTRACT_VERSION,
        "statcast_consumed_by_model": True,
        "statcast_features": GAME_STATCAST_FEATURES,
        "run_features": ("off_rf_pg", "opp_ra_pg", *GAME_STATCAST_FEATURES),
    }
    require_statcast_artifact(artifact, kind="game")


def test_complete_nrfi_artifact_contract_passes():
    artifact = {
        "statcast_contract_version": STATCAST_CONTRACT_VERSION,
        "statcast_consumed_by_model": True,
        "statcast_features": NRFI_STATCAST_FEATURES,
        "features": ("away_fi_for", "home_fi_for", *NRFI_STATCAST_FEATURES),
    }
    require_statcast_artifact(artifact, kind="nrfi")


def test_nrfi_metadata_without_model_columns_fails():
    artifact = {
        "statcast_contract_version": STATCAST_CONTRACT_VERSION,
        "statcast_consumed_by_model": True,
        "statcast_features": NRFI_STATCAST_FEATURES,
        "features": ("away_fi_for", "home_fi_for"),
    }
    with pytest.raises(StatcastContractError, match="STATCAST_NOT_IN_MODEL_FEATURE_CONTRACT"):
        require_statcast_artifact(artifact, kind="nrfi")


def test_live_statcast_row_must_contain_every_required_numeric_field():
    row = {name: 0.25 for name in GAME_STATCAST_FEATURES}
    require_statcast_row(row, kind="game")
    row.pop(GAME_STATCAST_FEATURES[0])
    with pytest.raises(StatcastContractError, match="STATCAST_VALUE_MISSING_OR_INVALID"):
        require_statcast_row(row, kind="game")
