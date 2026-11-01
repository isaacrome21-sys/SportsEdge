import pytest

from sportsedge.capper_pipeline import (
    PickParseError, attach_close, match_event, parse_issue, render_table, settle,
)
from sportsedge.capper_vetter import grade_account, load_config

BODY = """### Account

@CorbieBO

### Other account handle

_No response_

### Posted at (Central)

2026-11-01 17:30

### Post link

https://x.com/CorbieBO/status/1

### Sport

NCAAB

### Game (Away @ Home)

High Point @ Liberty

### Market

Total

### Pick

Under

### Line

155.5

### Price when posted

-115

### Units (if the account gives them)

_No response_

### Does this account post its losses?

Yes
"""


def _team(side, name, short, abbr, score):
    return {"homeAway": side, "score": str(score),
            "team": {"displayName": name, "shortDisplayName": short, "location": short,
                     "abbreviation": abbr, "name": "x"}}


def _event(h=74, a=70, final=True, close_total=154.5):
    return {
        "id": "401", "date": "2026-11-02T04:59Z",
        "status": {"type": {"completed": final, "state": "post" if final else "pre"}},
        "competitions": [{
            "neutralSite": False,
            "competitors": [_team("home", "Liberty Flames", "Liberty", "LIB", h),
                            _team("away", "High Point Panthers", "High Point", "HPU", a)],
            "odds": [{"provider": {"name": "DraftKings"},
                      "total": {"over": {"close": {"line": f"o{close_total}", "odds": "-105"}},
                                "under": {"close": {"line": f"u{close_total}", "odds": "-115"}}},
                      "pointSpread": {"home": {"close": {"line": "+7.5", "odds": "-110"}},
                                      "away": {"close": {"line": "-7.5", "odds": "-110"}}},
                      "moneyline": {"home": {"close": {"odds": "+260"}},
                                    "away": {"close": {"odds": "-325"}}}}],
        }],
    }


def test_parse_issue_form():
    p = parse_issue(7, "[CAPPER] x", BODY, "2026-11-01T23:40:00Z")
    assert p["account"] == "@CorbieBO" and p["sport"] == "NCAAB"
    assert (p["away"], p["home"], p["market"], p["line"], p["price"]) == ("High Point", "Liberty", "Total", 155.5, -115)
    assert p["shows_losses"] is True and p["units"] == 1.0
    assert p["posted_at"].startswith("2026-11-01T17:30:00-06:00")


def test_parse_rejects_bad_price_and_future_post():
    with pytest.raises(PickParseError):
        parse_issue(1, "t", BODY.replace("-115", "-50"))
    with pytest.raises(PickParseError):
        parse_issue(1, "t", BODY, "2026-11-01T20:00:00Z")  # filed before the stated post time


def test_comment_overrides():
    p = parse_issue(7, "t", BODY, comments=["close: -125 / +105 line 155.5", "result: loss"])
    assert (p["close_price"], p["close_other_price"], p["result"]) == (-125, 105, "loss")


def test_match_close_settle_total_same_number():
    p = parse_issue(7, "t", BODY)
    ev = match_event(p, [_event(close_total=155.5)])
    assert ev["id"] == "401"
    attach_close(p, ev)
    assert (p["close_price"], p["close_other_price"]) == (-115, -105)
    settle(p, ev)
    assert p["result"] == "win"  # 144 < 155.5


def test_line_move_drops_price_clv():
    p = parse_issue(7, "t", BODY)
    ev = _event(close_total=152.5)
    attach_close(p, ev)
    assert "close_price" not in p and p["close_line_moved"] == -3.0


def test_spread_and_moneyline_settle():
    body = BODY.replace("Total", "Spread").replace("Under", "Liberty").replace("155.5", "+7.5")
    p = parse_issue(8, "t", body)
    ev = _event(h=60, a=66)
    attach_close(p, ev)
    assert p["close_price"] == -110
    settle(p, ev)
    assert p["result"] == "win"  # lost by 6 with +7.5
    ml = parse_issue(9, "t", BODY.replace("Total", "Moneyline").replace("Under", "High Point").replace("155.5", ""))
    settle(ml, ev)
    assert ml["result"] == "win"


def test_not_final_stays_pending_and_grades():
    p = parse_issue(7, "t", BODY)
    ev = _event(final=False)
    settle(p, ev)
    assert p["result"] == "pending"
    p["tip_utc"] = "2026-11-02T04:59:00+00:00"
    r = grade_account([p], load_config())
    assert r["picks_graded"] == 0 and r["picks_logged"] == 1


def test_render_table():
    md = render_table([{"account": "@a", "score": 61.2, "grade": "C", "picks_graded": 3,
                        "clv_pct": 1.234, "adj_roi": -0.03, "flags": []}], 4, ["#9: bad"], "now")
    assert "| 1 | @a | 61 | C | 3 | +1.23 | -3.0% | — |" in md and "#9: bad" in md
