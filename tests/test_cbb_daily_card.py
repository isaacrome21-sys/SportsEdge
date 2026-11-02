import json
import math

from sportsedge.cbb_daily_card import (
    SIGMA, card_rows, fixtures_from_espn, phi, render_card_markdown, stars,
)


def _comp(side, tid, name, short, abbr):
    return {"homeAway": side, "team": {"id": tid, "displayName": name,
            "shortDisplayName": short, "location": short, "abbreviation": abbr}}


EVENTS = [{
    "id": "401", "date": "2026-11-03T00:00Z",           # Nov 2, 6:00 PM CT
    "competitions": [{"neutralSite": False, "competitors": [
        _comp("home", "2335", "Liberty Flames", "Liberty", "LIB"),
        _comp("away", "2272", "High Point Panthers", "High Point", "HPU")]}],
}, {
    "id": "402", "date": "2026-11-03T01:00Z",
    "competitions": [{"neutralSite": True, "competitors": [
        _comp("home", "1", "Queens Royals", "Queens", "QUOC"),
        _comp("away", "2", "Winthrop Eagles", "Winthrop", "WIN")]}],
}, {
    "id": "499", "date": "2026-11-10T00:00Z",           # a week later
    "competitions": [{"neutralSite": False, "competitors": [
        _comp("home", "2335", "Liberty Flames", "Liberty", "LIB"),
        _comp("away", "2272", "High Point Panthers", "High Point", "HPU")]}],
}]
D = "2026-11-02"


def test_sigma_from_screen_mae():
    assert abs(SIGMA["SPREAD"] - 8.899 * math.sqrt(math.pi / 2)) < 1e-9
    assert 11.0 < SIGMA["SPREAD"] < 11.3 and 17.2 < SIGMA["TOTAL"] < 17.4


def test_fixture_match_names_and_corroborated_id():
    board = {"games": [
        {"away": "High Point Panthers", "home": "Liberty Flames", "espn_event_id": None},
        {"away": "Winthrop", "home": "Queens", "espn_event_id": "402"},
        {"away": "Nobody U", "home": "Liberty Flames", "espn_event_id": None},
    ]}
    fx, notes = fixtures_from_espn(board, EVENTS, D)
    hp = fx["High Point Panthers@Liberty Flames"]
    assert (hp["espn_event_id"], hp["away_espn_id"], hp["home_espn_id"]) == ("401", "2272", "2335")
    assert fx["Winthrop@Queens"]["neutral_site"] is True
    assert len(fx) == 2 and "no ESPN game" in notes[0]


# ---- regressions, review 5731013111 / 5731013239 (head f778791f) ----

def test_r1_supplied_id_naming_other_teams_is_refused_not_fallback():
    board = {"games": [{"away": "High Point Panthers", "home": "Liberty Flames", "espn_event_id": "402"}]}
    fx, notes = fixtures_from_espn(board, EVENTS, D)
    assert fx == {} and "ESPN_EVENT_ID_TEAM_CONFLICT" in notes[0]


def test_r1_supplied_id_unknown_or_off_date_is_refused():
    for eid, code in (("wrong", "ESPN_EVENT_ID_UNKNOWN"), ("499", "ESPN_EVENT_DATE_MISMATCH")):
        board = {"games": [{"away": "High Point Panthers", "home": "Liberty Flames", "espn_event_id": eid}]}
        fx, notes = fixtures_from_espn(board, EVENTS, D)
        assert fx == {} and code in notes[0]


def test_r1_name_match_only_considers_slate_date():
    fx, _ = fixtures_from_espn({"games": [{"away": "High Point Panthers", "home": "Liberty Flames"}]}, EVENTS, D)
    assert fx["High Point Panthers@Liberty Flames"]["espn_event_id"] == "401"
    fx, notes = fixtures_from_espn({"games": [{"away": "High Point Panthers", "home": "Liberty Flames"}]},
                                   EVENTS, "2026-11-05")
    assert fx == {} and "no ESPN game" in notes[0]


def _rec(market, gap, side, line, a=-110, b=-110, model=None, **over):
    rec = {"market": market, "gap": gap, "designated_side": side, "line": line,
           "side_a_price": a, "side_b_price": b, "classification": "PICKED",
           "espn_event_id": "401", "tip_utc": "2026-11-03T00:00:00+00:00",
           "row_id": f"x:{market}", "away_team": "hpu", "home_team": "lib",
           "engine_id": "CBB_TORVIK_EFFICIENCY_V1", "counted": False,
           "verified_play": False, "freeze_state": "DRAFT_NOT_IN_FORCE", "label": "NON_COUNTED",
           "side_a_captured_at": "2026-11-02T18:00:00+00:00",
           "side_b_captured_at": "2026-11-02T18:00:00+00:00", "capture_source": "DK_CAPTURE",
           "model_margin_home_candidate": (model if market == "SPREAD" else 0),
           "model_total_candidate": (model if market == "TOTAL" else 0)}
    rec.update(over)
    return rec


