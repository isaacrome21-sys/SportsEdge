import math

from sportsedge.cbb_daily_card import (
    SIGMA, card_rows, fixtures_from_espn, phi, render_card_markdown, stars,
)


def _comp(side, tid, name, short, abbr):
    return {"homeAway": side, "team": {"id": tid, "displayName": name,
            "shortDisplayName": short, "location": short, "abbreviation": abbr}}


EVENTS = [{
    "id": "401", "date": "2026-11-03T00:00Z",
    "competitions": [{"neutralSite": False, "competitors": [
        _comp("home", "2335", "Liberty Flames", "Liberty", "LIB"),
        _comp("away", "2272", "High Point Panthers", "High Point", "HPU")]}],
}, {
    "id": "402", "date": "2026-11-03T01:00Z",
    "competitions": [{"neutralSite": True, "competitors": [
        _comp("home", "1", "Queens Royals", "Queens", "QUOC"),
        _comp("away", "2", "Winthrop Eagles", "Winthrop", "WIN")]}],
}]


def test_sigma_from_screen_mae():
    assert abs(SIGMA["SPREAD"] - 8.899 * math.sqrt(math.pi / 2)) < 1e-9
    assert 11.0 < SIGMA["SPREAD"] < 11.3 and 17.2 < SIGMA["TOTAL"] < 17.4


def test_fixture_match_full_names_and_comment_id():
    board = {"games": [
        {"away": "High Point Panthers", "home": "Liberty Flames", "espn_event_id": None},
        {"away": "Winthrop", "home": "Queens", "espn_event_id": "402"},
        {"away": "Nobody U", "home": "Liberty Flames", "espn_event_id": None},
    ]}
    fx, notes = fixtures_from_espn(board, EVENTS, "2026-11-02")
    hp = fx["High Point Panthers@Liberty Flames"]
    assert (hp["espn_event_id"], hp["away_espn_id"], hp["home_espn_id"]) == ("401", "2272", "2335")
    assert fx["Winthrop@Queens"]["neutral_site"] is True
    assert len(fx) == 2 and "no ESPN game" in notes[0]


def _rec(market, gap, side, line, a=-110, b=-110, model=None):
    rec = {"market": market, "gap": gap, "designated_side": side, "line": line,
           "side_a_price": a, "side_b_price": b, "classification": "PICKED",
           "espn_event_id": "401", "tip_utc": "2026-11-03T00:00:00+00:00",
           "row_id": f"x:{market}", "away_team": "hpu", "home_team": "lib",
           "model_margin_home_candidate": (model if market == "SPREAD" else 0),
           "model_total_candidate": (model if market == "TOTAL" else 0)}
    return rec


def test_card_rows_ev_side_and_ranking():
    fx, _ = fixtures_from_espn({"games": [{"away": "High Point Panthers",
                                           "home": "Liberty Flames"}]}, EVENTS, "d")
    priced = {"records": [
        # away spread +7.5 (HPU is the dog? no: away +7.5 means away is the dog)
        _rec("SPREAD", -2.7, "AWAY", 7.5, a=-112, b=-108, model=4.8),
        _rec("TOTAL", -4.6, "UNDER", 155.5, a=-105, b=-115, model=150.9),
        {"classification": "PASSED"},
    ]}
    rows = card_rows(priced, fx)
    assert [r["market"] for r in rows] == ["TOTAL", "SPREAD"] or rows[0]["ev"] >= rows[1]["ev"]
    total = next(r for r in rows if r["market"] == "TOTAL")
    assert total["pick"] == "Under 155.5" and total["price"] == -115
    p = phi(4.6 / SIGMA["TOTAL"])
    assert abs(total["ev"] - (p * (100 / 115) - (1 - p))) < 1e-12
    spread = next(r for r in rows if r["market"] == "SPREAD")
    assert spread["pick"] == "High Point +7.5" and spread["price"] == -112


def test_negative_ev_dropped_and_stars():
    priced = {"records": [_rec("SPREAD", 2.2, "HOME", -1.0, a=-200, b=-300, model=3.2)]}
    assert card_rows(priced, {}) == []
    assert (stars(0.01), stars(0.05), stars(0.12), stars(0.2)) == (1, 2, 4, 5)


def test_render_empty_and_refusals():
    md = render_card_markdown([], "2026-11-02",
                              {"records": [], "refusals": [{"market": None, "espn_event_id": "9",
                                                            "reason": "ILLINOIS_COLLEGE_EXCLUDED"}]},
                              ["x: no ESPN game found"], "Ratings: morning Torvik pull.")
    assert "No plays clear" in md and "ILLINOIS_COLLEGE_EXCLUDED" in md and "Not priced (2)" in md
