"""The legacy aggregate MLB simulator may not silently price playoff extras.

The canonical plate-appearance joint-path simulator is the separate postseason
research candidate; these tests do not promote that research distribution.
"""
import pytest

from sportsedge.v7_distribution import (
    V7DistributionError,
    simulate_game_distribution,
)


def _kwargs():
    return dict(
        away_mean_runs=4.1,
        home_mean_runs=4.6,
        total_line=8.5,
        simulations=1000,
        seed=1234,
    )


def test_postseason_rule_mode_fails_closed_before_simulating():
    with pytest.raises(V7DistributionError, match="V7_POSTSEASON_REQUIRES_INNING_LEVEL_JOINT_PATHS"):
        simulate_game_distribution(**_kwargs(), rules_mode="POSTSEASON")


@pytest.mark.parametrize("mode", ["UNKNOWN", "", "playoffs", None, True])
def test_unrecognized_rule_modes_fail_closed(mode):
    with pytest.raises(V7DistributionError, match="V7_RULES_MODE_INVALID"):
        simulate_game_distribution(**_kwargs(), rules_mode=mode)


def test_explicit_regular_season_retains_existing_distribution_bytes():
    implicit = simulate_game_distribution(**_kwargs())
    explicit = simulate_game_distribution(**_kwargs(), rules_mode="REGULAR_SEASON")
    assert implicit.result_sha256 == explicit.result_sha256
    assert implicit.joint_score_pmf == explicit.joint_score_pmf
    assert implicit.away_win_probability == explicit.away_win_probability
