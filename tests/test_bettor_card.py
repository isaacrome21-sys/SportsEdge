from sportsedge.bettor_card import build_bettor_card, enrich_result, REQUIRED_MARKETS


def _row(market, status, p=None, odds=-110, reason="test"):
    return {
        "game_id": "1",
        "market": market,
        "entity_id": "" if market in {"MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI"} else "42",
        "line": None if market == "MONEYLINE" else 0.5,
        "side": "HOME" if market in {"MONEYLINE", "RUN_LINE"} else "OVER",
        "american_odds": odds,
        "model_p": p,
        "bet_status": status,
        "reason": reason,
    }


def test_blocked_never_becomes_lean_even_with_model_probability():
    row = enrich_result(_row("MONEYLINE", "BLOCKED", 0.70, +120))
    assert row["classification"] == "BLOCKED"
    assert row["price_needed_for_official"] is None


def test_pass_with_valid_model_becomes_presentation_lean_only():
    row = enrich_result(_row("MONEYLINE", "PASS", 0.55, -125), min_edge=0.02)
    assert row["bet_status"] == "PASS"
    assert row["classification"] == "LEAN"
    assert row["price_needed_for_official"] is not None
    assert row["model_p"] == 0.55


def test_official_status_is_preserved():
    row = enrich_result(_row("MONEYLINE", "OFFICIAL_BET", 0.62, +110))
    assert row["classification"] == "OFFICIAL_BET"
    assert row["price_needed_for_official"] is None
    assert row["edge"] > 0
    assert row["ev_per_dollar"] > 0


def test_all_required_markets_are_accounted_for_even_when_zero():
    card = build_bettor_card([_row("MONEYLINE", "PASS", 0.51, -110)])
    assert tuple(card["market_accounting"].keys()) == REQUIRED_MARKETS
    assert card["market_accounting"]["MONEYLINE"]["candidates"] == 1
    for market in REQUIRED_MARKETS[1:]:
        assert card["market_accounting"][market] == {
            "candidates": 0,
            "official": 0,
            "lean": 0,
            "pass": 0,
            "blocked": 0,
        }


def test_accounting_reconciles_mixed_card_and_never_drops_blocked_market():
    rows = [
        _row("MONEYLINE", "OFFICIAL_BET", 0.62, +110),
        _row("MONEYLINE", "PASS", 0.53, -125),
        _row("RUN_LINE", "BLOCKED", None, +105, "DEPLOYMENT_BLOCKED"),
        _row("PITCHER_BB", "BLOCKED", None, -115, "FORWARD_SHADOW_GATE_PENDING"),
    ]
    card = build_bettor_card(rows)
    assert card["official_bets_count"] == 1
    assert len(card["best_official_bets"]) == 1
    assert len(card["best_leans_prices_to_watch"]) == 1
    assert card["market_accounting"]["MONEYLINE"] == {
        "candidates": 2,
        "official": 1,
        "lean": 1,
        "pass": 0,
        "blocked": 0,
    }
    assert card["market_accounting"]["RUN_LINE"]["blocked"] == 1
    assert card["market_accounting"]["PITCHER_BB"]["blocked"] == 1
    assert len(card["full_card"]) == 4


def test_zero_officials_still_returns_ranked_leans():
    card = build_bettor_card([
        _row("MONEYLINE", "PASS", 0.54, -125),
        _row("TOTALS", "PASS", 0.53, -120),
    ])
    assert card["official_bets_count"] == 0
    assert card["best_official_bets"] == []
    assert len(card["best_leans_prices_to_watch"]) == 2
