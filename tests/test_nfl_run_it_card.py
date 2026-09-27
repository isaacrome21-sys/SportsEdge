import pytest

from sportsedge.nfl_run_it import AUTHORITY_FOOTER, NflRunItError, run_it


NOW = "2026-09-21T10:45:00Z"


def _q(**kwargs):
    base = {
        "game_id": "2026-W3-KC-NYJ",
        "home": "KC",
        "away": "NYJ",
        "book": "dk",
        "retrieved_at": NOW,
    }
    base.update(kwargs)
    return base


def test_empty_slate_is_valid_and_non_certifying():
    card = run_it([], [], as_of=NOW)
    assert card.picks == ()
    assert card.empty_reason == "Nothing looks strong enough."
    text = card.render()
    assert "Nothing looks strong enough." in text
    assert text.endswith(AUTHORITY_FOOTER)


def test_one_sided_quote_is_refused():
    quotes = [_q(market="moneyline", selection="KC", price_american=-150)]
    with pytest.raises(NflRunItError, match="PAIRED_PRICE_REQUIRED"):
        run_it(quotes, [], as_of=NOW)


def test_retrieved_at_is_required_and_stale_quotes_fail_closed():
    missing = [
        _q(market="moneyline", selection="KC", price_american=-150, retrieved_at=None),
        _q(market="moneyline", selection="NYJ", price_american=130),
    ]
    with pytest.raises(NflRunItError, match="QUOTE_RETRIEVED_AT_REQUIRED"):
        run_it(missing, [], as_of=NOW)

    stale = [
        _q(market="moneyline", selection="KC", price_american=-150, retrieved_at="2026-09-21T10:41:59Z"),
        _q(market="moneyline", selection="NYJ", price_american=130, retrieved_at="2026-09-21T10:41:59Z"),
    ]
    with pytest.raises(NflRunItError, match="QUOTE_STALE"):
        run_it(stale, [], as_of=NOW)


def test_future_clock_and_pair_skew_are_refused():
    future = [
        _q(market="moneyline", selection="KC", price_american=-150, retrieved_at="2026-09-21T10:45:31Z"),
        _q(market="moneyline", selection="NYJ", price_american=130),
    ]
    with pytest.raises(NflRunItError, match="QUOTE_CLOCK_SKEW"):
        run_it(future, [], as_of=NOW)

    skewed = [
        _q(market="moneyline", selection="KC", price_american=-150),
        _q(market="moneyline", selection="NYJ", price_american=130, retrieved_at="2026-09-21T10:44:29Z"),
    ]
    estimates = [_q(market="moneyline", selection="KC", line=None, estimate_p=0.70)]
    with pytest.raises(NflRunItError, match="PAIRED_QUOTE_TIME_SKEW"):
        run_it(skewed, estimates, as_of=NOW)


def test_model_p_field_is_forbidden_on_non_certifying_card():
    quotes = [
        _q(market="moneyline", selection="KC", price_american=-150),
        _q(market="moneyline", selection="NYJ", price_american=130),
    ]
    rows = [_q(market="moneyline", selection="KC", line=None, model_p=0.70)]
    with pytest.raises(NflRunItError, match="MODEL_P_FIELD_FORBIDDEN_USE_ESTIMATE_P"):
        run_it(quotes, rows, as_of=NOW)


def test_integer_spread_scalar_estimate_requires_joint_simulations():
    quotes = [
        _q(market="spread", selection="KC", line=-3.0, price_american=-110),
        _q(market="spread", selection="NYJ", line=3.0, price_american=-110),
    ]
    estimates = [_q(market="spread", selection="KC", line=-3.0, estimate_p=0.57)]
    with pytest.raises(NflRunItError, match="SIMULATIONS_REQUIRED_FOR_INTEGER_LINE"):
        run_it(quotes, estimates, as_of=NOW)


def test_integer_spread_simulation_carries_push_mass_into_ev():
    quotes = [
        _q(market="spread", selection="KC", line=-3.0, price_american=-110),
        _q(market="spread", selection="NYJ", line=3.0, price_american=-110),
    ]
    rows = (
        [{"home_score": 27, "away_score": 17} for _ in range(60)]
        + [{"home_score": 27, "away_score": 24} for _ in range(20)]
        + [{"home_score": 20, "away_score": 24} for _ in range(20)]
    )
    card = run_it(
        quotes,
        [],
        simulations={"2026-W3-KC-NYJ": rows},
        edge_floor=0.02,
        as_of=NOW,
    )
    assert len(card.picks) == 1
    pick = card.picks[0]
    assert pick.selection == "KC"
    assert pick.line == -3.0
    assert pick.estimate_p == pytest.approx(0.60)
    assert pick.push_p == pytest.approx(0.20)
    assert pick.market_no_vig_p == pytest.approx(0.50)
    assert pick.ev_per_dollar == pytest.approx(0.60 * (100 / 110) - 0.20)
    assert pick.devig_method == "POWER_V1"


def test_noninteger_markets_rank_only_by_price_economics():
    quotes = [
        _q(market="spread", selection="KC", line=-2.5, price_american=-105),
        _q(market="spread", selection="NYJ", line=2.5, price_american=-115),
        _q(market="total", selection="OVER", line=47.5, price_american=-108),
        _q(market="total", selection="UNDER", line=47.5, price_american=-112),
        _q(game_id="2026-W3-DET-CHI", home="CHI", away="DET", market="moneyline", selection="DET", price_american=150),
        _q(game_id="2026-W3-DET-CHI", home="CHI", away="DET", market="moneyline", selection="CHI", price_american=-170),
    ]
    estimates = [
        _q(market="spread", selection="KC", line=-2.5, estimate_p=0.57),
        _q(market="total", selection="OVER", line=47.5, estimate_p=0.56),
        _q(game_id="2026-W3-DET-CHI", home="CHI", away="DET", market="moneyline", selection="DET", line=None, estimate_p=0.48),
    ]
    card = run_it(quotes, estimates, edge_floor=0.015, as_of=NOW)
    assert card.picks
    evs = [p.ev_per_dollar for p in card.picks]
    assert evs == sorted(evs, reverse=True)
    payload = card.to_dict()
    assert all("score" not in p and "reason" not in p and "model_p" not in p for p in payload["picks"])
    assert payload["authority_footer"] == AUTHORITY_FOOTER


def test_longshot_over_plus_400_uses_sensitivity_gate():
    quotes = [
        _q(market="moneyline", selection="NYJ", price_american=500),
        _q(market="moneyline", selection="KC", price_american=-800),
    ]
    estimates = [_q(market="moneyline", selection="NYJ", line=None, estimate_p=0.20)]
    with pytest.raises(NflRunItError, match="DEVIG_METHOD_SENSITIVITY"):
        run_it(quotes, estimates, as_of=NOW)
