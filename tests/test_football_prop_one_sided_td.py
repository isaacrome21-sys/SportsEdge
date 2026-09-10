from math import isclose

from sportsedge.football_prop_readiness import _apply_one_sided_anytime_td_economics


def _row(**overrides):
    row = {
        "provider_market": "player_anytime_td",
        "model_p": 0.64,
        "push_p": 0.0,
        "american_odds": -150,
        "paired_price_available": False,
        "quote_fresh": True,
        "stale_quote": False,
        "fair_market_p": None,
        "edge": None,
        "ev_per_dollar": None,
    }
    row.update(overrides)
    return row


def test_one_sided_anytime_td_economics_uses_existing_model_p_only():
    row = _row()

    assert _apply_one_sided_anytime_td_economics(row) is True
    assert row["fair_market_p"] is None
    assert row["market_no_vig_p"] == "UNAVAILABLE_ONE_SIDED"
    assert isclose(row["raw_break_even_p"], 0.60, rel_tol=0.0, abs_tol=1e-12)
    assert isclose(
        row["model_fair_american_odds"],
        -177.77777777777777,
        rel_tol=0.0,
        abs_tol=1e-9,
    )
    assert isclose(row["ev_per_dollar"], 0.06666666666666665, rel_tol=0.0, abs_tol=1e-12)
    assert row["edge"] is None
    assert row["economics_basis"] == "ONE_SIDED_OFFER_VS_MODEL_P"
    assert row["devig_status"] == "UNAVAILABLE_ONE_SIDED"
    assert row["promotion_lane"] == "EXPERIMENTAL_ONE_SIDED_ANYTIME_TD"


def test_exception_does_not_apply_to_paired_anytime_td():
    row = _row(paired_price_available=True)

    assert _apply_one_sided_anytime_td_economics(row) is False
    assert row["ev_per_dollar"] is None


def test_exception_does_not_apply_to_two_plus_td():
    row = _row(provider_market="player_tds_over")

    assert _apply_one_sided_anytime_td_economics(row) is False
    assert row["ev_per_dollar"] is None


def test_exception_does_not_apply_to_stale_quote():
    row = _row(quote_fresh=False, stale_quote=True)

    assert _apply_one_sided_anytime_td_economics(row) is False
    assert row["ev_per_dollar"] is None


def test_exception_never_creates_model_p():
    row = _row(model_p=None)

    assert _apply_one_sided_anytime_td_economics(row) is False
    assert row["model_p"] is None
    assert row["ev_per_dollar"] is None


def test_legacy_paired_price_field_still_blocks_one_sided_path():
    row = _row()
    row.pop("paired_price_available")
    row["paired_price_present"] = True

    assert _apply_one_sided_anytime_td_economics(row) is False
    assert row["ev_per_dollar"] is None
