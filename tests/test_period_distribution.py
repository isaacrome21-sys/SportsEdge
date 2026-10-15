"""Period (F3/F7) distribution tests. Offline fixtures only.

Proves sportsedge.period_distribution: the joint period score state
builds from strictly-prior period run arrays for both periods, market
read-outs conserve probability with integer push mass preserved, the
league-prior (m30) path is wired, and malformed inputs fail closed.
"""
from __future__ import annotations

import pytest

from sportsedge.period_distribution import (
    PeriodDistributionError,
    build_period_distribution,
    distribution_version,
    read_period_probability,
)


def _features(n=20, seed_shift=0):
    away_for = [ (i + seed_shift) % 4 for i in range(n) ]
    away_against = [ (i + 1) % 3 for i in range(n) ]
    home_for = [ (i + 2) % 4 for i in range(n) ]
    home_against = [ i % 3 for i in range(n) ]
    return {
        "away_period_runs_for": away_for,
        "away_period_runs_against": away_against,
        "home_period_runs_for": home_for,
        "home_period_runs_against": home_against,
    }


def _league_features(n=20):
    feats = _features(n=n)
    feats["league_period_pmf"] = {"0": 0.3, "1": 0.3, "2": 0.2, "3": 0.1, "4": 0.1}
    feats["league_prior_halves"] = 500
    feats["league_prior_strength"] = 30
    return feats


@pytest.mark.parametrize("innings", [3, 7])
def test_build_and_read_all_markets(innings):
    dist = build_period_distribution(_features(), innings=innings)
    assert dist.innings == innings
    assert dist.distribution_version == distribution_version(innings, league_prior_strength=0)
    assert abs(sum(dist.joint_score_pmf.values()) - 1.0) < 1e-12
    prefix = f"F{innings}"
    ml = read_period_probability(dist, market=f"{prefix}_MONEYLINE", side="HOME")
    assert 0.0 < ml.probability < 1.0
    assert ml.push_probability > 0.0  # tied period score carries mass
    rl = read_period_probability(dist, market=f"{prefix}_RUN_LINE", line=-0.5, side="AWAY")
    assert rl.push_probability == pytest.approx(0.0, abs=1e-9)
    tot = read_period_probability(dist, market=f"{prefix}_TOTALS", line=4.5, side="OVER")
    assert 0.0 < tot.probability < 1.0
    tt = read_period_probability(
        dist, market=f"{prefix}_TEAM_TOTALS", line=2.5, side="OVER", team_side="HOME")
    assert 0.0 < tt.probability < 1.0


@pytest.mark.parametrize("innings", [3, 7])
def test_integer_total_line_preserves_push_mass(innings):
    dist = build_period_distribution(_features(), innings=innings)
    prefix = f"F{innings}"
    over = read_period_probability(dist, market=f"{prefix}_TOTALS", line=4, side="OVER")
    under = read_period_probability(dist, market=f"{prefix}_TOTALS", line=4, side="UNDER")
    assert over.push_probability > 0.0
    # Opposite sides + push exhaust the settlement mass (post-Jeffreys).
    assert over.probability + under.probability + over.push_probability == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("innings", [3, 7])
def test_league_prior_path_builds_with_production_version(innings):
    dist = build_period_distribution(
        _league_features(), innings=innings, league_prior_strength=30)
    assert dist.distribution_version == distribution_version(innings)
    assert "m30" in dist.distribution_version
    readout = read_period_probability(
        dist, market=f"F{innings}_TOTALS", line=4.5, side="UNDER")
    assert readout.readout_version.endswith(f"f{innings}")
    assert len(readout.distribution_sha256) == 64


def test_distribution_sha_is_deterministic_and_period_scoped():
    a = build_period_distribution(_features(), innings=3)
    b = build_period_distribution(_features(), innings=3)
    c = build_period_distribution(_features(), innings=7)
    assert a.distribution_sha256 == b.distribution_sha256
    assert a.distribution_sha256 != c.distribution_sha256


def test_insufficient_history_refused():
    feats = _features(n=9)
    with pytest.raises(PeriodDistributionError):
        build_period_distribution(feats, innings=3)


def test_misaligned_arrays_refused():
    feats = _features()
    feats["away_period_runs_against"] = feats["away_period_runs_against"][:-1]
    with pytest.raises(PeriodDistributionError):
        build_period_distribution(feats, innings=7)


def test_wrong_period_market_refused():
    dist3 = build_period_distribution(_features(), innings=3)
    with pytest.raises(PeriodDistributionError):
        read_period_probability(dist3, market="F7_TOTALS", line=6.5, side="OVER")
    with pytest.raises(PeriodDistributionError):
        read_period_probability(dist3, market="F5_TOTALS", line=4.5, side="OVER")


def test_unsupported_period_refused():
    with pytest.raises(PeriodDistributionError):
        build_period_distribution(_features(), innings=5)


def test_team_total_requires_team_side():
    dist = build_period_distribution(_features(), innings=3)
    with pytest.raises(PeriodDistributionError):
        read_period_probability(dist, market="F3_TEAM_TOTALS", line=0.5, side="OVER")


def test_negative_runs_refused():
    feats = _features()
    feats["home_period_runs_for"][0] = -1
    with pytest.raises(PeriodDistributionError):
        build_period_distribution(feats, innings=3)
