"""Tests for sportsedge.research.factor_gate (forward selection + ablation protocol)."""
from __future__ import annotations

import pytest

from sportsedge.research.factor_gate import (
    FactorGateError,
    ablation_table,
    brier_score,
    marginal_gain,
    retest_rejected,
    select_candidates,
)


def _recs(ps, outcomes, prefix="g"):
    return [
        {"game_id": f"{prefix}{i}", "model_p": p, "outcome": y}
        for i, (p, y) in enumerate(zip(ps, outcomes))
    ]


OUTCOMES = [1.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 0.0]
BASE_P = [0.6, 0.4, 0.55, 0.45, 0.6, 0.65, 0.35, 0.4]
# Strictly better-calibrated than base on the same outcomes.
GOOD_P = [0.8, 0.2, 0.75, 0.25, 0.8, 0.85, 0.15, 0.2]
# Strictly worse than base.
BAD_P = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]


def _variants():
    return {
        "base": _recs(BASE_P, OUTCOMES),
        "base+good": _recs(GOOD_P, OUTCOMES),
        "base+bad": _recs(BAD_P, OUTCOMES),
    }


def test_brier_score_known_value():
    assert brier_score([(0.5, 1.0), (0.5, 0.0)]) == pytest.approx(0.25)
    assert brier_score([(1.0 - 1e-9, 1.0)]) == pytest.approx(1e-18)


def test_brier_score_empty_raises():
    with pytest.raises(FactorGateError):
        brier_score([])


def test_select_candidates_keeps_only_real_gains():
    variants = _variants()
    result = select_candidates(
        variants, base="base", candidates=["base+good", "base+bad"], min_gain=0.001
    )
    assert result["kept"] == ["base+good"]
    assert result["dropped"] == ["base+bad"]
    good = result["details"]["base+good"]
    assert good["gain"] > 0.001
    assert good["n_common"] == len(OUTCOMES)
    assert good["variant_brier"] < good["base_brier"]


def test_select_candidates_min_gain_is_strict_noise_floor():
    variants = _variants()
    # Absurdly high noise floor drops even the genuinely better variant.
    result = select_candidates(
        variants, base="base", candidates=["base+good"], min_gain=10.0
    )
    assert result["kept"] == []
    assert result["dropped"] == ["base+good"]


def test_select_candidates_ranks_kept_by_gain_desc():
    variants = _variants()
    variants["base+ok"] = _recs([0.7, 0.3, 0.65, 0.35, 0.7, 0.75, 0.25, 0.3], OUTCOMES)
    result = select_candidates(
        variants,
        base="base",
        candidates=["base+ok", "base+good"],
        min_gain=0.0,
    )
    assert result["kept"] == ["base+good", "base+ok"]


def test_common_coverage_intersection():
    variants = _variants()
    # Variant covers only the first 4 games; alignment must use the intersection.
    variants["base+partial"] = _recs(GOOD_P[:4], OUTCOMES[:4])
    result = select_candidates(
        variants, base="base", candidates=["base+partial"], min_gain=0.0
    )
    assert result["details"]["base+partial"]["n_common"] == 4


def test_outcome_mismatch_fails_closed():
    variants = _variants()
    bad = _recs(GOOD_P, OUTCOMES)
    bad[0]["outcome"] = 0.0  # flip an outcome vs base on the same game_id
    with pytest.raises(FactorGateError):
        marginal_gain(variants["base"], bad, variant_label="base+tampered")


def test_no_common_coverage_fails_closed():
    variants = _variants()
    other = _recs(GOOD_P, OUTCOMES, prefix="other")
    with pytest.raises(FactorGateError):
        marginal_gain(variants["base"], other, variant_label="base+other")


@pytest.mark.parametrize(
    "records",
    [
        [],
        [{"model_p": 0.5, "outcome": 1.0}],  # missing game_id
        [{"game_id": "", "model_p": 0.5, "outcome": 1.0}],  # empty game_id
        [{"game_id": "g0", "model_p": 0.0, "outcome": 1.0}],  # degenerate p
        [{"game_id": "g0", "model_p": 1.0, "outcome": 1.0}],  # degenerate p
        [{"game_id": "g0", "model_p": 1.5, "outcome": 1.0}],  # p out of range
        [{"game_id": "g0", "model_p": 0.5, "outcome": 0.7}],  # invalid outcome
        [
            {"game_id": "g0", "model_p": 0.5, "outcome": 1.0},
            {"game_id": "g0", "model_p": 0.6, "outcome": 1.0},  # duplicate game_id
        ],
    ],
)
def test_malformed_records_fail_closed(records):
    base = _variants()["base"]
    with pytest.raises(FactorGateError):
        marginal_gain(base, records, variant_label="v")


def test_invalid_gate_args_fail_closed():
    variants = _variants()
    with pytest.raises(FactorGateError):
        select_candidates(variants, base="base", candidates=[], min_gain=0.0)
    with pytest.raises(FactorGateError):
        select_candidates(variants, base="missing", candidates=["base+good"], min_gain=0.0)
    with pytest.raises(FactorGateError):
        select_candidates(variants, base="base", candidates=["nope"], min_gain=0.0)
    with pytest.raises(FactorGateError):
        select_candidates(variants, base="base", candidates=["base"], min_gain=0.0)
    with pytest.raises(FactorGateError):
        select_candidates(
            variants, base="base", candidates=["base+good", "base+good"], min_gain=0.0
        )
    with pytest.raises(FactorGateError):
        select_candidates(variants, base="base", candidates=["base+good"], min_gain=-0.1)


def test_ablation_table_flags_negative_test_gain():
    # A factor that would pass the validation gate but whose probabilities are
    # miscalibrated on the test set gets a negative test gain, flagged honestly.
    test = {
        "base": _recs(BASE_P, OUTCOMES),
        "base+good": _recs(BAD_P, OUTCOMES),
    }
    table = ablation_table(test, base="base", variants=["base+good"])
    detail = table["details"]["base+good"]
    assert detail["gain"] < 0.0
    assert detail["test_gain_positive"] is False


def test_retest_rejected_repasses_gate_on_new_data():
    # A factor rejected on old data (noise floor) can be re-admitted on new data
    # where the gain clears the floor.
    old = _variants()
    assert retest_rejected(
        old, base="base", rejected=["base+good"], min_gain=10.0
    )["kept"] == []
    # New data where base is awful and the variant shines.
    new_outcomes = [1.0] * 6
    new = {
        "base": _recs([0.45] * 6, new_outcomes),
        "base+good": _recs([0.9] * 6, new_outcomes),
    }
    assert retest_rejected(new, base="base", rejected=["base+good"], min_gain=0.01)[
        "kept"
    ] == ["base+good"]


def test_gain_sign_convention():
    variants = _variants()
    good = marginal_gain(variants["base"], variants["base+good"])
    bad = marginal_gain(variants["base"], variants["base+bad"])
    assert good["gain"] > 0.0
    assert bad["gain"] < 0.0
