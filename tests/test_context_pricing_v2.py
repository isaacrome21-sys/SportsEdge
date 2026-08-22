from sportsedge.mlb.context_pricing_v2 import (
    CatcherContext, ParkWeatherSample, PropQuote, alternate_line_surface,
    best_executable_quote, catcher_k_multiplier, devig_pair, park_specific_weather_lookup,
)


def test_weather_fails_closed_without_sample():
    rows = [ParkWeatherSample("Wrigley", 8, 75, 60, 1.05, 1.08)] * 10
    r = park_specific_weather_lookup(rows, park="Wrigley", wind_mph=8, temp_f=75, dewpoint_f=60, min_samples=30)
    assert r.status == "INSUFFICIENT_EMPIRICAL_WEATHER_SAMPLE"
    assert r.run_factor is None


def test_weather_uses_empirical_matches_only():
    rows = [ParkWeatherSample("Wrigley", 8, 75, 60, 1.05, 1.08)] * 30
    r = park_specific_weather_lookup(rows, park="Wrigley", wind_mph=8, temp_f=75, dewpoint_f=60)
    assert r.status == "OK" and r.samples_used == 30


def test_catcher_overlay_is_capped():
    assert 0.98 <= catcher_k_multiplier(CatcherContext(100, 50)) <= 1.02


def test_pair_devig_and_executable_quote():
    o = PropQuote("dk", "K", "OVER", 5.5, -110, True, 100)
    u = PropQuote("dk", "K", "UNDER", 5.5, -110, True, 100)
    a, b = devig_pair(o, u)
    assert abs(a + b - 1) < 1e-12
    better = PropQuote("fd", "K", "OVER", 5.5, +105, True, 50)
    assert best_executable_quote([o, better], side="OVER", min_stake=25).book == "fd"


def test_alt_surface_sorted():
    q = [PropQuote("dk", "K", "OVER", x, -110) for x in (6.5, 4.5, 5.5)]
    assert [r.line for r in alternate_line_surface(q, book="dk", market="K", side="OVER")] == [4.5, 5.5, 6.5]
