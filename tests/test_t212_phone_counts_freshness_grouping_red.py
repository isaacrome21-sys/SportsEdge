"""RED (t212u #2355 + parent audit): family counts rebuilt after refusal;
missing freshness blocks whenever any quote field exists; NaN/inf/None age
with a recorded capture time refuses; impossible-total grouping includes push
and never merges different lines via abs(line)."""
import math

import pytest

from sportsedge.phone_display import build_phone_card
from sportsedge.research_estimate import build_research_estimate
from test_t197_quote_attestation_card import SCREENSHOT, _card, _game_row


def _sel(card):
    return build_phone_card(card)["selections"]


def _side(i, side, p, **extra):
    return _game_row("QUOTE_FRESHNESS_UNVERIFIED", input_index=i,
                     selection=f"{side} ML", estimate_p=p, fair_american=None, **extra)


def _two(rows):
    return {"evaluated_rows": rows, "summary": {"rows": len(rows)}, "min_ev": 0.02,
            "selection_intake": [dict(SCREENSHOT) for _ in rows]}


# --- B: counts rebuilt from finalized displayed selections ------------------
def test_refused_market_contributes_zero_priced_or_research_rows():
    view = build_phone_card(_two([_side(0, "Seattle Seahawks", 0.62), _side(1, "Denver Broncos", 0.55)]))
    assert all(s["status"] == "BLOCKED" for s in view["selections"])
    fams = view["coverage"]["families"]
    assert sum(f["priced"] for f in fams) == 0
    assert sum(f["research"] for f in fams) == 0
    assert sum(f["blocked"] for f in fams) == 2
    assert view["status_counts"] == {"BLOCKED": 2}


def test_counts_match_displayed_statuses_for_mixed_board():
    rows = [_side(0, "Seattle Seahawks", 0.62), _side(1, "Denver Broncos", 0.55),
            _side(2, "Kansas City Chiefs", 0.48, game="Kansas City Chiefs @ Buffalo Bills"),
            _side(3, "Buffalo Bills", 0.52, game="Kansas City Chiefs @ Buffalo Bills")]
    view = build_phone_card(_two(rows))
    fams = view["coverage"]["families"]
    shown_research = sum(s["status"] == "RESEARCH ONLY" for s in view["selections"])
    assert shown_research == 2
    assert sum(f["research"] for f in fams) == shown_research
    assert sum(f["blocked"] for f in fams) == 2
    assert sum(f["rows"] for f in fams) == 4


# --- missing freshness with any quote field ---------------------------------
@pytest.mark.parametrize("quote", [
    {"odds_american": None, "dk_odds": -110},
    {"price_american": -110},
    {"price": -110},
    {"american_odds": 120},
])
def test_missing_freshness_blocks_when_any_quote_field_exists(quote):
    est = build_research_estimate(0.61, engine="E", blocker="NO_QUOTE_BASIS")
    row = {"input_index": 0, "sport": "MLB", "market": "PLAYER_HITS",
           "selection": "OVER 0.5", "status": "NO_MODEL_OR_MARKET",
           "reason": "NO_QUOTE_BASIS", "research_estimate": est, **quote}
    sel = _sel(_card(row))[0]
    assert sel["status"] != "RESEARCH ONLY"
    assert sel["probability"] is None


def test_missing_freshness_without_any_quote_field_still_research():
    est = build_research_estimate(0.61, engine="E", blocker="NO_QUOTE_BASIS")
    row = {"input_index": 0, "sport": "MLB", "market": "PLAYER_HITS",
           "selection": "OVER 0.5", "status": "NO_MODEL_OR_MARKET",
           "reason": "NO_QUOTE_BASIS", "research_estimate": est}
    assert _sel(_card(row))[0]["status"] == "RESEARCH ONLY"


# --- non-finite / missing age with a recorded capture time ------------------
@pytest.mark.parametrize("age", [float("nan"), float("inf"), "nan"])
def test_nonfinite_age_refuses(age):
    row = _game_row("QUOTE_FRESHNESS_UNVERIFIED", age=age)
    sel = _sel(_card(row, SCREENSHOT))[0]
    assert sel["status"] != "RESEARCH ONLY"
    assert sel["probability"] is None


