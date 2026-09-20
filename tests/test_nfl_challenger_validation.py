from __future__ import annotations

from copy import deepcopy

import pytest

from sportsedge.core.simulate.nfl_challenger_validation import (
    score_challenger_structural_metrics,
)


def _metrics():
    return {
        "mean_possessions_per_team_game":10.7,
        "opening_drive_scoring_rate":.36,
        "first_score_opening_receiver_rate":.52,
        "drive_outcome_shares":{
            "TD":.22,
            "FG":.16,
            "PUNT":.35,
            "TURNOVER":.11,
            "DOWNS":.04,
            "END_HALF_GAME":.12,
        },
        "absolute_margin_mass":{"3":.15,"7":.09,"10":.04},
        "mean_total_points":45.0,
        "total_point_quantiles":{"10":27.0,"25":34.0,"50":44.0,"75":55.0,"90":65.0},
        "late_game":{
            "leading":{
                "sample_count":250,
                "fourth_down_attempt_rate":.18,
                "pace_proxy_rate":.22,
            },
            "trailing":{
                "sample_count":300,
                "fourth_down_attempt_rate":.35,
                "pace_proxy_rate":.48,
            },
        },
    }


def _by_metric(report):
    return {row["metric"]:row for row in report["metrics"]}


def test_identical_structural_metrics_pass_with_zero_authority():
    metrics=_metrics()
    report=score_challenger_structural_metrics(metrics,deepcopy(metrics))
    assert report["status"]=="PASS"
    assert report["authority"]=="NONE_RESEARCH_ONLY"
    assert report["promotion_authority"] is False
    assert report["truth_gate_authority"] is False
    assert report["staking_authority"] is False
    assert report["official_authority"] is False
    assert all(row["disposition"]=="PASS" for row in report["metrics"])


def test_frozen_threshold_is_inclusive():
    empirical=_metrics(); simulated=deepcopy(empirical)
    simulated["mean_total_points"]+=2.0
    report=score_challenger_structural_metrics(simulated,empirical)
    row=_by_metric(report)["mean_total_points"]
    assert row["absolute_error"]==2.0
    assert row["disposition"]=="PASS"
    assert report["status"]=="PASS"


def test_metric_beyond_frozen_threshold_blocks():
    empirical=_metrics(); simulated=deepcopy(empirical)
    simulated["mean_total_points"]+=2.01
    report=score_challenger_structural_metrics(simulated,empirical)
    assert report["status"]=="BLOCKED"
    assert _by_metric(report)["mean_total_points"]["disposition"]=="FAIL"
    assert report["official_authority"] is False


def test_sparse_late_game_bucket_is_insufficient_sample_and_blocks():
    empirical=_metrics(); simulated=deepcopy(empirical)
    empirical["late_game"]["leading"]={"sample_count":199}
    simulated["late_game"]["leading"]={}
    report=score_challenger_structural_metrics(simulated,empirical)
    assert report["status"]=="BLOCKED"
    rows=_by_metric(report)
    for metric in ("fourth_down_attempt_rate","pace_proxy_rate"):
        row=rows[f"late_game.leading.{metric}"]
        assert row["disposition"]=="INSUFFICIENT_SAMPLE"
        assert row["empirical_sample_count"]==199


def test_late_game_minimum_sample_is_enforced_at_200():
    empirical=_metrics(); simulated=deepcopy(empirical)
    empirical["late_game"]["leading"]["sample_count"]=200
    simulated["late_game"]["leading"]["fourth_down_attempt_rate"]=(
        empirical["late_game"]["leading"]["fourth_down_attempt_rate"]+.051
    )
    report=score_challenger_structural_metrics(simulated,empirical)
    row=_by_metric(report)["late_game.leading.fourth_down_attempt_rate"]
    assert row["disposition"]=="FAIL"
    assert row["empirical_sample_count"]==200
    assert report["status"]=="BLOCKED"


@pytest.mark.parametrize("bad",[float("nan"),float("inf"),True,None,"45"])
def test_invalid_required_numeric_metric_fails_closed(bad):
    empirical=_metrics(); simulated=deepcopy(empirical)
    simulated["mean_total_points"]=bad
    with pytest.raises(ValueError,match="CHALLENGER_STRUCTURAL_METRIC_INVALID"):
        score_challenger_structural_metrics(simulated,empirical)


@pytest.mark.parametrize("bad",[-.01,1.01])
def test_invalid_rate_fails_closed(bad):
    empirical=_metrics(); simulated=deepcopy(empirical)
    simulated["opening_drive_scoring_rate"]=bad
    with pytest.raises(ValueError,match="CHALLENGER_STRUCTURAL_RATE_OUT_OF_RANGE"):
        score_challenger_structural_metrics(simulated,empirical)


def test_missing_required_mapping_fails_closed():
    empirical=_metrics(); simulated=deepcopy(empirical)
    del simulated["drive_outcome_shares"]
    with pytest.raises(ValueError,match="CHALLENGER_STRUCTURAL_MAPPING_REQUIRED:drive_outcome_shares"):
        score_challenger_structural_metrics(simulated,empirical)


@pytest.mark.parametrize("bad",[-1,True,2.5,"200"])
def test_invalid_late_game_sample_count_fails_closed(bad):
    empirical=_metrics(); simulated=deepcopy(empirical)
    empirical["late_game"]["leading"]["sample_count"]=bad
    with pytest.raises(ValueError,match="CHALLENGER_STRUCTURAL_SAMPLE_COUNT_INVALID:leading"):
        score_challenger_structural_metrics(simulated,empirical)


def test_non_mapping_input_fails_closed():
    with pytest.raises(TypeError,match="CHALLENGER_STRUCTURAL_MAPPING_REQUIRED"):
        score_challenger_structural_metrics([], _metrics())
