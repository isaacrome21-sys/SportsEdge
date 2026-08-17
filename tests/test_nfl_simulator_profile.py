import pytest

from sportsedge.sports.nfl.simulator_profile import build_nfl_simulator_profile, validate_profile_fit


def _audit():
    return {
        "provenance": "REAL_PUBLIC_HISTORY",
        "source_sha256": "a" * 64,
        "seasons": [2021, 2022, 2023, 2024, 2025],
        "signed_margin_pmf": {
            "-7": 0.045,
            "-3": 0.072,
            "3": 0.083,
            "7": 0.051,
        },
    }


def test_profile_is_versioned_and_hash_bound():
    profile = build_nfl_simulator_profile(_audit(), version="nfl-key-pmf-v1")
    assert profile["version"] == "nfl-key-pmf-v1"
    assert profile["source_sha256"] == "a" * 64
    assert profile["seasons"] == [2021, 2022, 2023, 2024, 2025]


def test_profile_uses_signed_key_mass_exactly():
    profile = build_nfl_simulator_profile(_audit(), version="nfl-key-pmf-v1")
    assert profile["empirical_key_mass"] == {-7: 0.045, -3: 0.072, 3: 0.083, 7: 0.051}


def test_profile_rejects_non_real_history():
    audit = _audit()
    audit["provenance"] = "FIXTURE"
    with pytest.raises(ValueError, match="REAL_HISTORY_REQUIRED"):
        build_nfl_simulator_profile(audit, version="nfl-key-pmf-v1")


def test_fit_validation_checks_each_signed_key():
    profile = build_nfl_simulator_profile(_audit(), version="nfl-key-pmf-v1")
    report = validate_profile_fit(profile, {-7: 0.044, -3: 0.074, 3: 0.081, 7: 0.052}, max_abs_error=0.005)
    assert report["pass"] is True
    assert set(report["per_key"]) == {-7, -3, 3, 7}


def test_fit_validation_fails_when_one_key_is_bad():
    profile = build_nfl_simulator_profile(_audit(), version="nfl-key-pmf-v1")
    report = validate_profile_fit(profile, {-7: 0.044, -3: 0.074, 3: 0.060, 7: 0.052}, max_abs_error=0.005)
    assert report["pass"] is False
    assert report["per_key"][3]["abs_error"] > 0.005
