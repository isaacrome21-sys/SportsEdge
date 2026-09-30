from sportsedge.mlb_quote_move_guard import STATUS, apply_quote_move_guard, load_move_guard, move_reason


def test_thresholds_are_frozen() -> None:
    cfg = load_move_guard()
    assert cfg["thresholds"] == {"ml_american_cents": 40, "total_runs": 1.0, "rl_favorite_flip": True}


def test_phi_ml_plus152_would_need_confirm() -> None:
    cfg = load_move_guard()
    reason = move_reason(
        {"market": "MONEYLINE", "american_odds": 152, "side": "AWAY"},
        {"market_type": "MONEYLINE", "price": -117, "side": "AWAY"},
        cfg["thresholds"],
    )
    assert reason == "QUOTE_MOVE_NEEDS_CONFIRM"


def test_bos_total_8_5_would_need_confirm() -> None:
    cfg = load_move_guard()
    reason = move_reason(
        {"market": "TOTALS", "line": 8.5},
        {"market_type": "TOTALS", "line": 6.5},
        cfg["thresholds"],
    )
    assert reason == "QUOTE_MOVE_NEEDS_CONFIRM"


def test_rl_favorite_flip_needs_confirm() -> None:
    cfg = load_move_guard()
    reason = move_reason(
        {"market": "RUN_LINE", "line": 1.5},
        {"market_type": "RUN_LINE", "line": -1.5},
        cfg["thresholds"],
    )
    assert reason == "QUOTE_MOVE_NEEDS_CONFIRM"


def test_small_ml_tick_stays_actionable() -> None:
    rows = [{
        "game_id": "849848",
        "market": "MONEYLINE",
        "american_odds": -142,
        "status": "ACTIONABLE",
        "scored_status": "ACTIONABLE",
    }]
    prior = [{"game_pk": 849848, "market_type": "MONEYLINE", "price": -136}]
    out = apply_quote_move_guard(rows, prior)
    assert out[0]["status"] == "ACTIONABLE"


def test_actionable_becomes_needs_confirm_not_blocked() -> None:
    rows = [{
        "game_id": "849841",
        "market": "MONEYLINE",
        "american_odds": 152,
        "status": "ACTIONABLE",
        "scored_status": "ACTIONABLE",
    }]
    prior = [{"game_pk": 849841, "market_type": "MONEYLINE", "price": -117}]
    out = apply_quote_move_guard(rows, prior)
    assert out[0]["status"] == STATUS
    assert out[0]["scored_status"] == STATUS
    assert "QUOTE_MOVE_NEEDS_CONFIRM" in out[0]["presentation_reason_codes"]
