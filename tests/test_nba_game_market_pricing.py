"""End-to-end test: verified games -> ratings -> ML/spread/total prices.

The *parse* path is proven on recorded fixtures in
test_nba_espn_verified_source.py. Here the fit/price math is exercised on
deterministically generated games already in the parse_completed_games()
output shape (marked synthetic); the wiring between parse output and
fit_verified_games input is asserted by key contract.
"""
import math
import random

import pytest

from sportsedge.sports.nba.espn_verified_source import NBASource, NBADataError
from sportsedge.sports.nba.nba_game_market_pricing import (
    fit_verified_games,
    price_game_markets,
    spread_probability,
    total_probability,
)


def synthetic_games(n=60, seed=7):
    rng = random.Random(seed)
    teams = ["8", "11", "2", "13"]
    strength = {"8": 3.0, "11": 1.0, "2": -1.0, "13": -3.0}
    games = []
    for i in range(n):
        home, away = rng.sample(teams, 2)
        hs = int(round(112 + strength[home] - strength[away] + 3.5 + rng.gauss(0, 10)))
        aws = int(round(112 + strength[away] - strength[home] - 3.5 + rng.gauss(0, 10)))
        games.append({
            "event_id": f"9{i:06d}",
            "tipoff": f"2024-11-{(i % 28) + 1:02d}T00:00:00+00:00",
            "home_team_id": home,
            "away_team_id": away,
            "home_score": max(hs, 80),
            "away_score": max(aws, 80),
        })
    return games


class TestFitAndPrice:
    def test_fit_requires_minimum_games(self):
        with pytest.raises(NBADataError, match="NBA_INSUFFICIENT_VERIFIED_GAMES"):
            fit_verified_games(synthetic_games(10))

    def test_end_to_end_prices_are_valid(self):
        ratings, sig_m, sig_t = fit_verified_games(synthetic_games(60))
        assert math.isfinite(sig_m) and sig_m > 0
        assert math.isfinite(sig_t) and sig_t > 0
        prices = price_game_markets(home_team_id="8", away_team_id="13",
                                    ratings=ratings, sigma_margin=sig_m,
                                    sigma_total=sig_t)
        prices.validate()
        # team 8 is the strongest synthetic team and at home -> clear favorite
        assert prices.ml_home_probability > 0.6
        assert prices.predicted_margin > 0
        assert 195 < prices.predicted_total < 245

    def test_spread_probability_monotone_in_line(self):
        ratings, sig_m, sig_t = fit_verified_games(synthetic_games(60))
        prices = price_game_markets(home_team_id="8", away_team_id="13",
                                    ratings=ratings, sigma_margin=sig_m,
                                    sigma_total=sig_t)
        p1 = spread_probability(prices, -10.5, selection="HOME")
        p2 = spread_probability(prices, -2.5, selection="HOME")
        assert p1 < p2  # harder line -> less likely to cover
        p_away = spread_probability(prices, 10.5, selection="AWAY")
        assert 0.0 < p_away < 1.0

    def test_total_probability_monotone_in_line(self):
        ratings, sig_m, sig_t = fit_verified_games(synthetic_games(60))
        prices = price_game_markets(home_team_id="8", away_team_id="13",
                                    ratings=ratings, sigma_margin=sig_m,
                                    sigma_total=sig_t)
        assert total_probability(prices, 200.5, selection="OVER") > \
            total_probability(prices, 240.5, selection="OVER")
        assert 0.0 < total_probability(prices, 220.5, selection="UNDER") < 1.0

    def test_bad_inputs_fail_closed(self):
        ratings, sig_m, sig_t = fit_verified_games(synthetic_games(60))
        with pytest.raises(NBADataError):
            price_game_markets(home_team_id="8", away_team_id="8",
                               ratings=ratings, sigma_margin=sig_m, sigma_total=sig_t)
        with pytest.raises(NBADataError):
            price_game_markets(home_team_id="8", away_team_id="13",
                               ratings=ratings, sigma_margin=0.0, sigma_total=sig_t)
        prices = price_game_markets(home_team_id="8", away_team_id="13",
                                    ratings=ratings, sigma_margin=sig_m,
                                    sigma_total=sig_t)
        with pytest.raises(NBADataError):
            spread_probability(prices, float("nan"), selection="HOME")
        with pytest.raises(NBADataError):
            total_probability(prices, 220.5, selection="MAYBE")

    def test_parse_output_feeds_fit_input_contract(self):
        # the keys fit_verified_games needs are exactly the keys
        # parse_completed_games produces
        src = NBASource(getter=lambda url: None)
        required = {"event_id", "tipoff", "home_team_id", "away_team_id",
                    "home_score", "away_score"}
        for g in synthetic_games(30):
            assert required <= set(g)
