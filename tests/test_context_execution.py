from sportsedge.mlb.context_execution import (
    ExecutionQuote, ParkWeatherContext, PitchQualityContext, UmpireContext,
    best_executable_quote, execution_gate,
)


def test_pitch_quality_overlay_is_bounded():
    assert PitchQualityContext(140, 140, 140).k_multiplier() <= 1.08
    assert PitchQualityContext(60, 60, 60).k_multiplier() >= .92


def test_weather_and_park_are_separate_but_combined():
    ctx = ParkWeatherContext(park_run_factor=1.05, park_hr_factor=1.10,
                             weather_run_delta=.08, weather_hr_delta=.15)
    assert ctx.run_multiplier() > 1.05
    assert ctx.hr_multiplier() > 1.10


def test_umpire_cannot_dominate_projection():
    assert UmpireContext(total_run_impact=20).run_multiplier() == 1.04
    assert UmpireContext(called_strike_bias=-20).k_multiplier() == .96


def test_best_price_must_be_executable():
    quotes = (
        ExecutionQuote("A", +120, max_stake=0.50),
        ExecutionQuote("B", +105, max_stake=100),
        ExecutionQuote("C", +130, max_stake=100, available=False),
    )
    q = best_executable_quote(.52, quotes, min_stake=10)
    assert q is not None and q.sportsbook == "B"


def test_execution_gate_rejects_tiny_limit_even_with_good_price():
    q = ExecutionQuote("A", +120, max_stake=2)
    passed, reasons = execution_gate(.52, q, min_ev=.01, min_stake=10)
    assert not passed
    assert "LIMIT_TOO_LOW" in reasons
