from sportsedge.mlb_portfolio_guard import apply_mlb_portfolio_guard


def _row(game_id, market, odds, edge, ev, kelly, selection):
    return {
        "game_id": str(game_id),
        "market": market,
        "selection": selection,
        "side": selection,
        "american_odds": odds,
        "underlying_moneyline_odds": odds,
        "edge": edge,
        "ev_per_dollar": ev,
        "kelly_fraction": kelly,
        "bet_status": "OFFICIAL_BET",
    }


def test_max_one_underdog_ml_and_no_favorite_manufacture():
    rows = [
        _row(1, "MONEYLINE", 120, 0.060, 0.12, 0.015, "DOG_A"),
        _row(2, "MONEYLINE", 135, 0.055, 0.11, 0.015, "DOG_B"),
        _row(3, "MONEYLINE", -145, 0.010, 0.01, 0.005, "FAV_C"),
    ]
    out = apply_mlb_portfolio_guard(rows)
    dogs = [r for r in out if r["american_odds"] > 100 and r["market"] == "MONEYLINE"]
    assert sum(r["bet_status"] == "OFFICIAL_BET" for r in dogs) == 1
    assert next(r for r in out if r["selection"] == "FAV_C")["bet_status"] == "OFFICIAL_BET"


def test_max_two_underdog_side_positions_and_total_kelly_cap():
    rows = [
        _row(1, "RUN_LINE", 110, 0.070, 0.14, 0.015, "DOG_A"),
        _row(2, "RUN_LINE", 115, 0.060, 0.13, 0.015, "DOG_B"),
        _row(3, "RUN_LINE", 120, 0.050, 0.12, 0.015, "DOG_C"),
    ]
    out = apply_mlb_portfolio_guard(rows)
    official = [r for r in out if r["bet_status"] == "OFFICIAL_BET"]
    assert len(official) == 2
    assert abs(sum(r["kelly_fraction"] for r in official) - 0.020) < 1e-12


def test_validated_calibration_disables_interim_concentration_guard():
    rows = [
        _row(1, "MONEYLINE", 120, 0.060, 0.12, 0.015, "DOG_A"),
        _row(2, "MONEYLINE", 135, 0.055, 0.11, 0.015, "DOG_B"),
    ]
    out = apply_mlb_portfolio_guard(rows, dog_calibration_validated=True)
    assert all(r["bet_status"] == "OFFICIAL_BET" for r in out)
    assert sum(r["kelly_fraction"] for r in out) == 0.030
    assert all(r["portfolio_guard_reason"] == "DOG_CALIBRATION_VALIDATED_PASS_THROUGH" for r in out)


def test_non_side_markets_unchanged():
    row = {
        "game_id": "9",
        "market": "TOTALS",
        "side": "UNDER",
        "selection": "UNDER",
        "american_odds": -110,
        "edge": 0.05,
        "ev_per_dollar": 0.10,
        "kelly_fraction": 0.012,
        "bet_status": "OFFICIAL_BET",
    }
    out = apply_mlb_portfolio_guard([row])
    assert out[0]["bet_status"] == "OFFICIAL_BET"
    assert out[0]["kelly_fraction"] == 0.012
