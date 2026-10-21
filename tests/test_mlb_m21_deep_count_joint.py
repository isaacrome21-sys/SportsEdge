"""Adversarial first-inning COUNT readout tests; known losing baseline remains."""
from dataclasses import replace
import math

import pytest

from sportsedge.mlb_first_inning_model import (
    _pool, blended_rate, price_game_first_inning_runs,
)
from sportsedge.mlb_m21_deep_count_joint import (
    M21CountError, construct_first_inning_joint, read_first_inning_deep,
)
from sportsedge.mlb_first_inning_deep_set import deep_set_blocked_row

POOLS = {
    "away_for": [0, 1, 0, 0, 2, 1, 0, 3, 1, 0],
    "home_against": [0, 0, 1, 1, 0, 0, 2, 1, 0, 0],
    "home_for": [0, 2, 1, 0, 0, 1, 3, 0, 0, 1],
    "away_against": [1, 0, 0, 0, 1, 2, 0, 1, 0, 0],
}


def joint(**kwargs):
    return construct_first_inning_joint(
        **(POOLS | kwargs), source_evidence_sha256="a" * 64)


def read(d, market, selection, line=None):
    return read_first_inning_deep(
        d, market=market, selection=selection, line=line)


def test_same_incumbent_rates_disclosed_and_mass_conserved():
    d = joint()
    assert d.lambda_away == blended_rate(
        _pool(POOLS["away_for"], "away_for"),
        _pool(POOLS["home_against"], "home_against"))
    assert d.lambda_home == blended_rate(
        _pool(POOLS["home_for"], "home_for"),
        _pool(POOLS["away_against"], "away_against"))
    assert d.documented_binary_baseline_loss is True
    assert d.conditional_independence_assumed is True
    assert not d.eligible and d.market_test == "NO_MARKET_TEST"
    assert 0 <= d.tail_mass_truncated <= 2e-13
    assert abs(sum(d.joint_score_pmf.values()) - 1) < 1e-12
    # Independent-Poisson score joint's zero-zero probability should
    # match the existing Poisson total scoring mean, modulo <=1e-13 tails.
    incumbent = price_game_first_inning_runs(**POOLS, line=0.5)
    zero = d.joint_score_pmf["0,0"]
    assert abs(zero - (1 - incumbent["p_over"])) < 1e-11


def test_first_inning_three_way_explicit_tie_winning_cell():
    d = joint()
    readouts = [read(d, "FIRST_INNING_3_WAY", x)
                for x in ("HOME", "TIE", "AWAY")]
    assert readouts[1].probability > 0
    assert abs(sum(x.probability for x in readouts) - 1) < 1e-12
    assert all(x.push_probability == 0 for x in readouts)
    raw_tie = sum(p for key, p in d.joint_score_pmf.items()
                  if key.split(",")[0] == key.split(",")[1])
    assert raw_tie > 0


def test_odd_even_is_complete_partition():
    d = joint()
    a = read(d, "FIRST_INNING_ODD_EVEN", "ODD")
    b = read(d, "FIRST_INNING_ODD_EVEN", "EVEN")
    assert abs(a.probability + b.probability - 1) < 1e-12
    assert a.push_probability == b.push_probability == 0


@pytest.mark.parametrize("line", [0.5, -0.5, 0.0])
def test_signed_opposite_run_lines_account_for_push(line):
    d = joint()
    home = read(d, "FIRST_INNING_RUN_LINE", "HOME", line=line)
    away = read(d, "FIRST_INNING_RUN_LINE", "AWAY", line=-line)
    assert abs(home.probability + away.probability + home.push_probability - 1) < 1e-12
    assert abs(home.push_probability - away.push_probability) < 1e-12


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, "bad", True])
def test_invalid_existing_history_pool_refused(bad):
    values = POOLS["away_for"].copy()
    values[0] = bad
    with pytest.raises(M21CountError, match="INCUMBENT_POOL_REJECTED"):
        joint(away_for=values)


def test_insufficient_or_excessive_history_held():
    with pytest.raises(M21CountError, match="INCUMBENT_POOL_REJECTED"):
        joint(away_for=[0] * 9)
    with pytest.raises(M21CountError, match="INCUMBENT_POOL_REJECTED"):
        joint(home_for=[0] * 31)


def test_fake_hash_rejected_and_hash_is_part_of_model_provenance():
    with pytest.raises(M21CountError, match="PINNED_SOURCE_EVIDENCE_SHA256_REQUIRED"):
        construct_first_inning_joint(**POOLS, source_evidence_sha256="not-sha")
    a = joint()
    b = construct_first_inning_joint(**POOLS, source_evidence_sha256="b" * 64)
    assert a.distribution_sha256 != b.distribution_sha256
    assert a.joint_score_pmf == b.joint_score_pmf


@pytest.mark.parametrize("market", [
    "FIRST_INNING_K", "FIRST_INNING_BATTERS_TO_PLATE",
    "FIRST_INNING_HR", "EXTRA_INNINGS",
])
def test_no_unbuilt_pbp_or_game_exotics_claim(market):
    with pytest.raises(M21CountError, match="UNSUPPORTED_FIRST_INNING_DEEP_MARKET"):
        read(joint(), market, "HOME")


def test_bad_mass_and_nonfinite_pmf_refused():
    d = joint()
    with pytest.raises(M21CountError, match="M21_DISTRIBUTION_MASS_NOT_CONSERVED"):
        read(replace(d, joint_score_pmf={"0,0": 0.4}), "FIRST_INNING_3_WAY", "TIE")
    with pytest.raises(M21CountError, match="INVALID_JOINT_SCORE_CELL"):
        read(replace(d, joint_score_pmf={"0,0": math.nan}), "FIRST_INNING_3_WAY", "TIE")


def test_baseline_failure_and_independence_disclosure_cannot_be_removed():
    d = joint()
    with pytest.raises(M21CountError, match="REQUIRED_ADVERSE_ASSUMPTIONS_NOT_DISCLOSED"):
        read(replace(d, documented_binary_baseline_loss=False),
             "FIRST_INNING_3_WAY", "TIE")
    with pytest.raises(M21CountError, match="REQUIRED_ADVERSE_ASSUMPTIONS_NOT_DISCLOSED"):
        read(replace(d, conditional_independence_assumed=False),
             "FIRST_INNING_3_WAY", "TIE")


def test_canonical_m21_gate_stays_research_no_engine():
    d = joint()
    r = read(d, "FIRST_INNING_ODD_EVEN", "ODD")
    assert r.status == "RESEARCH_CHALLENGER_KNOWN_BINARY_BASELINE_LOSS"
    assert r.documented_binary_baseline_loss
    assert not r.play_authority and not r.staking_authority
    assert not hasattr(r, "odds_american")
    blocked = deep_set_blocked_row(
        {"market": "FIRST_INNING_3_WAY", "selection": "TIE"})
    assert blocked["blocker"] == "NO_ENGINE"
    assert blocked["research_only"] is True
