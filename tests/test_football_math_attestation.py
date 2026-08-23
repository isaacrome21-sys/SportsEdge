import pytest


def _artifact(**overrides):
    base = {
        "provenance": "REAL_PUBLIC_HISTORY",
        "source_sha256": "a" * 64,
        "profile_version": "nfl-key-emergent-v2",
        "key_number_contract": "EMERGENT_VALIDATION_TARGET_V1",
        "seasons": [2019, 2020, 2021, 2022, 2023, 2024, 2025],
        "key_numbers": [-7, -3, 3, 7],
        "per_key_abs_error": {"-7": 0.002, "-3": 0.003, "3": 0.002, "7": 0.004},
        "max_allowed_abs_error": 0.005,
    }
    base.update(overrides)
    return base


def test_real_hash_bound_emergent_profile_can_attest_validated_math():
    from sportsedge.core.validation.math_attestation import attest_validated_math
    result = attest_validated_math(_artifact())
    assert result["math_valid"] is True
    assert result["attestation"] == "VALIDATED_MATH"
    assert result["key_number_contract"] == "EMERGENT_VALIDATION_TARGET_V1"
    assert result["artifact_sha256"]


def test_old_imposed_mass_contract_cannot_attest_math():
    from sportsedge.core.validation.math_attestation import attest_validated_math
    artifact = _artifact()
    artifact.pop("key_number_contract")
    with pytest.raises(ValueError, match="EMERGENT_KEY_NUMBER_CONTRACT_REQUIRED"):
        attest_validated_math(artifact)


def test_fixture_or_synthetic_provenance_cannot_attest_math():
    from sportsedge.core.validation.math_attestation import attest_validated_math
    with pytest.raises(ValueError, match="REAL_PUBLIC_HISTORY_REQUIRED"):
        attest_validated_math(_artifact(provenance="FIXTURE"))


def test_missing_signed_key_fails_closed():
    from sportsedge.core.validation.math_attestation import attest_validated_math
    artifact = _artifact(key_numbers=[-3, 3, 7])
    with pytest.raises(ValueError, match="SIGNED_KEY_COVERAGE_INCOMPLETE"):
        attest_validated_math(artifact)


def test_any_key_over_tolerance_fails_closed():
    from sportsedge.core.validation.math_attestation import attest_validated_math
    artifact = _artifact(per_key_abs_error={"-7": 0.002, "-3": 0.003, "3": 0.009, "7": 0.004})
    result = attest_validated_math(artifact)
    assert result["math_valid"] is False
    assert result["attestation"] == "BLOCKED_MATH"
    assert result["failed_keys"] == [3]


def test_attestation_hash_changes_when_evidence_changes():
    from sportsedge.core.validation.math_attestation import attest_validated_math
    first = attest_validated_math(_artifact())
    second = attest_validated_math(_artifact(per_key_abs_error={"-7": 0.002, "-3": 0.003, "3": 0.002, "7": 0.003}))
    assert first["artifact_sha256"] != second["artifact_sha256"]


def test_promotion_entrypoint_derives_math_state_from_artifact():
    from sportsedge.core.promotion.football import evaluate_football_promotion_from_math_artifact
    result = evaluate_football_promotion_from_math_artifact(
        _artifact(per_key_abs_error={"-7": 0.002, "-3": 0.003, "3": 0.009, "7": 0.004}),
        fold_wins=100, fold_total=100, ci_attested=True,
        calibration_max_bin_deviation=0.0, calibration_threshold=0.02,
        logged_plays=1000, mean_clv=0.05, clv_t_stat=5.0,
    )
    assert result["stage"] == "BLOCKED_MATH"
    assert result["math_attestation"]["math_valid"] is False
