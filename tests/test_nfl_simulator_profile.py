import pytest

from sportsedge.sports.nfl.simulator_profile import (
    KEY_NUMBER_CONTRACT,
    build_nfl_simulator_profile,
    validate_profile_fit,
)


def _audit():
    return {
        "provenance": "REAL_PUBLIC_HISTORY",
        "source_sha256": "a" * 64,
        "seasons": [2021, 2022, 2023, 2024, 2025],
        "signed_margin_pmf": {"-7": 0.045, "-3": 0.072, "3": 0.083, "7": 0.051},
    }


def test_profile_is_versioned_hash_bound_and_emergent_contract():
    profile = build_nfl_simulator_profile(_audit(), version="nfl-key-emergent-v2")
    assert profile["version"] == "nfl-key-emergent-v2"
    assert profile["source_sha256"] == "a" * 64
    assert profile["seasons"] == [2021, 2022, 2023, 2024, 2025]
    assert profile["key_number_contract"] == KEY_NUMBER_CONTRACT


def test_profile_stores_validation_targets_not_empirical_simulator_mass():
    profile = build_nfl_simulator_profile(_audit(), version="nfl-key-emergent-v2")
    assert "empirical_key_mass" not in profile
    assert profile["validation_target_key_frequency"] == {
        -7: 0.045, -3: 0.072, 3: 0.083, 7: 0.051,
    }


def test_profile_rejects_non_real_history():
    audit = _audit()
    audit["provenance"] = "FIXTURE"
    with pytest.raises(ValueError, match="REAL_HISTORY_REQUIRED"):
        build_nfl_simulator_profile(audit, version="nfl-key-emergent-v2")


def test_fit_validation_checks_each_emergent_signed_key():
    profile = build_nfl_simulator_profile(_audit(), version="nfl-key-emergent-v2")
    report = validate_profile_fit(
        profile, {-7: 0.044, -3: 0.074, 3: 0.081, 7: 0.052}, max_abs_error=0.005,
    )
    assert report["pass"] is True
    assert report["contract"] == KEY_NUMBER_CONTRACT
    assert set(report["per_key"]) == {-7, -3, 3, 7}
    assert report["per_key"][3]["historical_target"] == pytest.approx(0.083)
    assert report["per_key"][3]["simulated_emergent"] == pytest.approx(0.081)


def test_fit_validation_fails_when_one_emergent_key_is_bad():
    profile = build_nfl_simulator_profile(_audit(), version="nfl-key-emergent-v2")
    report = validate_profile_fit(
        profile, {-7: 0.044, -3: 0.074, 3: 0.060, 7: 0.052}, max_abs_error=0.005,
    )
    assert report["pass"] is False
    assert report["per_key"][3]["abs_error"] > 0.005


def test_old_profile_contract_cannot_validate():
    old = {
        "version": "old", "empirical_key_mass": {-7: .04, -3: .07, 3: .08, 7: .05}
    }
    with pytest.raises(ValueError, match="EMERGENT_KEY_NUMBER_CONTRACT_REQUIRED"):
        validate_profile_fit(old, {-7: .04, -3: .07, 3: .08, 7: .05}, max_abs_error=.01)
