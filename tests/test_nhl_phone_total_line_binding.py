from scripts.render_nhl_myspari_card import TOTAL_LINE_HOLD, price_row


def _sim():
    return {
        "over_5_5": 0.60,
        "over_6_5": 0.40,
        "home_pl_minus_1_5": 0.30,
    }


def test_supported_total_5_5_uses_exact_5_5_event():
    rendered = price_row("TOTAL", 5.5, -110, -110, _sim())
    assert "model_p=0.600" in rendered
    assert "model_p=0.400" in rendered


def test_supported_total_6_5_uses_exact_6_5_event():
    rendered = price_row("TOTAL", 6.5, -110, -110, _sim())
    assert "model_p=0.400" in rendered
    assert "model_p=0.600" in rendered


def test_whole_number_total_fails_closed_until_push_mass_is_priced():
    assert price_row("TOTAL", 6.0, -110, -110, _sim()) == TOTAL_LINE_HOLD


def test_other_half_point_total_does_not_borrow_nearest_grid_probability():
    assert price_row("TOTAL", 7.5, -110, -110, _sim()) == TOTAL_LINE_HOLD
    assert price_row("TOTAL", 4.5, -110, -110, _sim()) == TOTAL_LINE_HOLD


def test_missing_total_line_fails_closed():
    assert price_row("TOTAL", None, -110, -110, _sim()) == TOTAL_LINE_HOLD
