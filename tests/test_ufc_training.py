from sportsedge.ufc_training import TrainingRow, evaluate, fit_chronological, update_elo


def _rows(n=120):
    rows = []
    for i in range(n):
        x = (i % 12) - 5.5
        rows.append(TrainingRow(
            fight_date=f"2025-{1 + (i // 28):02d}-{1 + (i % 28):02d}",
            event=f"E{i//10}", fighter_a=f"A{i}", fighter_b=f"B{i}",
            y_a_win=1 if x > 0 else 0,
            features={
                "elo_diff": x * 30,
                "age_diff": -x * 0.2,
                "reach_diff": x * 0.3,
                "height_diff": 0.0,
                "slpm_diff": x * 0.1,
                "sapm_diff": -x * 0.05,
                "str_acc_diff": x * 0.01,
                "str_def_diff": x * 0.01,
                "td_avg_diff": x * 0.04,
                "td_acc_diff": x * 0.005,
                "td_def_diff": x * 0.005,
                "sub_avg_diff": 0.0,
                "recent_win_rate_diff": x * 0.02,
                "sos_diff": x * 0.01,
                "rest_days_diff": 0.0,
                "late_replacement_diff": 0.0,
                "experience_diff": x * 0.4,
            },
        ))
    return rows


def test_chronological_fit_and_holdout_metrics_are_valid():
    model, metrics = fit_chronological(_rows())
    assert metrics.n > 0
    assert 0 <= metrics.brier <= 1
    assert 0 <= metrics.accuracy <= 1
    assert model.probability({"elo_diff": 200}) > model.probability({"elo_diff": -200})


def test_elo_update_is_zero_sum():
    a, b = update_elo(1500, 1500, 1.0)
    assert a > 1500 and b < 1500
    assert round(a + b, 8) == 3000
