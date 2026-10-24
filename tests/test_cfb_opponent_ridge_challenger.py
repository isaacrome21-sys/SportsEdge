"""Contract tests for CFB opponent ridge research challenger."""
from datetime import datetime, timedelta, timezone
import pytest

from sportsedge.cfb_opponent_ridge_challenger import (
    fit, predict, reference_probabilities, factors_before_kickoff, SCHEMA,
)
from scripts.eval_cfb_opponent_ridge_challenger import evaluate

NOW = datetime(2025, 10, 11, 20, tzinfo=timezone.utc)


def game(i, h, a, hp, ap, *, days=7, season=2025, neutral=False,
         spread=None, total=None):
    start = NOW - timedelta(days=days)
    return {"game_id": str(i), "season": season, "home": h, "away": a,
            "kickoff_utc": start.isoformat(),
            "result_observed_at_utc": (start + timedelta(hours=4)).isoformat(),
            "home_points": hp, "away_points": ap,
            "neutral_site": neutral, "reference_spread_home": spread,
            "reference_total": total}


def sample():
    return [game(1, "A", "B", 37, 10, days=40),
            game(2, "B", "C", 42, 17, days=38),
            game(3, "C", "A", 14, 24, days=36),
            game(4, "A", "C", 34, 14, days=32),
            game(5, "B", "A", 27, 20, days=28),
            game(6, "C", "B", 21, 26, days=24)]


def test_opponent_adjusted_offense_defense_are_distinct():
    model = fit(sample(), as_of=NOW, season=2025, ridge=0.5)
    assert model["trained_games"] == 6
    assert model["ratings"]["a"]["games"] == 4
    assert model["ratings"]["a"]["attack"] != model["ratings"]["b"]["attack"]
    assert model["ratings"]["a"]["defense"] != model["ratings"]["b"]["defense"]
    p = predict(model, home="A", away="B")
    assert p["schema"] == SCHEMA
    assert p["status"] == "SCREEN_NOT_VALIDATED"
    assert p["market_data_used"] is False
    assert p["play_authority"] is False
    assert p["factor_weights_fitted"] is False


def test_target_result_and_bookmaker_data_never_affect_predicted_spread():
    rows = sample()
    original = predict(fit(rows, as_of=NOW, season=2025),
                       home="A", away="B")
    future = game(7, "A", "B", 111, 0, days=-1)
    polluted = [dict(r, dk_odds=-110, closing_spread=-21,
                     public_tickets=89) for r in rows]
    assert predict(fit(rows + [future], as_of=NOW, season=2025),
                   home="A", away="B") == original
    assert predict(fit(polluted, as_of=NOW, season=2025),
                   home="A", away="B") == original


def test_neutral_site_zeroes_home_edge():
    fitted = fit(sample(), as_of=NOW, season=2025)
    home = predict(fitted, home="A", away="B")
    neutral = predict(fitted, home="A", away="B", neutral_site=True)
    assert home["margin_home"] - neutral["margin_home"] == pytest.approx(4.31, abs=1e-4)
    assert home["total"] == pytest.approx(neutral["total"], abs=1e-4)


def test_dated_qb_talent_weather_and_market_are_audited_without_weights():
    stamp = (NOW - timedelta(days=1)).isoformat()
    qb = {"group": "qb", "name": "projected starter", "value": "Player A",
          "source_url": "https://example.edu/news", "observed_at_utc": stamp}
    talent = dict(qb, group="talent_depth", name="OL availability", value=4)
    market = dict(qb, group="market_context", name="DK spread", value=-3.5)
    stale = dict(qb, observed_at_utc=(NOW + timedelta(seconds=1)).isoformat())
    evidence = factors_before_kickoff([qb, talent, market, stale], as_of=NOW)
    assert len(evidence["accepted"]) == 3
    assert evidence["accepted"][2]["usage"] == "COMPARISON_ONLY"
    assert evidence["point_adjustment"] == 0.0
    assert evidence["accepted"][0]["receipt_authenticated"] is False
    assert evidence["refused"][0]["reason"] == "NOT_OBSERVED_PREGAME"


def test_even_spread_and_total_push_mass_not_assumed_as_win():
    output = predict(fit(sample(), as_of=NOW, season=2025),
                     home="A", away="B")
    ref = reference_probabilities(output, home_spread=-3, total_line=45)
    assert ref["spread_home"]["push"] > 0
    assert ref["total_over"]["push"] > 0
    for key in ("spread_home", "total_over"):
        assert sum(ref[key].values()) == pytest.approx(1)
    half = reference_probabilities(output, home_spread=-3.5, total_line=44.5)
    assert half["spread_home"]["push"] == 0
    assert half["total_over"]["push"] == 0
    assert ref["executable_quote"] is False


def test_model_requires_observed_pregame_result_and_unique_ids():
    future = game(1, "A", "B", 99, 0, days=-1)
    with pytest.raises(ValueError, match="NO_PREGAME_FINALS"):
        fit([future], as_of=NOW, season=2025)
    with pytest.raises(ValueError, match="DUPLICATE_GAME"):
        fit(sample() + [sample()[0]], as_of=NOW, season=2025)
    with pytest.raises(ValueError, match="TIME_MUST_BE_AWARE"):
        fit(sample(), as_of=NOW.replace(tzinfo=None), season=2025)
    with pytest.raises(ValueError, match="FINAL_OR_VENUE_INVALID"):
        fit([dict(sample()[0], neutral_site=None)], as_of=NOW, season=2025)


def test_walk_forward_brier_is_only_historical_research():
    old = [game(i, h, a, hp, ap, days=300 + i, season=2024)
           for i, (h, a, hp, ap) in enumerate([
               ("A", "B", 30, 20), ("B", "C", 42, 13),
               ("C", "A", 10, 27), ("A", "C", 24, 13),
               ("C", "B", 14, 28), ("B", "A", 17, 23)])]
    two = [game(200, "A", "B", 24, 19, days=10, spread=-3.5, total=43.5),
           game(201, "B", "C", 21, 14, days=1, spread=-2, total=35)]
    data = old + two
    report = evaluate(data, season=2025)
    assert report["status"] == "SCREEN_NOT_VALIDATED"
    assert report["eligible"] == 2
    assert report["spread_brier"] is not None
    assert report["total_brier"] is not None
    assert report["play_authority"] is False
    assert report["market_references"] == "RESEARCH_ONLY_NOT_CERTIFIED_EXECUTABLE_CLOSE"
    altered = [dict(row, home_points=110) if row["game_id"] == "200" else row for row in data]
    assert evaluate(altered)["predictions"][0]["predicted_margin"] == report["predictions"][0]["predicted_margin"]


def test_walkforward_does_not_invent_market_reference():
    old = [game(i, h, a, 28, 14, days=300 + i, season=2024)
           for i, (h, a) in enumerate([
               ("A", "B"), ("B", "C"), ("C", "A"), ("A", "C"), ("C", "B"), ("B", "A")])]
    report = evaluate(old + [game(100, "A", "B", 30, 20, days=1)])
    assert report["eligible"] == 1
    assert report["spread_brier"] is None
    assert report["reference_rows"] == 0
    assert report["predictions"][0]["reason"] == "HISTORICAL_REFERENCE_MISSING"
