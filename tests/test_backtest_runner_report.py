"""End-to-end smoke: recorded 2024 NFL games -> splits -> runner -> report.

The candidate here is a SYNTHETIC stand-in (an oracle at p=0.75), used only
to exercise the harness machinery: PASS/FAIL/conditional verdicts and the
market-baseline-missing flag. It proves nothing about any real factor.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsedge.backtest import outcomes, runner, report
from sportsedge.backtest.splits import walk_forward_splits

FIX = Path(__file__).parent / "fixtures" / "backtest"


def _recorded(url):
    for day in ("20240908", "20240909", "20240912"):
        if "dates=" + day in url:
            return json.loads((FIX / ("nfl_scoreboard_%s.json" % day)).read_text())
    raise AssertionError("unexpected URL " + url)


def _games():
    games = []
    for day in ("20240908", "20240909", "20240912"):
        events = outcomes.fetch_football_scoreboard("nfl", dates=day,
                                                    getter=_recorded)
        games.extend(outcomes.parse_completed_football_games(events))
    assert len(games) == 15
    return games


def _fixtures(games):
    out = []
    for g in games:
        kickoff = datetime.fromisoformat(g["kickoff"].replace("Z", "+00:00"))
        out.append({
            "fixture_id": g["event_id"],
            "kickoff": g["kickoff"],
            "as_of": (kickoff - timedelta(hours=3)).isoformat(),
            "home_team": g["home_team"],
            "away_team": g["away_team"],
        })
    out.sort(key=lambda f: f["kickoff"])
    return out


@pytest.fixture()
def setup():
    games = _games()
    by_id = {g["event_id"]: g for g in games}
    fixtures = _fixtures(games)

    def settle_fn(fixture, market, selection, line):
        return outcomes.settle_game(by_id[fixture["fixture_id"]],
                                    market, selection, line)

    def price_fn(model_name, fixture, as_of, train):
        game = by_id[fixture["fixture_id"]]
        home_won = game["home_score"] > game["away_score"]
        if model_name == "existing":
            return [{"market": "ML", "selection": "HOME", "model_p": 0.55}]
        if model_name == "candidate_good":
            # SYNTHETIC oracle: 0.75 on the true winner. Machinery only.
            sel = "HOME" if home_won else "AWAY"
            return [{"market": "ML", "selection": sel, "model_p": 0.75}]
        if model_name == "candidate_bad":
            sel = "AWAY" if home_won else "HOME"
            return [{"market": "ML", "selection": sel, "model_p": 0.75}]
        raise AssertionError("unknown model " + model_name)

    splits = list(walk_forward_splits(fixtures, min_train=5, test_size=5))
    assert splits, "expected at least one walk-forward split"
    return fixtures, splits, settle_fn, price_fn


def _evaluate(result, models, **kw):
    comp = runner.compare_models(result)
    return report.evaluate(
        candidate=comp["models"][models[1]],
        existing=comp["models"][models[0]],
        baseline_status=comp["baseline"]["status"],
        baseline=comp["baseline"]["summary"],
        **kw)


def test_better_candidate_yields_conditional_pass_with_missing_baseline(setup):
    fixtures, splits, settle_fn, price_fn = setup
    models = ["existing", "candidate_good"]
    result = runner.run_backtest(fixtures=fixtures, splits=splits,
                                 models=models, price_fn=price_fn,
                                 settle_fn=settle_fn, market_baseline=None)
    assert result["baseline"]["status"] == "MISSING"
    assert len(result["records"]["candidate_good"]) >= 5
    verdict = _evaluate(result, models, min_n=5)
    assert verdict["verdict"] == "CONDITIONAL_PASS"
    assert any("MARKET_BASELINE_MISSING" in r for r in verdict["reasons"])
    md = report.to_markdown(verdict,
                            candidate_records=result["records"]["candidate_good"])
    assert "CONDITIONAL_PASS" in md
    assert "MISSING" in md
    assert "calibration" in md.lower()
    parsed = json.loads(report.to_json(verdict))
    assert parsed["verdict"] == "CONDITIONAL_PASS"


def test_worse_candidate_fails_with_reasons(setup):
    fixtures, splits, settle_fn, price_fn = setup
    models = ["existing", "candidate_bad"]
    result = runner.run_backtest(fixtures=fixtures, splits=splits,
                                 models=models, price_fn=price_fn,
                                 settle_fn=settle_fn)
    verdict = _evaluate(result, models, min_n=5)
    assert verdict["verdict"] == "FAIL"
    assert any("BRIER_NOT_IMPROVED" in r for r in verdict["reasons"])


def test_available_baseline_checked_when_supplied(setup):
    fixtures, splits, settle_fn, price_fn = setup
    models = ["existing", "candidate_good"]
    games = {g["event_id"]: g for g in _games()}
    # Archived-style baseline: 0.60 on the true winner (worse than candidate).
    baseline = {}
    for fx in fixtures:
        g = games[fx["fixture_id"]]
        sel = "HOME" if g["home_score"] > g["away_score"] else "AWAY"
        baseline[(fx["fixture_id"], "ML", sel, None)] = 0.60
    result = runner.run_backtest(fixtures=fixtures, splits=splits,
                                 models=models, price_fn=price_fn,
                                 settle_fn=settle_fn,
                                 market_baseline=baseline)
    assert result["baseline"]["status"] == "AVAILABLE"
    verdict = _evaluate(result, models, min_n=5)
    assert verdict["verdict"] == "PASS"


def test_insufficient_sample_fails_closed(setup):
    fixtures, splits, settle_fn, price_fn = setup
    models = ["existing", "candidate_good"]
    result = runner.run_backtest(fixtures=fixtures, splits=splits,
                                 models=models, price_fn=price_fn,
                                 settle_fn=settle_fn)
    verdict = _evaluate(result, models)  # default min_n=30
    assert verdict["verdict"] == "FAIL"
    assert any("INSUFFICIENT_OUT_OF_SAMPLE" in r for r in verdict["reasons"])


def test_degenerate_prediction_rejected(setup):
    fixtures, splits, settle_fn, _ = setup

    def bad_price(model_name, fixture, as_of, train):
        return [{"market": "ML", "selection": "HOME", "model_p": 1.5}]

    with pytest.raises(Exception) as exc:
        runner.run_backtest(fixtures=fixtures, splits=splits,
                            models=["existing"], price_fn=bad_price,
                            settle_fn=settle_fn)
    assert "BACKTEST_PREDICTION_PROBABILITY_INVALID" in str(exc.value)


def test_runner_never_invents_baseline_prices():
    # market_baseline=None must not fabricate records.
    assert runner._baseline_lookup(None) is None
