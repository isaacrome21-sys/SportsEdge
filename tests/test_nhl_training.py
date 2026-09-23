import pytest
from sportsedge.sports.nhl.training import (FEATURES, NHLRateTrainingRow,
    fit_rate_parameters, fit_binned_calibrator)


def rows(n=14):
    return [NHLRateTrainingRow(f"g{i}", f"2026-01-{i+1:02d}T05:00:00Z",
            tuple((i + j) / 100 for j in range(len(FEATURES))), i % 5)
            for i in range(n)]


def test_rate_fit_is_deterministic_and_market_free():
    a = fit_rate_parameters(rows(), version="nhl-rate-test", ridge=2.0)
    b = fit_rate_parameters(rows(), version="nhl-rate-test", ridge=2.0)
    assert a == b
    assert a.version == "nhl-rate-test"


def test_rate_fit_rejects_short_or_bad_data():
    with pytest.raises(ValueError):
        fit_rate_parameters(rows(2), version="v")
    bad = rows(); bad[0] = NHLRateTrainingRow("g", "2026-01-01T00:00:00Z", (1.0,), 2)
    with pytest.raises(ValueError):
        fit_rate_parameters(bad, version="v")


def test_calibrator_is_deterministic_and_bounded():
    p = [0.1, 0.2, 0.7, 0.8]
    y = [0, 0, 1, 1]
    a = fit_binned_calibrator(p, y, version="cal-v1", bins=2)
    b = fit_binned_calibrator(p, y, version="cal-v1", bins=2)
    assert a == b
    assert a.training_sha256 == b.training_sha256
    assert 0 <= a.calibrate(0.75) <= 1


def test_calibrator_rejects_invalid_observations():
    with pytest.raises(ValueError):
        fit_binned_calibrator([1.2], [1], version="v")
    with pytest.raises(ValueError):
        fit_binned_calibrator([0.5], [2], version="v")
