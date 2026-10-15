"""MLB period-count research model synthetic leakage and settlement tests."""
import pytest

from sportsedge.mlb_period_counts_empirical import (
    period_run_distribution, price_period_total,
)


def _games(n=20):
    return [
        {"game_id": f"g{i}", "start_time": f"2026-09-{i + 1:02d}T18:00:00Z",
         "inning_runs": [i % 2, 1, 0, 0, 0, 0, 0, 0, 0]}
        for i in range(n)
    ]


@pytest.mark.parametrize("innings", [3, 7])
def test_prior_only_distribution(innings):
    dist = period_run_distribution(_games(), cutoff="2026-10-01T00:00:00Z", innings=innings)
    assert dist["games"] == 20
    assert dist["sample_mean"] == 1.5
    assert abs(sum(dist["pmf"].values()) - 1) < 1e-12
    assert not dist["play_authorized"]


def test_integer_push_mass_preserved():
    dist = period_run_distribution(_games(), cutoff="2026-10-01T00:00:00Z", innings=3)
    priced = price_period_total(dist, line=1)
    assert priced["push"] == .5
    assert priced["over"] == .5
    assert priced["under"] == 0


def test_future_game_refused():
    games = _games()
    games[-1]["start_time"] = "2026-10-02T00:00:00Z"
    with pytest.raises(ValueError, match="NON_PRIOR_GAME"):
        period_run_distribution(games, cutoff="2026-10-01T00:00:00Z", innings=3)


def test_duplicate_game_refused():
    games = _games()
    games[-1]["game_id"] = games[0]["game_id"]
    with pytest.raises(ValueError, match="DUPLICATE_GAME_ID"):
        period_run_distribution(games, cutoff="2026-10-01T00:00:00Z", innings=3)


def test_missing_inning_data_refused():
    games = _games()
    games[-1]["inning_runs"] = [0, 1, 0]
    with pytest.raises(ValueError, match="INCOMPLETE_INNINGS"):
        period_run_distribution(games, cutoff="2026-10-01T00:00:00Z", innings=7)


def test_insufficient_history_refused():
    with pytest.raises(ValueError, match="INSUFFICIENT_PRIOR_GAMES"):
        period_run_distribution(_games(5), cutoff="2026-10-01T00:00:00Z", innings=3)


def test_naive_cutoff_refused():
    with pytest.raises(ValueError, match="NAIVE_EVENT_TIME"):
        period_run_distribution(_games(), cutoff="2026-10-01T00:00:00", innings=3)
