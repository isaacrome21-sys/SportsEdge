"""Synthetic first-screen parity and hostile refusals for M50 final-score readouts.

These tests are NOT a historical or against-close validation screen.
"""
import pytest

from sportsedge.f5_distribution import F5Distribution
from sportsedge.f5_derived_readouts import (
    read_f5_btts_probability,
    read_f5_correct_score_probability,
    read_f5_winning_margin_probability,
)
from sportsedge.game_total_distribution import (
    GameTotalDistribution, build_game_total_distribution,
)
from sportsedge.mlb_m50_terminal_score_readouts import (
    GameExoticReadoutError, read_game_exotic_probability,
)


JOINT = {"0,0": 0.1, "1,0": 0.15, "0,1": 0.2,
         "1,1": 0.25, "2,3": 0.2, "3,2": 0.1}
SHA = "c" * 64


def _gt(joint=None, n=20):
    return GameTotalDistribution(
        away_history_games=n, home_history_games=n,
        joint_score_pmf=dict(JOINT if joint is None else joint),
        distribution_sha256=SHA, distribution_version="synthetic")


def _f5():
    return F5Distribution(
        away_history_games=20, home_history_games=20,
        joint_score_pmf=dict(JOINT), distribution_sha256=SHA,
        distribution_version="synthetic")


def _read(market, selection, **kw):
    return read_game_exotic_probability(
        _gt(), market=market, selection=selection, **kw)


def test_btts_first_screen_parity_with_identical_f5_state():
    for rung in (1, 2, 7):
        for side in ("YES", "NO"):
            ours = _read("BOTH_TEAMS_TO_SCORE_RUNS", side, line=rung)
            incumbent = read_f5_btts_probability(_f5(), line=rung, side=side)
            assert abs(ours.probability - incumbent.probability) < 1e-14
            assert ours.eligible is False
            assert ours.status == "RESEARCH_ESTIMATE_UNVALIDATED"
            assert ours.market_test == "NO_MARKET_TEST"
            assert ours.push_probability == 0.0


def test_btts_nine_plus_and_opposites_conserve():
    yes = _read("BOTH_TEAMS_TO_SCORE_RUNS", "YES", line=9)
    no = _read("BOTH_TEAMS_TO_SCORE_RUNS", "NO", line=9)
    assert abs(yes.probability + no.probability - 1) < 1e-12
    assert yes.probability > 0  # Jeffreys avoids unsupported certainty.


def test_correct_score_first_screen_parity_with_f5_grammar():
    partition = ("AWAY_0_HOME_0", "AWAY_1_HOME_1", "ANY_OTHER")
    for selection in partition:
        ours = _read("CORRECT_SCORE", selection, partition=partition)
        incumbent = read_f5_correct_score_probability(
            _f5(), selection=selection, partition=partition)
        assert abs(ours.probability - incumbent.probability) < 1e-14
    assert abs(sum(_read("CORRECT_SCORE", s, partition=partition).probability
                   for s in partition) - 1) < 1e-12


def test_winning_margin_first_screen_parity_with_f5_grammar():
    partition = (
        "AWAY_BY_1_PLUS", "TIE", "HOME_BY_1", "HOME_BY_2_PLUS")
    for selection in partition:
        ours = _read("WINNING_MARGIN", selection, partition=partition)
        incumbent = read_f5_winning_margin_probability(
            _f5(), selection=selection, partition=partition)
        assert abs(ours.probability - incumbent.probability) < 1e-14
    assert abs(sum(_read("WINNING_MARGIN", s, partition=partition).probability
                   for s in partition) - 1) < 1e-12


def test_odd_even_is_team_specific_and_conserves():
    for team in ("HOME", "AWAY"):
        odd = _read("TEAM_TOTAL_ODD_EVEN", "ODD", team_side=team)
        even = _read("TEAM_TOTAL_ODD_EVEN", "EVEN", team_side=team)
        assert abs(odd.probability + even.probability - 1) < 1e-12
    assert _read("TEAM_TOTAL_ODD_EVEN", "ODD", team_side="HOME").probability != (
        _read("TEAM_TOTAL_ODD_EVEN", "ODD", team_side="AWAY").probability)


def test_actual_incumbent_joint_builder_is_read_not_modified():
    values = [0, 1, 2, 3, 1, 0, 2, 1, 4, 3]
    features = {
        "away_game_runs_for": values, "away_game_runs_against": values,
        "home_game_runs_for": values, "home_game_runs_against": values,
    }
    # Uses the shared existing full-game model, not a reimplemented mock.
    # Check the field schema through the canonical builder's explicit API.
    joint = build_game_total_distribution(features)
    before = dict(joint.joint_score_pmf)
    read = read_game_exotic_probability(
        joint, market="BOTH_TEAMS_TO_SCORE_RUNS", selection="YES", line=1)
    assert 0 < read.probability < 1
    assert joint.joint_score_pmf == before
    assert read.distribution_sha256 == joint.distribution_sha256


@pytest.mark.parametrize("market,selection,kw", [
    ("EXTRA_INNINGS", "YES", {}),
    ("RACE_TO_RUNS", "HOME", {"line": 3}),
    ("GRAND_SLAM", "NO", {}),
    ("TEAM_TO_WIN_MOST_INNINGS", "HOME", {}),
])
def test_not_deducible_from_final_score_is_refused(market, selection, kw):
    with pytest.raises(GameExoticReadoutError):
        _read(market, selection, **kw)


@pytest.mark.parametrize("bad_joint", [
    {"0,0": .4}, {"0,0": float("nan"), "1,1": .6},
    {"-1,0": 1.0}, {"01,0": 1.0},
])
def test_malformed_joint_refused(bad_joint):
    with pytest.raises(GameExoticReadoutError):
        read_game_exotic_probability(
            _gt(bad_joint), market="BOTH_TEAMS_TO_SCORE_RUNS",
            selection="YES", line=1)


@pytest.mark.parametrize("partition", [
    ["AWAY_0_HOME_0"],
    ["AWAY_0_HOME_0", "AWAY_0_HOME_0", "ANY_OTHER"],
    ["AWAY_0_HOME_0", "GARBAGE", "ANY_OTHER"],
])
def test_correct_score_partition_hostile(partition):
    with pytest.raises(GameExoticReadoutError):
        _read("CORRECT_SCORE", "AWAY_0_HOME_0", partition=partition)


@pytest.mark.parametrize("partition", [
    ["TIE", "HOME_BY_1_PLUS"],
    ["AWAY_BY_1_PLUS", "TIE", "HOME_BY_1", "HOME_BY_1_PLUS"],
    ["AWAY_BY_1_PLUS", "TIE", "BAD"],
])
def test_winning_margin_incomplete_or_overlapping_partition(partition):
    with pytest.raises(GameExoticReadoutError):
        _read("WINNING_MARGIN", "TIE", partition=partition)


@pytest.mark.parametrize("rung", [0, 10, 1.25, float("inf"), float("nan"), True])
def test_btts_catalog_rung_refusals(rung):
    with pytest.raises(GameExoticReadoutError):
        _read("BOTH_TEAMS_TO_SCORE_RUNS", "YES", line=rung)


def test_reproducible_sha_and_no_market_price():
    a = _read("TEAM_TOTAL_ODD_EVEN", "ODD", team_side="HOME")
    b = _read("TEAM_TOTAL_ODD_EVEN", "ODD", team_side="HOME")
    assert a.readout_sha256 == b.readout_sha256
    assert a.readout_version
    assert not hasattr(a, "odds_american")
    assert not hasattr(a, "ev_per_dollar")
    assert not hasattr(a, "play_label")
