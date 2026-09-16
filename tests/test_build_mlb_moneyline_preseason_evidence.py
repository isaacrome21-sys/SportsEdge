from datetime import datetime, timezone

import numpy as np

from scripts.build_mlb_moneyline_preseason_evidence import (
    Game,
    build_examples,
    calibration_metrics,
    fit_logistic,
    team_prior_stats,
)


def _prior_games():
    rows = []
    pk = 1
    for i in range(120):
        start = datetime(2025, 4, 1 + (i % 28), 18, 0, tzinfo=timezone.utc)
        home = 10 if i % 2 == 0 else 20
        away = 20 if home == 10 else 10
        home_runs = 5 if home == 10 else 3
        away_runs = 2 if away == 20 else 4
        rows.append(Game(2025, pk, start, home, away, home_runs, away_runs))
        pk += 1
    return rows


def test_prior_season_examples_are_strictly_before_target():
    prior = _prior_games()
    target = [Game(2026, 999, datetime(2026, 4, 5, 20, 0, tzinfo=timezone.utc), 10, 20, 4, 2)]
    rows = build_examples(target, prior)
    assert len(rows) == 1
    assert rows[0]["feature_asof_ts"] < rows[0]["event_start_ts"]
    assert rows[0]["home_team_id"] == 10


def test_team_prior_stats_require_real_sample_and_are_market_blind():
    stats = team_prior_stats(_prior_games())
    assert set(stats) == {10, 20}
    assert 0 <= stats[10]["win_pct"] <= 1
    assert "odds" not in stats[10]


def test_logistic_and_calibration_metrics_are_finite():
    x = np.column_stack([np.ones(200), np.linspace(-2, 2, 200)])
    y = (np.arange(200) % 3 != 0).astype(float)
    beta = fit_logistic(x, y, ridge=1.0)
    p = 1.0 / (1.0 + np.exp(-(x @ beta)))
    metrics = calibration_metrics(y, p)
    assert np.isfinite(beta).all()
    assert 0 <= metrics["brier"] <= 1
    assert metrics["log_loss"] >= 0
    assert np.isfinite(metrics["calibration_slope"])
    assert np.isfinite(metrics["calibration_intercept"])
    assert 0 <= metrics["ece_10_equal_frequency"] <= 1
