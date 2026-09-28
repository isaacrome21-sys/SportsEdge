import pytest

from sportsedge.dfs.mlb_joint_paths import simulate_mlb_joint_paths
from sportsedge.research.mlb_joint_market_readout import read_joint_research_probability
from sportsedge.research.mlb_joint_period_paths import (
    MlbPeriodResearchError,
    read_mlb_period_probability,
    simulate_mlb_period_paths,
)
from tests.test_dfs_mlb_joint_paths import _game


@pytest.fixture(scope="module")
def results():
    game = _game()
    canonical = simulate_mlb_joint_paths(game, path_count=120, seed=31027)
    period = simulate_mlb_period_paths(game, path_count=120, seed=31027)
    return canonical, period


def test_period_paths_share_canonical_identity_and_final_scores(results):
    canonical, period = results
    assert period["path_set_id"] == canonical.path_set_id
    assert period["path_count"] == canonical.path_count
    assert len(period["samples"]) == canonical.path_count
    for expected, actual in zip(canonical.snapshot["game_samples"], period["samples"]):
        assert actual["away_runs"] == expected["away_runs"]
        assert actual["home_runs"] == expected["home_runs"]
        assert actual["innings"] == expected["innings"]
        assert sum(row["away_runs"] for row in actual["inning_runs"]) == actual["away_runs"]
        assert sum(row["home_runs"] for row in actual["inning_runs"]) == actual["home_runs"]
        assert [row["inning"] for row in actual["inning_runs"]] == list(
            range(1, actual["innings"] + 1)
        )


def test_nrfi_yrfi_partition_same_paths(results):
    _, period = results
    nrfi = read_mlb_period_probability(period, market="NRFI")
    yrfi = read_mlb_period_probability(period, market="YRFI")
    assert nrfi["research_p"] + yrfi["research_p"] == pytest.approx(1.0)
    assert nrfi["push_p"] == yrfi["push_p"] == 0.0
    assert nrfi["path_set_id"] == yrfi["path_set_id"] == period["path_set_id"]
    assert nrfi["production_ready"] is False
    assert nrfi["official_authority"] is False


def test_f5_moneyline_preserves_ties_as_pushes(results):
    _, period = results
    home = read_mlb_period_probability(period, market="F5_MONEYLINE", side="HOME")
    away = read_mlb_period_probability(period, market="F5_MONEYLINE", side="AWAY")
    assert home["research_p"] + away["research_p"] + home["push_p"] == pytest.approx(1.0)
    assert home["push_p"] == away["push_p"]


def test_f5_total_and_run_line_preserve_probability_mass(results):
    _, period = results
    over = read_mlb_period_probability(period, market="F5_TOTALS", side="OVER", line=4)
    under = read_mlb_period_probability(period, market="F5_TOTALS", side="UNDER", line=4)
    assert over["research_p"] + under["research_p"] + over["push_p"] == pytest.approx(1.0)
    assert over["push_p"] == under["push_p"]

    home = read_mlb_period_probability(period, market="F5_RUN_LINE", side="HOME", line=-1)
    away = read_mlb_period_probability(period, market="F5_RUN_LINE", side="AWAY", line=1)
    assert home["research_p"] + away["research_p"] + home["push_p"] == pytest.approx(1.0)
    assert home["push_p"] == away["push_p"]


def test_first_inning_and_generic_inning_readouts_agree(results):
    _, period = results
    first = read_mlb_period_probability(
        period, market="FIRST_INNING_TOTALS", side="OVER", line=0.5
    )
    generic = read_mlb_period_probability(
        period, market="INNING_TOTALS", side="OVER", line=0.5, inning=1
    )
    yrfi = read_mlb_period_probability(period, market="YRFI")
    assert first["research_p"] == generic["research_p"] == yrfi["research_p"]
    assert first["inning"] == generic["inning"] == 1


def test_period_layer_does_not_open_original_three_market_readout(results):
    canonical, _ = results
    with pytest.raises(ValueError, match="MARKET_OUTSIDE_VALIDATION_SCOPE"):
        read_joint_research_probability(canonical, market="NRFI", side="OVER", line=0.5)


def test_unplayed_or_invalid_inning_fails_closed(results):
    _, period = results
    with pytest.raises(MlbPeriodResearchError, match="INNING_NOT_PLAYED"):
        read_mlb_period_probability(
            period, market="INNING_TOTALS", side="OVER", line=0.5, inning=31
        )
    with pytest.raises(MlbPeriodResearchError, match="INNING_REQUIRED"):
        read_mlb_period_probability(
            period, market="INNING_TOTALS", side="OVER", line=0.5, inning=0
        )


def test_nrfi_yrfi_reject_irrelevant_side(results):
    _, period = results
    with pytest.raises(MlbPeriodResearchError, match="SIDE_NOT_USED"):
        read_mlb_period_probability(period, market="NRFI", side="OVER")
