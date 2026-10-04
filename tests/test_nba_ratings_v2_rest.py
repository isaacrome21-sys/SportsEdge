import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import backtest_nba_ratings_v2_rest as v2  # noqa: E402


def _g(date, home, away, season=2015):
    return {"season": season, "date": date, "home": home, "away": away}


def test_add_rest_uses_only_earlier_games_and_flags_b2b():
    rows = v2.add_rest([_g(20151027, "A", "B"), _g(20151028, "B", "C"), _g(20151031, "A", "C")])
    by = {(r["date"], r["home"]): r for r in rows}
    first = by[(20151027, "A")]
    assert first["rest_h"] == v2.REST_CAP and first["rest_a"] == v2.REST_CAP
    second = by[(20151028, "B")]
    assert second["rest_h"] == 1 and second["b2b_h"] == 1 and second["b2b_a"] == 0
    third = by[(20151031, "A")]
    assert third["rest_h"] == 4 and third["rest_a"] == 3 and third["b2b_a"] == 0


def test_rest_resets_each_season():
    rows = v2.add_rest([_g(20160410, "A", "B", 2015), _g(20160411, "A", "B", 2016)])
    assert rows[1]["rest_h"] == v2.REST_CAP and rows[1]["b2b_h"] == 0


def test_ols_recovers_exact_linear_fit():
    X = [[1.0, x, x * x % 3] for x in range(10)]
    y = [2.0 + 0.5 * x[1] - 1.5 * x[2] for x in X]
    c = v2.ols(X, y)
    assert [round(v, 6) for v in c] == [2.0, 0.5, -1.5]
