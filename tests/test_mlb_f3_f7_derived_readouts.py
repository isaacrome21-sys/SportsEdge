"""Synthetic, offline F3/F7 derived readout parity; NOT historical scoring."""
from dataclasses import replace

import pytest

from sportsedge.period_distribution import build_period_distribution
from sportsedge.f5_distribution import F5Distribution
from sportsedge.f5_derived_readouts import (
    read_f5_btts_probability, read_f5_winning_margin_probability,
)
from sportsedge.mlb_f3_f7_derived_readouts import (
    F3F7DerivedError, read_period_derived,
)


def features():
    return {
        "away_period_runs_for": [i % 5 for i in range(20)],
        "away_period_runs_against": [(i+1) % 4 for i in range(20)],
        "home_period_runs_for": [(i+2) % 5 for i in range(20)],
        "home_period_runs_against": [(i+3) % 4 for i in range(20)],
    }


def dist(innings):
    return build_period_distribution(features(), innings=innings)


def f5_equivalent(source):
    return F5Distribution(
        away_history_games=source.away_history_games,
        home_history_games=source.home_history_games,
        joint_score_pmf=dict(source.joint_score_pmf),
        distribution_sha256=source.distribution_sha256,
        distribution_version="synthetic_same_state")


PARTITION = [
    "AWAY_BY_5_PLUS", "AWAY_BY_4", "AWAY_BY_3",
    "AWAY_BY_2", "AWAY_BY_1", "TIE",
    "HOME_BY_1", "HOME_BY_2", "HOME_BY_3",
    "HOME_BY_4", "HOME_BY_5_PLUS",
]


@pytest.mark.parametrize("innings", [3, 7])
@pytest.mark.parametrize("rung", [1, 2, 3, 7])
def test_btts_hand_recomputed_via_independent_f5_readout(innings, rung):
    d = dist(innings)
    pair = []
    for side in ("YES", "NO"):
        result = read_period_derived(
            d, innings=innings, market=f"F{innings}_BOTH_TEAMS_TO_SCORE",
            selection=side, line=rung)
        reference = read_f5_btts_probability(
            f5_equivalent(d), line=rung, side=side)
        assert abs(result.probability - reference.probability) < 1e-14
        assert result.distribution_sha256 == d.distribution_sha256
        assert result.eligible is False
        assert result.market_test == "NO_MARKET_TEST"
        pair.append(result)
    assert abs(sum(r.probability for r in pair) - 1) < 1e-12


@pytest.mark.parametrize("innings", [3, 7])
def test_full_winning_margin_partition_recomputed_against_incumbent(innings):
    d = dist(innings)
    original_state = dict(d.joint_score_pmf)
    readouts = []
    for choice in PARTITION:
        result = read_period_derived(
            d, innings=innings, market=f"F{innings}_WINNING_MARGIN",
            selection=choice, partition=PARTITION)
        reference = read_f5_winning_margin_probability(
            f5_equivalent(d), selection=choice, partition=PARTITION)
        assert abs(result.probability - reference.probability) < 1e-14
        assert result.push_probability == 0
        readouts.append(result)
    assert abs(sum(r.probability for r in readouts) - 1) < 1e-12
    assert dict(d.joint_score_pmf) == original_state


@pytest.mark.parametrize("partition", [
    ["TIE", "HOME_BY_1_PLUS"],
    ["AWAY_BY_1_PLUS", "HOME_BY_1_PLUS"],
    ["AWAY_BY_1_PLUS", "TIE", "HOME_BY_1", "HOME_BY_1_PLUS"],
    [],
])
def test_unquoted_or_overlapping_margin_partition_refused(partition):
    with pytest.raises(F3F7DerivedError):
        read_period_derived(
            dist(3), innings=3, market="F3_WINNING_MARGIN",
            selection="TIE", partition=partition)


@pytest.mark.parametrize("rung", [0, 8, 1.5, float("nan"), float("inf"), True])
def test_bad_btts_rungs_rejected(rung):
    with pytest.raises(F3F7DerivedError):
        read_period_derived(
            dist(3), innings=3, market="F3_BOTH_TEAMS_TO_SCORE",
            selection="YES", line=rung)


def test_cross_period_distribution_mismatch_refused():
    with pytest.raises(F3F7DerivedError, match="PERIOD_IDENTITY_MISMATCH"):
        read_period_derived(
            dist(3), innings=7, market="F7_BOTH_TEAMS_TO_SCORE",
            selection="YES", line=1)


@pytest.mark.parametrize("scores", [
    {"0,0": 0.3}, {"-1,0": 1.0},
    {"0,0": float("nan")}, {"01,0": 1.0},
])
def test_corrupt_joint_refused(scores):
    bad = replace(dist(3), joint_score_pmf=scores)
    with pytest.raises(F3F7DerivedError):
        read_period_derived(
            bad, innings=3, market="F3_BOTH_TEAMS_TO_SCORE",
            selection="YES", line=1)


def test_no_pricing_or_eligibility_surface_and_existing_period_gate_untouched():
    d = dist(7)
    result = read_period_derived(
        d, innings=7, market="F7_WINNING_MARGIN",
        selection="TIE", partition=PARTITION)
    assert not hasattr(result, "odds_american")
    assert not hasattr(result, "ev_per_dollar")
    assert not result.eligible
    assert not result.play_authority
    assert result.status == "RESEARCH_ESTIMATE_UNVALIDATED"
    # All canonical F3/F7 quote-binding/deployment controls remain elsewhere.
