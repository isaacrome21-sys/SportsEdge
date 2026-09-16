import pytest

from sportsedge.mlb_moneyline_clv import MLBMoneylineCLVError, evaluate_paired_closes, paired_no_vig


def test_paired_no_vig_sums_to_one():
    h, a = paired_no_vig(-150, 135)
    assert h + a == pytest.approx(1.0)
    assert h > a


def test_empty_closes_fail_closed():
    out = evaluate_paired_closes([])
    assert out["status"] == "BLOCKED_NO_ADMISSIBLE_PAIRED_CLOSES"
    assert out["promotion_authority"] is False


def test_model_directed_clv_is_separate_and_non_authoritative():
    out = evaluate_paired_closes([
        {"game_pk": 1, "model_side": "HOME", "model_p": 0.62, "close_home_odds": -140, "close_away_odds": 125},
        {"game_pk": 2, "model_side": "AWAY", "model_p": 0.58, "close_home_odds": 120, "close_away_odds": -130},
    ])
    assert out["n"] == 2
    assert out["devig_method"] == "MULTIPLICATIVE_V1"
    assert out["promotion_authority"] is False


def test_unpaired_close_is_rejected():
    with pytest.raises(MLBMoneylineCLVError):
        evaluate_paired_closes([
            {"game_pk": 1, "model_side": "HOME", "model_p": 0.60, "close_home_odds": -120}
        ])
