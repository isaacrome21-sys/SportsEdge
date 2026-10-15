import pytest
from research.mlb_pit_rolling_baseline import evaluate

CUT = "2026-01-01T00:00:00Z"


def row(i, *, pred="2026-01-02T12:00:00Z", event="2026-01-02T18:00:00Z",
        result="2026-01-02T22:00:00Z", **changes):
    item = dict(event_id=f"e{i}", player_id="p1", market_key="hit_1plus", outcome=1,
                event_time=event, prediction_source_url="https://example.org/prediction",
                prediction_published_at=pred, prediction_observed_at=pred,
                outcome_source_url="https://example.org/result",
                outcome_published_at=result, outcome_observed_at=result,
                lineup_status="CONFIRMED", event_status="FINAL")
    item.update(changes)
    return item


def test_unobserved_outcome_does_not_leak():
    rows = [row(1, result="2026-01-04T00:00:00Z"),
            row(2, pred="2026-01-03T12:00:00Z", event="2026-01-03T18:00:00Z",
                result="2026-01-03T22:00:00Z", outcome=0)]
    result = evaluate(rows, train_cutoff=CUT, league_rate=.4)
    assert result["mean_log_loss"]["trailing"] == pytest.approx(result["mean_log_loss"]["league"])
    assert result["mean_log_loss"]["shrinkage"] == pytest.approx(result["mean_log_loss"]["league"])
    assert not result["play_authorized"] and not result["source_authenticity_verified"]


def test_outcome_released_after_observation():
    rows = [row(1), row(2, pred="2026-01-03T12:00:00Z",
                         event="2026-01-03T18:00:00Z", result="2026-01-03T22:00:00Z")]
    result = evaluate(rows, train_cutoff=CUT, league_rate=.4)
    assert result["mean_log_loss"]["trailing"] < result["mean_log_loss"]["league"]
    assert result["mean_log_loss"]["shrinkage"] < result["mean_log_loss"]["league"]


def test_different_markets_do_not_pool():
    rows = [row(1), row(2, pred="2026-01-03T12:00:00Z",
                         event="2026-01-03T18:00:00Z", result="2026-01-03T22:00:00Z",
                         market_key="walk_1plus")]
    result = evaluate(rows, train_cutoff=CUT, league_rate={"hit_1plus": .4, "walk_1plus": .2})
    assert result["mean_log_loss"]["trailing"] == pytest.approx(result["mean_log_loss"]["league"])


def test_equal_forecast_timestamp_does_not_leak():
    rows = [row(1), row(2, event="2026-01-02T19:00:00Z",
                         result="2026-01-02T23:00:00Z")]
    result = evaluate(rows, train_cutoff=CUT, league_rate=.4)
    assert result["mean_log_loss"]["trailing"] == pytest.approx(result["mean_log_loss"]["league"])


@pytest.mark.parametrize("change", [
    {"prediction_published_at": "2026-01-02T13:00:00Z"},
    {"prediction_observed_at": "2026-01-02T18:00:00Z"},
    {"outcome_published_at": "2026-01-02T17:00:00Z"},
    {"outcome_observed_at": "2026-01-02T21:00:00Z"},
    {"lineup_status": "UNKNOWN"}, {"event_status": "POSTPONED"},
    {"prediction_source_url": "http://example.org"},
    {"outcome": True}, {"player_id": True}, {"market_key": ""},
])
def test_invalid_or_uncertain_rows_refused(change):
    with pytest.raises(ValueError):
        evaluate([row(1, **change)], train_cutoff=CUT, league_rate=.4)


def test_duplicate_refused():
    with pytest.raises(ValueError, match="DUPLICATE"):
        evaluate([row(1), row(1)], train_cutoff=CUT, league_rate=.4)


def test_unsorted_forecasts_refused():
    rows = [row(1, pred="2026-01-03T12:00:00Z", event="2026-01-03T18:00:00Z",
                result="2026-01-03T22:00:00Z"), row(2)]
    with pytest.raises(ValueError, match="UNSORTED"):
        evaluate(rows, train_cutoff=CUT, league_rate=.4)


def test_pre_cutoff_forecast_refused():
    with pytest.raises(ValueError, match="TRAIN_OVERLAP"):
        evaluate([row(1, pred=CUT)], train_cutoff=CUT, league_rate=.4)


@pytest.mark.parametrize("rate,strength,window", [
    (0.0,20,20),(1.0,20,20),(.4,0,20),(.4,20,0),
    (float("nan"),20,20),(.4,float("inf"),20)])
def test_invalid_hyperparameters_refused(rate,strength,window):
    with pytest.raises(ValueError):
        evaluate([row(1)], train_cutoff=CUT, league_rate=rate, strength=strength, window=window)


def test_mixed_market_requires_distinct_frozen_priors():
    rows = [row(1), row(2, pred="2026-01-03T12:00:00Z",
                         event="2026-01-03T18:00:00Z",
                         result="2026-01-03T22:00:00Z", market_key="walk_1plus")]
    with pytest.raises(ValueError, match="MARKET_PRIOR_MAPPING_REQUIRED"):
        evaluate(rows, train_cutoff=CUT, league_rate=.4)
    with pytest.raises(ValueError, match="MISSING_MARKET_PRIOR"):
        evaluate(rows, train_cutoff=CUT, league_rate={"hit_1plus": .4})


def test_composite_identity_allows_same_game_different_market():
    rows = [row(1), row(1, market_key="walk_1plus")]
    result = evaluate(rows, train_cutoff=CUT,
                      league_rate={"hit_1plus": .4, "walk_1plus": .2})
    assert result["n"] == 2
    assert not result["market_probability_verified"]
