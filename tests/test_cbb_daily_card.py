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


PRICED_AT = "2026-11-02T18:01:00+00:00"   # 60 s after the _rec captures


def _P(*recs):
    return {"priced_at": PRICED_AT, "records": list(recs)}


def _fx():
    return fixtures_from_espn({"games": [{"away": "High Point Panthers", "home": "Liberty Flames"}]}, EVENTS, D)[0]


def test_card_rows_ev_side_status_and_headline():
    priced = _P(
        _rec("SPREAD", -2.7, "AWAY", 7.5, a=-112, b=-108, model=4.8),
        _rec("TOTAL", -4.6, "UNDER", 155.5, a=-105, b=-115, model=150.9),
        {"classification": "PASSED"},
    )
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
    rows = card_rows(_P(_rec("SPREAD", 30, "HOME", 5, b=-200, model=35)), _fx())
    assert rows[0]["bucket"] == "EXCLUDED_PRICE_CAP"
    rows = card_rows(_P(_rec("SPREAD", 30, "HOME", 5, b=-110, model=35)), _fx())
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
    rows = card_rows(_P(*bad), _fx())
    assert [r["bucket"] for r in rows] == ["REFUSED"] * 5
    assert {r["reason"] for r in rows} == {"PRICE_INVALID", "CARD_RECORD_INVALID",
                                          "CARD_RECORD_NOT_RUNNER_OUTPUT", "QUOTE_PROVENANCE_MISSING"}


def test_below_floor_and_stars():
    rows = card_rows(_P(_rec("SPREAD", 2.2, "HOME", -1.0, a=-140, b=-140, model=1.2)), _fx())
    assert rows[0]["bucket"] == "BELOW_FLOOR"
    assert (stars(0.01), stars(0.05), stars(0.12), stars(0.2)) == (1, 2, 4, 5)


def test_render_empty_and_refusals():
    md = render_card_markdown([], D,
                              {"records": [], "refusals": [{"market": None, "espn_event_id": "9",
                                                            "reason": "ILLINOIS_COLLEGE_EXCLUDED"}]},
                              ["x: no ESPN game found"], "Ratings: morning Torvik vintage.")
    assert "No research candidates clear" in md and "ILLINOIS_COLLEGE_EXCLUDED" in md and "Not on card (2)" in md
    assert "NOT COUNTED · PAPER / 0u · NO PLAY" in md and " plays" not in md
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
    rows = card_rows(_P(_rec("SPREAD", 3, "HOME", 1, b=-1, model=4),
                                  _rec("TOTAL", -4.6, "UNDER", 155.5, model=150.9)), _fx())
    json.loads(json.dumps(rows, allow_nan=False))
    assert rows[-1]["bucket"] == "REFUSED"


def test_r6_canonical_180s_freshness_gate():
    rec = _rec("TOTAL", -4.6, "UNDER", 155.5, a=-105, b=-115, model=150.9)
    fresh = card_rows({"priced_at": "2026-11-02T18:03:00+00:00", "records": [rec]}, _fx())
    assert fresh[0]["bucket"] == "HEADLINE"
    stale = card_rows({"priced_at": "2026-11-02T18:03:01+00:00", "records": [rec]}, _fx())
    assert stale[0]["bucket"] == "STALE_QUOTE" and stale[0]["freshness"]["code"] == "QUOTE_STALE_OVER_180S"
    md = render_card_markdown(stale, D, {"records": [rec]}, [], "v")
    assert "EV +" not in md and "repost fresh lines" in md and "QUOTE_STALE_OVER_180S" in md
    one_side = card_rows({"priced_at": "2026-11-02T18:01:00+00:00",
                          "records": [{**rec, "side_b_captured_at": "2026-11-02T17:50:00+00:00"}]}, _fx())
    assert one_side[0]["bucket"] == "STALE_QUOTE"
    unverified = card_rows({"records": [rec]}, _fx())
    assert unverified[0]["bucket"] == "STALE_QUOTE"


def test_r7_owner_option_a_banner_on_nonempty_card():
    rows = card_rows(_P(_rec("TOTAL", -4.6, "UNDER", 155.5, a=-105, b=-115, model=150.9)), _fx())
    md = render_card_markdown(rows, D, {"records": [1]}, [], "v")
    assert md.count("NOT COUNTED · PAPER / 0u · NO PLAY") == 1
    assert md.index("NO PLAY") < md.index("Under 155.5")      # banner above all rows
    assert "★" in md and "EV +" in md and " plays" not in md


# ---- opening-night slate-date convention (relay #2447, 2026-11-02 05:00Z) ----

OPENER = [{
    "id": "401800001", "date": "2026-11-02T05:00Z",    # 12:00 AM ET Nov 2 = 11:00 PM CT Nov 1
    "competitions": [{"neutralSite": True, "competitors": [
        _comp("home", "2335", "Liberty Flames", "Liberty", "LIB"),
        _comp("away", "2272", "High Point Panthers", "High Point", "HPU")]}],
}]


def test_r8_midnight_et_opener_is_on_the_eastern_slate_date():
    board = {"games": [{"away": "High Point Panthers", "home": "Liberty Flames"}]}
    fx, notes = fixtures_from_espn(board, OPENER, "2026-11-02")
    assert notes == [] and fx["High Point Panthers@Liberty Flames"]["espn_event_id"] == "401800001"
    assert fx["High Point Panthers@Liberty Flames"]["tip_utc"] == "2026-11-02T05:00+00:00"
    # Same game is NOT on the CT calendar date's slate
    fx, notes = fixtures_from_espn(board, OPENER, "2026-11-01")
    assert fx == {} and "no ESPN game found on 2026-11-01" in notes[0]


