"""N-way futures structural, PIT, and no-authority adversarial tests."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import isclose

import pytest

from sportsedge.futures_nway_research import (
    FuturesContractError, IndependentFuturesForecast, NWayFuturesQuote,
    RESEARCH_STATUS, screen_futures_research,
)


T = datetime(2026, 10, 21, 20, 0, tzinfo=timezone.utc)


def _board(**kwargs):
    return replace(NWayFuturesQuote(
        sport="NFL", competition_id="NFL-SB", season="2026-27",
        contract_id="SUPER_BOWL_CHAMPION", book="DK",
        runner_universe_ref="archived-full-runner-census-ref",
        quote_source_ref="exact-paired-board-capture-ref",
        expected_runners=("A", "B", "FIELD"),
        odds_by_runner={"A": -110, "B": 220, "FIELD": 350},
        source_as_of=T - timedelta(seconds=3), captured_at=T,
    ), **kwargs)


def _forecast(**kwargs):
    return replace(IndependentFuturesForecast(
        model_version="challenger-v0-not-validated",
        model_source_ref="market-blind-prequoted-features-ref",
        model_cutoff=T - timedelta(hours=1),
        probability_by_runner={"A": .57, "B": .25, "FIELD": .18},
    ), **kwargs)


def test_nway_benchmark_is_distinct_from_model_p_and_nonactionable():
    result = screen_futures_research(_board(), _forecast(), now=T)
    assert result["status"] == RESEARCH_STATUS
    assert result["official_authority"] is False
    assert result["staking_authority"] is False
    assert len(result["rows"]) == 3
    assert isclose(sum(r["market_no_vig_p"] for r in result["rows"]), 1)
    assert result["rows"][0]["model_p_unvalidated"] == pytest.approx(.57)
    assert result["rows"][0]["market_no_vig_p"] != pytest.approx(.57)
    assert result["rows"][0]["diagnostic_ev_per_unit"] == pytest.approx(.57 * (1 + 100 / 110) - 1)
    assert all(not r["official_authority"] and not r["staking_authority"] for r in result["rows"])


def test_reordered_quotes_do_not_change_runner_binding():
    quote = _board(odds_by_runner={"FIELD": 350, "A": -110, "B": 220})
    assert screen_futures_research(quote, _forecast(), now=T)["rows"][1]["runner"] == "B"


@pytest.mark.parametrize("odds", [
    {"A": -110, "B": 220},  # a missing field cannot be silently renormalized
    {"A": -110, "B": 220, "FIELD": 350, "D": 1100},
])
def test_incomplete_or_extra_quotes_refuse(odds):
    with pytest.raises(FuturesContractError, match="INCOMPLETE_OR_MISMATCHED"):
        screen_futures_research(_board(odds_by_runner=odds), _forecast(), now=T)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf"), True, 0, -99, 99, "100"])
def test_invalid_futures_odds_refuse(bad):
    with pytest.raises(FuturesContractError, match="INVALID_FUTURES_AMERICAN_ODDS"):
        screen_futures_research(
            _board(odds_by_runner={"A": bad, "B": 220, "FIELD": 350}),
            _forecast(), now=T,
        )


def test_runner_universe_must_be_distinct_and_settled_as_single_winner():
    with pytest.raises(FuturesContractError, match="DUPLICATE"):
        _board(expected_runners=("A", "A", "FIELD")).validate(now=T)
    with pytest.raises(FuturesContractError, match="SETTLEMENT"):
        _board(settlement="EACH_WAY").validate(now=T)


@pytest.mark.parametrize("field,bad,reason", [
    ("source_as_of", T + timedelta(seconds=1), "SOURCE_AFTER_CAPTURE"),
    ("captured_at", T + timedelta(seconds=1), "FUTURE_FUTURES_CAPTURE"),
    ("captured_at", T.replace(tzinfo=None), "CAPTURED_AT_TIMEZONE_REQUIRED"),
])
def test_quote_timestamp_contract(field, bad, reason):
    with pytest.raises(FuturesContractError, match=reason):
        _board(**{field: bad}).validate(now=T)


@pytest.mark.parametrize("probabilities", [
    {"A": .5, "B": .5},  # missing FIELD
    {"A": .5, "B": .3, "FIELD": .3},  # >1 mass
    {"A": -0.1, "B": .9, "FIELD": .2},
    {"A": float("nan"), "B": .25, "FIELD": .75},
    {"A": True, "B": 0, "FIELD": 0},
])
def test_invalid_independent_forecast_refuses(probabilities):
    with pytest.raises(FuturesContractError):
        screen_futures_research(
            _board(), _forecast(probability_by_runner=probabilities), now=T,
        )


def test_model_cannot_be_declared_after_quote_asof():
    with pytest.raises(FuturesContractError, match="MODEL_AFTER_QUOTE_AS_OF"):
        screen_futures_research(
            _board(), _forecast(model_cutoff=T), now=T,
        )


def test_no_model_probabilities_means_no_futures_screen():
    with pytest.raises(FuturesContractError, match="FUTURES_MODEL_RUNNERS_MISMATCH"):
        screen_futures_research(_board(), _forecast(probability_by_runner={}), now=T)
