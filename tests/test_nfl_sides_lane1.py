"""Lane 1 (#2384): NFL sides de-compression + push-aware ML / integer 3/7 spreads.

Written before the production wiring (failing first). Research only: the
#2384 WATCH hold stays because the holdout receipt does not pass the
work-order bar (see artifacts/nfl_sides_lane1_backtest.json).
"""
import json
from pathlib import Path

import pytest

from artifacts import free_models as fm
from sportsedge.sports.nfl import side_margin_model as smm

RECEIPT = Path(__file__).resolve().parents[1] / "artifacts" / "nfl_sides_lane1_backtest.json"


def test_probabilities_sum_to_one_and_are_symmetric():
    for market, line in (("ML", None), ("SPREAD", -3), ("SPREAD", -3.5), ("SPREAD", 7)):
        w, p, l = smm.price_side(market, "HOME", line, 2.0)
        assert abs(w + p + l - 1) < 1e-9
        flip = None if line is None else -line
        w2, p2, l2 = smm.price_side(market, "AWAY", flip, 2.0)
        assert abs(w - l2) < 1e-9 and abs(p - p2) < 1e-9


def test_integer_key_numbers_carry_real_push_mass():
    # Home favored by 3: a -3 push should be ~9-10% (NFL key number), far
    # above the old +/-0.5 normal slice (~2.8%).
    _, push3, _ = smm.price_side("SPREAD", "HOME", -3, 3.0)
    _, push7, _ = smm.price_side("SPREAD", "HOME", -7, 7.0)
    _, push4, _ = smm.price_side("SPREAD", "HOME", -4, 4.0)
    assert push3 > 0.075
    assert push7 > 0.045
    assert push3 > push4 and push7 > push4
    assert smm.price_side("SPREAD", "HOME", -3.5, 3.0)[1] == 0.0


def test_moneyline_tie_is_a_small_push():
    w, p, l = smm.price_side("ML", "HOME", None, 0.0)
    assert 0 < p < 0.01
    assert abs(w - l) < 1e-9


def test_margin_rating_is_not_compressed():
    # Five straight 10-point wins vs five 10-point losses. The old rule
    # (0.12 * avg, capped at 3) moved the margin 2.4 points; the fitted
    # model moves it far more.
    d = smm.margin_rating_diff([10] * 5, [-10] * 5)
    assert d > 8
    assert smm.margin_rating_diff([], []) == 0.0
    with pytest.raises(ValueError):
        smm.margin_rating_diff([float("nan")], [])


def test_invalid_inputs_fail_closed():
    for args in (("TOTAL", "HOME", 44), ("SPREAD", "OVER", -3), ("SPREAD", "HOME", None),
                 ("SPREAD", "HOME", -3.25), ("SPREAD", "HOME", float("inf"))):
        with pytest.raises(ValueError):
            smm.price_side(*args, 1.0)


def test_free_models_nfl_sides_use_key_number_model():
    # home_mean - away_mean = 3 -> HOME -3 push mass from the key-number model.
    w, p = fm.model_probability("NFL", "SPREAD", "HOME", -3, 23.5, 20.5)
    assert p > 0.075
    w_ml, p_ml = fm.model_probability("NFL", "ML", "HOME", None, 22.0, 22.0)
    assert 0 < p_ml < 0.01
    # CFB unchanged (still the normal slice).
    _, cfb_push = fm.model_probability("CFB", "SPREAD", "HOME", -3, 31.0, 28.0)
    assert cfb_push < 0.03


def test_free_models_nfl_rating_decompression_preserves_total():
    hr, ar = fm.nfl_decompressed_ratings(1.2, -1.2, [10] * 5, [-10] * 5)
    assert hr - ar > 8
    assert abs((hr + ar) - (1.2 + -1.2)) < 1e-9


def test_backtest_receipt_frozen_and_honest():
    r = json.loads(RECEIPT.read_text())
    assert r["model_id"] == smm.MODEL_ID
    assert r["train_seasons"] == [2006, 2020] and r["holdout_seasons"] == [2021, 2025]
    assert r["frozen_params_equal_train_only_refit"] is True
    fp = r["frozen_params"]
    assert fp["RATING_B"] == smm.RATING_B and fp["RATING_K"] == smm.RATING_K
    assert fp["MARGIN_SD"] == smm.MARGIN_SD
    assert {int(k): v for k, v in fp["KEY_WEIGHTS"].items()} == smm.KEY_WEIGHTS
    assert r["research_only"] is True and r["validated_profitability"] is False
    # The receipt does not pass the work-order bar, so the #2384 hold stays.
    assert not any(r["work_order_pass_checks"].values())
    assert fm.NFL_SIDE_WATCH_STATUS == "WATCH_NFL_SIDE_UNVALIDATED"
