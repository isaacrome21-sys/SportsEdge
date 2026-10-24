from sportsedge.cfb_spread_price_gate import assess_spread


def test_push_aware_ev():
    result = assess_spread(price_american=-110, cover_probability=.55,
                           push_probability=.05, loss_probability=.40,
                           quote_current=True, model_verified=True)
    assert result.status == "PLAY"
    assert result.expected_profit_per_unit > 0
    assert abs(result.conditional_cover - .55/.95) < 1e-12


def test_price_cap_and_illinois_exclusion():
    args = dict(price_american=-170, cover_probability=.6,
                push_probability=0, loss_probability=.4,
                quote_current=True, model_verified=True)
    assert assess_spread(**args).reason == "STRAIGHT_PRICE_CAP"
    args["price_american"] = -110
    assert assess_spread(**args, illinois_college_team=True).reason == "ILLINOIS_COLLEGE_EXCLUDED"


def test_missing_or_unverified_inputs_fail_closed():
    args = dict(price_american=-110, cover_probability=.6,
                push_probability=0, loss_probability=.4,
                quote_current=True, model_verified=True)
    assert assess_spread(**(args | {"quote_current": False})).status == "PASS"
    assert assess_spread(**(args | {"model_verified": False})).status == "PASS"
    assert assess_spread(**(args | {"cover_probability": None})).status == "PASS"
    assert assess_spread(**(args | {"loss_probability": .3})).status == "PASS"


def test_nonpositive_ev_passes():
    result = assess_spread(price_american=-110, cover_probability=.45,
                           push_probability=0, loss_probability=.55,
                           quote_current=True, model_verified=True)
    assert result.status == "PASS"
    assert result.expected_profit_per_unit < 0
