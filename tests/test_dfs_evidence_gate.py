from __future__ import annotations

from sportsedge.dfs.evidence import QuantileObservation, evaluate_dfs_evidence


def _calibrated_rows(n: int = 1000) -> list[QuantileObservation]:
    rows: list[QuantileObservation] = []
    for i in range(n):
        actual = float(i % 100)
        rows.append(
            QuantileObservation(
                actual=actual,
                quantiles={0.10: 9.0, 0.50: 49.0, 0.90: 89.0},
            )
        )
    return rows


def test_positive_roi_cannot_promote_bad_distribution_calibration() -> None:
    rows = [
        QuantileObservation(
            actual=row.actual,
            quantiles={0.10: 9.0, 0.50: 49.0, 0.90: 49.0},
        )
        for row in _calibrated_rows()
    ]
    decision = evaluate_dfs_evidence(rows, [1.0] * 40)
    assert decision.status == "FAILED"
    assert decision.calibration.status == "FAILED"
    assert decision.roi_veto.veto is False


def test_calibration_can_pass_with_noisy_negative_roi_without_roi_promoting() -> None:
    decision = evaluate_dfs_evidence(
        _calibrated_rows(),
        [-1.0, 1.0] * 10,
    )
    assert decision.status == "PASS"
    assert decision.calibration.status == "PASS"
    assert decision.roi_veto.reason == "ROI_TOO_NOISY_FOR_VETO"


def test_clear_negative_contest_roi_is_veto_only_after_calibration_passes() -> None:
    decision = evaluate_dfs_evidence(_calibrated_rows(), [-0.50] * 40)
    assert decision.calibration.status == "PASS"
    assert decision.roi_veto.veto is True
    assert decision.status == "FAILED"


def test_too_few_player_observations_stays_blocked_even_with_great_roi() -> None:
    decision = evaluate_dfs_evidence(_calibrated_rows(100), [2.0] * 50)
    assert decision.status == "BLOCKED"
    assert decision.calibration.status == "BLOCKED"
