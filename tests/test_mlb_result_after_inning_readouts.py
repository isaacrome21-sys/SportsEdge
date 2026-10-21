"""Synthetic parity and negative-contract tests for result-after-inning v1.

No data-driven model is trained or tuned here; the readout must reproduce
the incumbent scored F3/F5/F7 moneyline HOME/AWAY/PUSH distribution.
"""
from dataclasses import replace
from math import isclose

import pytest

from sportsedge.f5_distribution import (
    F5Distribution, build_f5_distribution, read_f5_probability)
from sportsedge.period_distribution import (
    PeriodDistribution, build_period_distribution, read_period_probability)
from sportsedge.mlb_result_after_inning_readouts import (
    ResultAfterInningError, read_result_after_inning)


def f5_features():
    return {
        "away_f5_runs_for": [0, 1, 2, 3, 1, 0, 4, 2, 1, 3],
        "away_f5_runs_against": [1, 2, 1, 0, 3, 2, 2, 4, 0, 1],
        "home_f5_runs_for": [2, 1, 3, 0, 2, 4, 1, 2, 3, 1],
        "home_f5_runs_against": [0, 2, 1, 3, 1, 2, 4, 1, 2, 0],
    }


def period_features():
    n = 20
    return {
        "away_period_runs_for": [i % 4 for i in range(n)],
        "away_period_runs_against": [(i + 1) % 3 for i in range(n)],
        "home_period_runs_for": [(i + 2) % 4 for i in range(n)],
        "home_period_runs_against": [i % 3 for i in range(n)],
    }


def dist_for(innings):
    if innings == 5:
        return build_f5_distribution(f5_features())
    return build_period_distribution(period_features(), innings=innings)


def incumbent_pair(distribution, innings):
    if innings == 5:
        return (
            read_f5_probability(distribution, market="F5_MONEYLINE", side="HOME"),
            read_f5_probability(distribution, market="F5_MONEYLINE", side="AWAY"),
        )
    return (
        read_period_probability(distribution, market=f"F{innings}_MONEYLINE",
                                side="HOME"),
        read_period_probability(distribution, market=f"F{innings}_MONEYLINE",
                                side="AWAY"),
    )


@pytest.mark.parametrize("innings", [3, 5, 7])
def test_exact_incumbent_parity_and_three_way_mass(innings):
    dist = dist_for(innings)
    underlying_home, underlying_away = incumbent_pair(dist, innings)
    market = f"RESULT_AFTER_INNING_{innings}"
    first_state = dict(dist.joint_score_pmf)
    home = read_result_after_inning(dist, market=market, selection="HOME")
    away = read_result_after_inning(dist, market=market, selection="AWAY")
    tie = read_result_after_inning(dist, market=market, selection="TIE")
    assert home.probability == underlying_home.probability
    assert away.probability == underlying_away.probability
    assert tie.probability == underlying_home.push_probability
    assert tie.probability == underlying_away.push_probability
    assert tie.probability > 0.0
    assert isclose(sum(x.probability for x in (home, away, tie)), 1.0,
                   rel_tol=0, abs_tol=1e-12)
    assert all(x.push_probability == 0.0 for x in (home, away, tie))
    assert all(x.eligible is False and x.play_authority is False
               for x in (home, away, tie))
    assert all(x.market_test == "NO_MARKET_TEST"
               for x in (home, away, tie))
    assert all(x.distribution_sha256 == dist.distribution_sha256
               for x in (home, away, tie))
    assert dict(dist.joint_score_pmf) == first_state


@pytest.mark.parametrize("innings", [2, 4, 6, 8])
def test_missing_cumulative_joint_refused_before_using_any_dist(innings):
    with pytest.raises(ResultAfterInningError,
                       match=f"NO_CUMULATIVE_DISTRIBUTION_FOR_INNING_{innings}"):
        read_result_after_inning(
            None, market=f"RESULT_AFTER_INNING_{innings}", selection="TIE")


@pytest.mark.parametrize("innings", [3, 7])
def test_wrong_period_identity_refused(innings):
    with pytest.raises(ResultAfterInningError,
                       match="PERIOD_DISTRIBUTION_INNINGS_MISMATCH"):
        read_result_after_inning(
            dist_for(7 if innings == 3 else 3),
            market=f"RESULT_AFTER_INNING_{innings}", selection="TIE")


def test_five_requires_five_inning_source_not_a_full_game():
    with pytest.raises(ResultAfterInningError, match="F5_DISTRIBUTION_REQUIRED"):
        read_result_after_inning(
            dist_for(3), market="RESULT_AFTER_INNING_5", selection="TIE")


def test_period_source_not_interchangeable_with_f5():
    with pytest.raises(ResultAfterInningError, match="PERIOD_DISTRIBUTION_REQUIRED"):
        read_result_after_inning(
            dist_for(5), market="RESULT_AFTER_INNING_3", selection="HOME")


@pytest.mark.parametrize("selection", ["PUSH", "OVER", "DRAW", "", "OTHER"])
def test_only_three_named_outcomes_accepted(selection):
    with pytest.raises(ResultAfterInningError,
                       match="RESULT_AFTER_SIDE_MUST_BE_HOME_TIE_AWAY"):
        read_result_after_inning(
            dist_for(5), market="RESULT_AFTER_INNING_5", selection=selection)


@pytest.mark.parametrize("market", [
    "INNING_3_3_WAY", "RESULT_AFTER_INNING_9",
    "RESULT_AFTER_INNING_3_EXTRA", "GAME_MONEYLINE",
])
def test_strict_market_identity(market):
    with pytest.raises(ResultAfterInningError, match="RESULT_AFTER_MARKET_NOT_RECOGNIZED"):
        read_result_after_inning(dist_for(3), market=market, selection="TIE")


@pytest.mark.parametrize("innings", [3, 5, 7])
def test_nonconserving_incumbent_joint_refused(innings):
    dist = dist_for(innings)
    broken = replace(dist, joint_score_pmf={"0,0": 0.25})
    with pytest.raises(ResultAfterInningError,
                       match="INCUMBENT_DISTRIBUTION_REFUSED"):
        read_result_after_inning(
            broken, market=f"RESULT_AFTER_INNING_{innings}", selection="TIE")


@pytest.mark.parametrize("innings", [3, 5, 7])
def test_stable_reproducible_readout_hash_without_odds(innings):
    d = dist_for(innings)
    market = f"RESULT_AFTER_INNING_{innings}"
    a = read_result_after_inning(d, market=market, selection="TIE")
    b = read_result_after_inning(d, market=market, selection="TIE")
    assert a.readout_sha256 == b.readout_sha256
    assert a.status == "RESEARCH_ESTIMATE_UNVALIDATED"
    assert not hasattr(a, "odds_american")
    assert not hasattr(a, "ev_per_dollar")
    assert not hasattr(a, "staking_units")


def test_no_operational_registry_change():
    from sportsedge.mlb_per_inning_gates import per_inning_blocked_row
    row = per_inning_blocked_row({
        "sport": "MLB", "market": "RESULT_AFTER_INNING_3",
        "selection": "TIE"})
    assert row["blocker"] == "NO_ENGINE"
    assert row["research_only"] is True
    assert row["coverage_market"] == "RESULT_AFTER_INNING_3"