def test_r8_supplied_opener_id_corroborated_on_eastern_date():
    board = {"games": [{"away": "High Point Panthers", "home": "Liberty Flames",
                        "espn_event_id": "401800001"}]}
    fx, notes = fixtures_from_espn(board, OPENER, "2026-11-02")
    assert notes == [] and len(fx) == 1
    fx, notes = fixtures_from_espn(board, OPENER, "2026-11-01")
    assert fx == {} and "ESPN_EVENT_DATE_MISMATCH" in notes[0]


def test_r8_opener_renders_its_ct_tip_time():
    from sportsedge.cbb_daily_card import SLATE_TZ
    assert str(SLATE_TZ) == "America/New_York"
    rows = card_rows(_P(_rec("TOTAL", -4.6, "UNDER", 155.5, a=-105, b=-115, model=150.9,
                             tip_utc="2026-11-02T05:00:00+00:00")), _fx())
    md = render_card_markdown(rows, "2026-11-02", {"records": [1]}, [], "v")
    assert "11:00 PM CT" in md


# ---- #3022: ET listing slate vs CT ratings date, per fixture ----

def test_r9_fixture_carries_et_listing_and_ct_ratings_dates():
    from sportsedge.cbb_daily_card import ratings_date
    board = {"games": [{"away": "High Point Panthers", "home": "Liberty Flames"}]}
    fx, _ = fixtures_from_espn(board, OPENER, "2026-11-02")
    f = fx["High Point Panthers@Liberty Flames"]
    assert (f["listing_date"], f["slate_date"]) == ("2026-11-02", "2026-11-01")
    assert ratings_date("2026-11-02T05:00Z") == "2026-11-01"        # 11:00 PM CT Nov 1
    assert ratings_date("2026-11-02T23:00:00+00:00") == "2026-11-02"  # 5:00 PM CT Nov 2


class _Vintage:
    def __init__(self, d):
        self.slate_date = d


class _Runner:
    def __init__(self):
        self.calls = []

    def price_slate(self, d, games, *, vintage, now):
        assert vintage.slate_date == d and all(g == d for g in games)
        self.calls.append(d)
        return {"records": [{"rd": d, "n": len(games)}], "refusals": [],
                "priced_at": f"{d}T12:00:00+00:00"}


def _mixed_fixtures():
    board = {"games": [{"away": "High Point Panthers", "home": "Liberty Flames"},
                       {"away": "Winthrop", "home": "Queens"}]}
    events = OPENER + [{**EVENTS[1], "date": "2026-11-02T23:00Z"}]   # Nov 2 5 PM CT, same ET slate
    fx, notes = fixtures_from_espn(board, events, "2026-11-02")
    assert notes == [] and len(fx) == 2
    return board, fx


def test_r9_mixed_ct_dates_in_one_et_slate_price_with_their_own_ratings():
    from sportsedge.cbb_daily_card import price_by_ratings_date
    board, fx = _mixed_fixtures()
    runner = _Runner()
    gfb = lambda b, group: [f["slate_date"] for f in group.values()]
    priced, notes = price_by_ratings_date(runner, board, fx, gfb,
                                          lambda d: (_Vintage(d), f"vintage {d}"), now=None)
    assert runner.calls == ["2026-11-01", "2026-11-02"]
    assert priced["ratings_dates"] == ["2026-11-01", "2026-11-02"]
    assert [r["rd"] for r in priced["records"]] == ["2026-11-01", "2026-11-02"]
    assert priced["priced_at"] == "2026-11-02T12:00:00+00:00"          # latest clock
    assert notes == ["Ratings 2026-11-01 (CT): vintage 2026-11-01",
                     "Ratings 2026-11-02 (CT): vintage 2026-11-02"]


def test_r9_missing_ratings_date_refuses_only_its_games_no_carry_forward():
    from sportsedge.cbb_daily_card import price_by_ratings_date
    board, fx = _mixed_fixtures()
    runner = _Runner()

    def vintage_for(d):
        if d == "2026-11-01":
            raise RuntimeError("SOURCE_FETCH_FAILED: HTTP 403 from https://barttorvik.com/2027_team_results.csv")
        return _Vintage(d), "ok"
    gfb = lambda b, group: [f["slate_date"] for f in group.values()]
    priced, notes = price_by_ratings_date(runner, board, fx, gfb, vintage_for, now=None)
    assert runner.calls == ["2026-11-02"]                              # Nov 1 never priced with Nov 2 ratings
    assert priced["refusals"] == [{"espn_event_id": "401800001", "market": None,
                                   "reason": "TORVIK_VINTAGE_UNAVAILABLE_FOR_RATINGS_DATE 2026-11-01"}]
    assert "HTTP 403" in notes[0] and len(priced["records"]) == 1
    md = render_card_markdown(card_rows(priced, fx), "2026-11-02", priced, [], " ".join(notes))
    assert "TORVIK_VINTAGE_UNAVAILABLE_FOR_RATINGS_DATE 2026-11-01" in md and "HTTP 403" in md
