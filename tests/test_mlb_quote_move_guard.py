from sportsedge.mlb_quote_move_guard import STATUS, american_cents, apply_quote_move_guard, load_move_guard, move_reason


def test_thresholds_are_frozen() -> None:
    cfg = load_move_guard()
    assert cfg["thresholds"] == {"ml_american_cents": 40, "total_runs": 1.0, "rl_favorite_flip": True}


def test_phi_ml_plus152_would_need_confirm() -> None:
    cfg = load_move_guard()
    reason = move_reason(
        {"market": "MONEYLINE", "side": "AWAY", "american_odds": 152},
        {"market_type": "MONEYLINE", "side": "AWAY", "price": -117},
        cfg["thresholds"],
    )
    assert reason == "QUOTE_MOVE_NEEDS_CONFIRM"


def test_bos_total_8_5_would_need_confirm() -> None:
    cfg = load_move_guard()
    reason = move_reason(
        {"market": "TOTALS", "side": "OVER", "line": 8.5},
        {"market_type": "TOTALS", "side": "OVER", "line": 6.5},
        cfg["thresholds"],
    )
    assert reason == "QUOTE_MOVE_NEEDS_CONFIRM"


def test_rl_favorite_flip_needs_confirm() -> None:
    cfg = load_move_guard()
    reason = move_reason(
        {"market": "RUN_LINE", "side": "AWAY", "line": 1.5},
        {"market_type": "RUN_LINE", "side": "AWAY", "line": -1.5},
        cfg["thresholds"],
    )
    assert reason == "QUOTE_MOVE_NEEDS_CONFIRM"


def test_pickem_ten_cent_move_is_not_forty() -> None:
    assert american_cents(-105, 105) == 10
    cfg = load_move_guard()
    reason = move_reason(
        {"market": "MONEYLINE", "side": "HOME", "american_odds": 105},
        {"market_type": "MONEYLINE", "side": "HOME", "price": -105},
        cfg["thresholds"],
    )
    assert reason is None


def test_two_sided_prior_with_no_move_flags_nothing() -> None:
    rows = [
        {"game_id": "849846", "market": "MONEYLINE", "side": "AWAY", "american_odds": 128, "status": "ACTIONABLE", "scored_status": "ACTIONABLE"},
        {"game_id": "849846", "market": "MONEYLINE", "side": "HOME", "american_odds": -155, "status": "ACTIONABLE", "scored_status": "ACTIONABLE"},
        {"game_id": "849846", "market": "RUN_LINE", "side": "AWAY", "line": 1.5, "american_odds": -175, "status": "ACTIONABLE", "scored_status": "ACTIONABLE"},
        {"game_id": "849846", "market": "RUN_LINE", "side": "HOME", "line": -1.5, "american_odds": 142, "status": "ACTIONABLE", "scored_status": "ACTIONABLE"},
    ]
    prior = [
        {"game_pk": 849846, "market_type": "MONEYLINE", "side": "AWAY", "price": 128},
        {"game_pk": 849846, "market_type": "MONEYLINE", "side": "HOME", "price": -155},
        {"game_pk": 849846, "market_type": "RUN_LINE", "side": "AWAY", "line": 1.5, "price": -179},
        {"game_pk": 849846, "market_type": "RUN_LINE", "side": "HOME", "line": -1.5, "price": 147},
    ]
    out = apply_quote_move_guard(rows, prior)
    assert all(row["status"] == "ACTIONABLE" for row in out)
    assert all(not row.get("presentation_reason_codes") for row in out)


def test_small_ml_tick_stays_actionable() -> None:
    rows = [{
        "game_id": "849848",
        "market": "MONEYLINE",
        "side": "HOME",
        "american_odds": -142,
        "status": "ACTIONABLE",
        "scored_status": "ACTIONABLE",
    }]
    prior = [{"game_pk": 849848, "market_type": "MONEYLINE", "side": "HOME", "price": -136}]
    out = apply_quote_move_guard(rows, prior)
    assert out[0]["status"] == "ACTIONABLE"


def test_actionable_becomes_needs_confirm_not_blocked() -> None:
    rows = [{
        "game_id": "849841",
        "market": "MONEYLINE",
        "side": "AWAY",
        "american_odds": 152,
        "status": "ACTIONABLE",
        "scored_status": "ACTIONABLE",
    }]
    prior = [{"game_pk": 849841, "market_type": "MONEYLINE", "side": "AWAY", "price": -117}]
    out = apply_quote_move_guard(rows, prior)
    assert out[0]["status"] == STATUS
    assert out[0]["scored_status"] == STATUS
    assert "QUOTE_MOVE_NEEDS_CONFIRM" in out[0]["presentation_reason_codes"]
