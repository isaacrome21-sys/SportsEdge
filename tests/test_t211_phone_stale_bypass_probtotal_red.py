"""RED (t211u, #2355): no stale-quote bypass (180s limit kept) and impossible
probability totals are refused, never renormalised."""
from sportsedge.phone_display import build_phone_card
from sportsedge.research_estimate import build_research_estimate
from test_t197_quote_attestation_card import SCREENSHOT, _card, _game_row


def _sel(card):
    return build_phone_card(card)["selections"]


def test_screenshot_with_recorded_age_over_180_is_not_research():
    row = _game_row("QUOTE_FRESHNESS_UNVERIFIED", age=912.4)
    sel = _sel(_card(row, SCREENSHOT))[0]
    assert sel["status"] == "REFRESH REQUIRED"
    assert sel["probability"] is None


def test_blocked_row_annex_with_stale_quote_shows_no_probability():
    est = build_research_estimate(0.61, engine="E", blocker="NO_QUOTE_BASIS")
    row = {"input_index": 0, "sport": "MLB", "market": "PLAYER_HITS",
           "selection": "OVER 0.5", "odds_american": -150,
           "status": "NO_MODEL_OR_MARKET", "reason": "NO_QUOTE_BASIS",
           "research_estimate": est,
           "quote_freshness": {"code": "QUOTE_STALE_OVER_180S", "age_seconds": 400.0,
                               "max_age_seconds": 180}}
    sel = _sel(_card(row))[0]
    assert sel["status"] != "RESEARCH ONLY"
    assert sel["probability"] is None


def test_forged_annex_push_making_total_exceed_one_refused():
    est = build_research_estimate(0.7, engine="E", blocker="NO_QUOTE_BASIS")
    est["push_p"] = 0.5  # p + push = 1.2: impossible
    row = {"input_index": 0, "sport": "NFL", "market": "TOTAL",
           "selection": "OVER 44", "status": "NO_MODEL_OR_MARKET",
           "reason": "NO_QUOTE_BASIS", "research_estimate": est}
    sel = _sel(_card(row))[0]
    assert sel["status"] != "RESEARCH ONLY"
    assert sel["probability"] is None


def _side(i, side, p):
    row = _game_row("QUOTE_FRESHNESS_UNVERIFIED", input_index=i,
                    selection=f"{side} ML", estimate_p=p, fair_american=None,
                    side_key=side)
    return row


def test_two_sides_summing_over_one_are_both_refused_not_renormalised():
    rows = [_side(0, "Seattle Seahawks", 0.62), _side(1, "Denver Broncos", 0.55)]
    for r in rows:
        r["selection"] = r["selection"]
    card = {"evaluated_rows": rows, "summary": {"rows": 2}, "min_ev": 0.02,
            "selection_intake": [dict(SCREENSHOT, side="AWAY"), dict(SCREENSHOT, side="HOME")]}
    sels = _sel(card)
    for s in sels:
        assert s["probability"] is None, s
        assert "PROBABILITY_TOTAL_IMPOSSIBLE" in s["reason"]
    # never renormalised: no row shows a rescaled value
    assert all(s.get("fair_odds") is None for s in sels)


def test_two_sides_summing_to_at_most_one_still_display():
    rows = [_side(0, "Seattle Seahawks", 0.48), _side(1, "Denver Broncos", 0.52)]
    card = {"evaluated_rows": rows, "summary": {"rows": 2}, "min_ev": 0.02,
            "selection_intake": [dict(SCREENSHOT, side="AWAY"), dict(SCREENSHOT, side="HOME")]}
    sels = _sel(card)
    assert [s["probability"] for s in sels] == [0.48, 0.52]
