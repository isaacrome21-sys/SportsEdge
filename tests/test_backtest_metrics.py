"""Metric correctness against hand-computed values."""
import math

import pytest

from sportsedge.backtest.metrics import (
    MetricError, brier_score, calibration_bins, hit_rate_at_thresholds,
    log_loss, summarize,
)

# Hand-computed reference:
#   p:    0.9   0.8   0.3   0.2
#   y:     1     0     1     0
# Brier = ((.1)^2 + (.8)^2 + (.7)^2 + (.2)^2)/4 = (0.01+0.64+0.49+0.04)/4
#       = 1.18/4 = 0.295
# LogLoss = -[ln(.9)+ln(.2)+ln(.3)+ln(.8)]/4
RECS = [
    {"model_p": 0.9, "outcome": 1.0},
    {"model_p": 0.8, "outcome": 0.0},
    {"model_p": 0.3, "outcome": 1.0},
    {"model_p": 0.2, "outcome": 0.0},
]


def test_brier_score_matches_hand_computation():
    assert brier_score(RECS) == pytest.approx(0.295)


def test_log_loss_matches_hand_computation():
    expected = -(math.log(0.9) + math.log(0.2)
                 + math.log(0.3) + math.log(0.8)) / 4
    assert log_loss(RECS) == pytest.approx(expected)


def test_log_loss_rejects_degenerate_probabilities():
    with pytest.raises(MetricError) as exc:
        log_loss([{"model_p": 1.0, "outcome": 1.0}])
    assert "BACKTEST_LOG_LOSS_DEGENERATE_PROBABILITY" in str(exc.value)
    with pytest.raises(MetricError) as exc:
        log_loss([{"model_p": 0.0, "outcome": 0.0}])
    assert "BACKTEST_LOG_LOSS_DEGENERATE_PROBABILITY" in str(exc.value)


def test_push_grades_half():
    recs = [{"model_p": 0.6, "outcome": 0.5}]
    assert brier_score(recs) == pytest.approx(0.01)
    assert log_loss(recs) == pytest.approx(
        -(0.5 * math.log(0.6) + 0.5 * math.log(0.4)))


def test_calibration_bins_count_and_rate():
    bins = calibration_bins(RECS, n_bins=2)
    # bin 0: [0, .5): p=.3 (y=1), p=.2 (y=0) -> mean .25, rate .5
    # bin 1: [.5, 1]: p=.9 (y=1), p=.8 (y=0) -> mean .85, rate .5
    assert bins[0]["n"] == 2
    assert bins[0]["mean_p"] == pytest.approx(0.25)
    assert bins[0]["hit_rate"] == pytest.approx(0.5)
    assert bins[1]["n"] == 2
    assert bins[1]["mean_p"] == pytest.approx(0.85)
    assert bins[1]["hit_rate"] == pytest.approx(0.5)


def test_empty_bins_report_none_not_invented():
    bins = calibration_bins([{"model_p": 0.05, "outcome": 1.0}], n_bins=4)
    assert bins[0]["n"] == 1
    assert bins[3]["n"] == 0
    assert bins[3]["mean_p"] is None
    assert bins[3]["hit_rate"] is None


def test_hit_rate_at_thresholds():
    out = hit_rate_at_thresholds(RECS, [0.5, 0.85])
    # t=.5: p>=.5 are .9(y1), .8(y0) -> 1/2
    assert out[0]["n"] == 2
    assert out[0]["hit_rate"] == pytest.approx(0.5)
    # t=.85: only p=.9 (y1) -> 1.0
    assert out[1]["n"] == 1
    assert out[1]["hit_rate"] == pytest.approx(1.0)


def test_summarize_fields():
    s = summarize(RECS)
    assert s["n"] == 4
    assert s["brier"] == pytest.approx(0.295)
    assert s["mean_p"] == pytest.approx(0.55)
    assert s["base_rate"] == pytest.approx(0.5)


def test_malformed_records_fail_closed():
    with pytest.raises(MetricError, match="BACKTEST_METRICS_NO_RECORDS"):
        brier_score([])
    with pytest.raises(MetricError, match="BACKTEST_METRIC_PROBABILITY_INVALID"):
        brier_score([{"model_p": 1.5, "outcome": 1.0}])
    with pytest.raises(MetricError, match="BACKTEST_METRIC_OUTCOME_INVALID"):
        brier_score([{"model_p": 0.5, "outcome": 0.7}])