@pytest.mark.parametrize("age", [None, float("nan"), float("inf")])
def test_old_captured_at_without_valid_age_refuses(age):
    row = _game_row("QUOTE_FRESHNESS_UNVERIFIED", age=age)
    row["quote_freshness"]["captured_at"] = "2026-10-15T20:00:00+00:00"
    sel = _sel(_card(row, SCREENSHOT))[0]
    assert sel["status"] != "RESEARCH ONLY"
    assert sel["probability"] is None


def test_old_captured_at_on_row_or_intake_refuses():
    row = _game_row("QUOTE_FRESHNESS_UNVERIFIED", quote_captured_at="2026-10-15T20:00:00+00:00")
    assert _sel(_card(row, SCREENSHOT))[0]["probability"] is None
    row = _game_row("QUOTE_FRESHNESS_UNVERIFIED")
    intake = dict(SCREENSHOT, captured_at="2026-10-15T20:00:00+00:00")
    assert _sel(_card(row, intake))[0]["probability"] is None


# --- grouping: push mass, exact lines ----------------------------------------
def _total(i, side, p, line, push):
    est = build_research_estimate(p, engine="E", blocker="NO_QUOTE_BASIS")
    est["push_p"] = push
    return {"input_index": i, "sport": "NFL", "market": "TOTAL", "game": "A @ B",
            "selection": f"{side} {line}", "line": line, "status": "NO_MODEL_OR_MARKET",
            "reason": "NO_QUOTE_BASIS", "research_estimate": est}


def test_push_mass_counted_in_impossible_total():
    rows = [_total(0, "OVER", 0.48, 44.0, 0.06), _total(1, "UNDER", 0.48, 44.0, 0.06)]
    sels = _sel({"evaluated_rows": rows, "summary": {"rows": 2}, "min_ev": 0.02})
    for s in sels:
        assert s["probability"] is None
        assert "PROBABILITY_TOTAL_IMPOSSIBLE" in s["reason"]


def test_push_mass_possible_total_displays():
    rows = [_total(0, "OVER", 0.47, 44.0, 0.06), _total(1, "UNDER", 0.47, 44.0, 0.06)]
    sels = _sel({"evaluated_rows": rows, "summary": {"rows": 2}, "min_ev": 0.02})
    assert [s["probability"] for s in sels] == [0.47, 0.47]


def test_different_signed_lines_same_side_are_not_merged():
    # Over 3.5 and Over -3.5 (team total style / alt line) are different lines.
    rows = [_total(0, "OVER", 0.6, 3.5, 0.0), _total(1, "UNDER", 0.6, -3.5, 0.0)]
    sels = _sel({"evaluated_rows": rows, "summary": {"rows": 2}, "min_ev": 0.02})
    assert [s["probability"] for s in sels] == [0.6, 0.6]


def _spread(i, team, p, line, push=0.0):
    est = build_research_estimate(p, engine="E", blocker="NO_QUOTE_BASIS")
    est["push_p"] = push
    return {"input_index": i, "sport": "NFL", "market": "SPREAD", "game": "A @ B",
            "selection": team, "line": line, "status": "NO_MODEL_OR_MARKET",
            "reason": "NO_QUOTE_BASIS", "research_estimate": est}


def test_spread_opposite_sides_paired_by_signed_line():
    rows = [_spread(0, "A", 0.55, -3.0, 0.08), _spread(1, "B", 0.40, 3.0, 0.08)]
    sels = _sel({"evaluated_rows": rows, "summary": {"rows": 2}, "min_ev": 0.02})
    assert all(s["probability"] is None for s in sels)


def test_spread_same_sign_different_teams_not_merged():
    # A +3 and B +3 are different contracts; both can exceed 0.5.
    rows = [_spread(0, "A", 0.6, 3.0), _spread(1, "B", 0.6, 3.0)]
    sels = _sel({"evaluated_rows": rows, "summary": {"rows": 2}, "min_ev": 0.02})
    assert [s["probability"] for s in sels] == [0.6, 0.6]