def _fx():
    return fixtures_from_espn({"games": [{"away": "High Point Panthers", "home": "Liberty Flames"}]}, EVENTS, D)[0]


def test_card_rows_ev_side_status_and_headline():
    priced = {"records": [
        _rec("SPREAD", -2.7, "AWAY", 7.5, a=-112, b=-108, model=4.8),
        _rec("TOTAL", -4.6, "UNDER", 155.5, a=-105, b=-115, model=150.9),
        {"classification": "PASSED"},
    ]}
    rows = card_rows(priced, _fx())
    assert all(r["bucket"] == "HEADLINE" for r in rows) and rows[0]["ev"] >= rows[1]["ev"]
    total = next(r for r in rows if r["market"] == "TOTAL")
    assert total["pick"] == "Under 155.5" and total["price"] == -115
    p = phi(4.6 / SIGMA["TOTAL"])
    assert abs(total["ev"] - (p * (100 / 115) - (1 - p))) < 1e-12
    assert (total["counted"], total["verified_play"], total["label"]) == (False, False, "NON_COUNTED")
    spread = next(r for r in rows if r["market"] == "SPREAD")
    assert spread["pick"] == "High Point +7.5" and spread["price"] == -112


def test_r2_reviewer_repro_minus_200_and_49pct_never_headlines():
    rows = card_rows({"records": [_rec("SPREAD", 30, "HOME", 5, b=-200, model=35)]}, _fx())
    assert rows[0]["bucket"] == "EXCLUDED_PRICE_CAP"
    rows = card_rows({"records": [_rec("SPREAD", 30, "HOME", 5, b=-110, model=35)]}, _fx())
    assert rows[0]["ev"] >= 0.40 and rows[0]["bucket"] == "OVERCONFIDENCE"
    md = render_card_markdown(rows, D, {"records": [1]}, [], "v")
    assert "EV +" not in md.split("Too-good")[0]          # not headlined
    assert "Too-good-to-be-true" in md


def test_r2_self_declared_or_malformed_rows_are_refused():
    bad = [
        _rec("SPREAD", 3, "HOME", 1, b=-1, model=4),                 # payout(-1) exploit
        _rec("SPREAD", float("nan"), "HOME", 1, model=4),
        _rec("SPREAD", 3, "HOME", 1, model=4, counted=True),
        _rec("SPREAD", 3, "HOME", 1, model=4, engine_id="OTHER"),
        _rec("SPREAD", 3, "HOME", 1, model=4, side_a_captured_at=None),
    ]
    rows = card_rows({"records": bad}, _fx())
    assert [r["bucket"] for r in rows] == ["REFUSED"] * 5
    assert {r["reason"] for r in rows} == {"PRICE_INVALID", "CARD_RECORD_INVALID",
                                          "CARD_RECORD_NOT_RUNNER_OUTPUT", "QUOTE_PROVENANCE_MISSING"}


def test_below_floor_and_stars():
    rows = card_rows({"records": [_rec("SPREAD", 2.2, "HOME", -1.0, a=-140, b=-140, model=1.2)]}, _fx())
    assert rows[0]["bucket"] == "BELOW_FLOOR"
    assert (stars(0.01), stars(0.05), stars(0.12), stars(0.2)) == (1, 2, 4, 5)


def test_render_empty_and_refusals():
    md = render_card_markdown([], D,
                              {"records": [], "refusals": [{"market": None, "espn_event_id": "9",
                                                            "reason": "ILLINOIS_COLLEGE_EXCLUDED"}]},
                              ["x: no ESPN game found"], "Ratings: morning Torvik vintage.")
    assert "No plays clear" in md and "ILLINOIS_COLLEGE_EXCLUDED" in md and "Not on card (2)" in md
    assert "assuming normal errors" in md


def test_r4_card_time_pull_keeps_its_label(tmp_path, monkeypatch):
    import importlib, sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
    m = importlib.import_module("run_cbb_daily_card")
    monkeypatch.setattr(m, "_get", lambda url: b"team,adjoe\nA,1\n")
    store = tmp_path / "torvik"
    d, note = m.ensure_vintage(D, store)
    assert d.name == "torvik_cardtime" and "not the morning vintage" in note
    assert not (store / f"{D}.json").exists()                     # admitted store untouched
    d2, note2 = m.ensure_vintage(D, store)                         # reuse keeps label
    assert d2 == d and "not the morning vintage" in note2
    store.mkdir()
    (store / f"{D}.csv").write_text("x")
    (store / f"{D}.json").write_text(json.dumps({"pulled_at_utc": "2026-11-02T12:00:00Z"}))
    d3, note3 = m.ensure_vintage(D, store)
    assert d3 == store and note3.startswith("Ratings: morning Torvik vintage")


def test_card_json_is_strict_json_even_with_refusals():
    rows = card_rows({"records": [_rec("SPREAD", 3, "HOME", 1, b=-1, model=4),
                                  _rec("TOTAL", -4.6, "UNDER", 155.5, model=150.9)]}, _fx())
    json.loads(json.dumps(rows, allow_nan=False))
    assert rows[-1]["bucket"] == "REFUSED"
