from sportsedge.sports.nfl.v2k_attempt5_market_calibration import (
    candidate_probability,
    fair_market_center,
    line_feature,
    evaluate_fold,
)


def _row(season, week, outcome, *, market="spread", base=0.51, line=-3.0):
    row = {
        "game_id": f"{season}-{week}-{market}",
        "season": season,
        "week": week,
        "spread_line": -3.0,
        "total_line": 44.0,
        "base_home_cover_probability": 0.51,
        "base_over_probability": 0.51,
        "home_cover_outcome": outcome,
        "over_outcome": outcome,
    }
    if market == "spread":
        row["spread_line"] = line
        row["base_home_cover_probability"] = base
    else:
        row["total_line"] = line
        row["base_over_probability"] = base
    return row


def test_identity_candidate_exactly_reproduces_market_baseline():
    for market, line in (("spread", -7.0), ("total", 51.5)):
        for p in (0.35, 0.5, 0.67):
            out = candidate_probability(
                p, line, market=market, intercept=0.0, line_beta=0.0
            )
            assert abs(out - p) < 1e-12


def test_line_feature_is_bounded_and_market_specific():
    assert line_feature("spread", 100.0) == 2.0
    assert line_feature("spread", -100.0) == -2.0
    assert line_feature("total", 44.0) == 0.0
    assert line_feature("total", 100.0) == 2.0


def test_outer_fold_parameter_selection_cannot_see_test_season_outcomes():
    rows = []
    for season in (2018, 2019, 2020):
        for week in range(1, 13):
            rows.append(_row(season, week, int((week + season) % 2 == 0)))
    for week in range(1, 13):
        rows.append(_row(2021, week, 0))
    a = evaluate_fold(rows, test_season=2021, market="spread")

    poisoned = [dict(r) for r in rows]
    for row in poisoned:
        if row["season"] == 2021:
            row["home_cover_outcome"] = 1
    b = evaluate_fold(poisoned, test_season=2021, market="spread")

    assert a["selected_intercept"] == b["selected_intercept"]
    assert a["selected_line_beta"] == b["selected_line_beta"]


def test_fair_center_is_monotonic_in_calibrated_probability():
    low = fair_market_center(line=-3.0, probability=0.45, market="spread")
    mid = fair_market_center(line=-3.0, probability=0.50, market="spread")
    high = fair_market_center(line=-3.0, probability=0.55, market="spread")
    assert low < mid < high
    assert abs(mid - (-3.0)) < 1e-12
