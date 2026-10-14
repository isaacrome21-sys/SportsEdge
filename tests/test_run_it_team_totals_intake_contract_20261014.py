"""MLB TEAM_TOTALS intake contract tests (2026-10-14).

The game engine requires an exact ``team`` and refuses to guess one
(TEAM_TOTALS_TEAM_REQUIRED) -- that strictness is correct and unchanged.
Board-shaped intake rows identify the team by ``team_side`` (HOME/AWAY)
instead. Before this contract, such a row died deep in the engine as
BLOCKED_INVALID / TEAM_TOTALS_TEAM_REQUIRED, and a ``team`` that
contradicted ``team_side`` was silently priced as the wrong team at the
other side's line.

Pinned here, through the canonical entry point (run_full):
(a) team_side-only rows are mapped to the corresponding home/away team
    at intake and evaluate exactly like the identical with-team rows;
(b) a team identity that contradicts team_side (the other side, or a
    third team) is refused at intake by name
    (TEAM_TOTALS_TEAM_SIDE_CONFLICT) -- never silently overridden;
(c) a row with no team identity and no resolvable team_side is refused
    at intake by name (TEAM_TOTALS_TEAM_REQUIRED), not BLOCKED_INVALID;
(d) engine-owned paths are untouched: selection-embedded team names
    still price, and a team field conflicting with the selection keeps
    the engine's TEAM_TOTALS_CONFLICTING_TEAM_IDENTITY refusal.
"""
from datetime import datetime, timedelta, timezone

from artifacts.run_it_full import run_full

CT = timezone(timedelta(hours=-5))
CAPTURE = datetime(2026, 10, 14, 14, 0, 0, tzinfo=CT)
BASE = {
    "sport": "MLB",
    "away": "Milwaukee Brewers",
    "home": "Los Angeles Dodgers",
    "kickoff": "2026-10-14T19:00:00-05:00",
    "book": "draftkings",
    "quote_captured_at": CAPTURE.isoformat(),
    "market": "TEAM_TOTALS",
}
BOARD = [
    dict(BASE, team_side="HOME", side="OVER", line=4.5, odds=114),
    dict(BASE, team_side="HOME", side="UNDER", line=4.5, odds=-145),
    dict(BASE, team_side="AWAY", side="OVER", line=3.5, odds=114),
    dict(BASE, team_side="AWAY", side="UNDER", line=3.5, odds=-145),
]


def _card(rows):
    return run_full({"lines": [dict(r) for r in rows]},
                    now=CAPTURE, auto_context=False)


def test_team_side_only_rows_price_like_with_team_rows():
    side_only = _card(BOARD)["evaluated_rows"]
    with_team = _card([
        dict(r, team=r["home"] if r["team_side"] == "HOME" else r["away"])
        for r in BOARD
    ])["evaluated_rows"]
    assert [r["status"] for r in side_only] == [r["status"] for r in with_team]
    assert [r["selection"] for r in side_only] == \
        [r["selection"] for r in with_team]
    assert [r["ev_per_dollar"] for r in side_only] == \
        [r["ev_per_dollar"] for r in with_team]
    # The mapped identities are the correct teams, by name.
    assert side_only[0]["selection"] == "Los Angeles Dodgers OVER 4.5"
    assert side_only[2]["selection"] == "Milwaukee Brewers OVER 3.5"
    assert all(r["status"] != "BLOCKED_INVALID" for r in side_only)


def test_contradictory_team_and_team_side_refused_at_intake_by_name():
    rows = [dict(r, team=r["away"] if r["team_side"] == "HOME" else r["home"])
            for r in BOARD]
    evaluated = _card(rows)["evaluated_rows"]
    assert len(evaluated) == 4
    for r in evaluated:
        assert r["status"] == "NO_MODEL_OR_MARKET"
        assert r["blocker"] == "TEAM_TOTALS_TEAM_SIDE_CONFLICT"
        assert r["intake_enforced"] is True
        # Refused rows never carry a price.
        assert "ev_per_dollar" not in r


def test_third_team_with_team_side_refused_at_intake_by_name():
    row = dict(BASE, side="OVER", line=4.5, odds=114,
               team="Chicago Cubs", team_side="HOME")
    r = _card([row])["evaluated_rows"][0]
    assert r["status"] == "NO_MODEL_OR_MARKET"
    assert r["blocker"] == "TEAM_TOTALS_TEAM_SIDE_CONFLICT"
    assert r["intake_enforced"] is True


def test_neither_team_nor_team_side_refused_at_intake_by_name():
    rows = [dict(r) for r in BOARD]
    for r in rows:
        r.pop("team_side")
    evaluated = _card(rows)["evaluated_rows"]
    assert len(evaluated) == 4
    for r in evaluated:
        assert r["status"] == "NO_MODEL_OR_MARKET"
        assert r["status"] != "BLOCKED_INVALID"
        assert r["blocker"] == "TEAM_TOTALS_TEAM_REQUIRED"
        assert "team is missing at intake" in r["blocker_detail"]
        assert r["intake_enforced"] is True


def test_selection_embedded_team_still_prices_unchanged():
    row = dict(BASE, side="Milwaukee Brewers OVER", line=3.5, odds=114)
    r = _card([row])["evaluated_rows"][0]
    assert r["selection"] == "Milwaukee Brewers OVER 3.5"
    assert r["status"] != "BLOCKED_INVALID"
    # Agreement between the embedded team and team_side also prices.
    row2 = dict(BASE, side="Milwaukee Brewers OVER", team_side="AWAY",
                line=3.5, odds=114)
    r2 = _card([row2])["evaluated_rows"][0]
    assert r2["selection"] == "Milwaukee Brewers OVER 3.5"
    assert r2["status"] == r["status"]


def test_team_field_conflicting_with_selection_stays_engine_owned():
    row = dict(BASE, side="Milwaukee Brewers OVER",
               team="Los Angeles Dodgers", line=3.5, odds=114)
    r = _card([row])["evaluated_rows"][0]
    assert r["status"] == "BLOCKED_INVALID"
    assert r["reason"] == "TEAM_TOTALS_CONFLICTING_TEAM_IDENTITY"
