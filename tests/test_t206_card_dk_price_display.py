"""t206: prop/blocked rows show the user-supplied DK price, never an invented one."""
import json
import subprocess
import sys
from pathlib import Path

from sportsedge.phone_display import build_phone_card, render_phone_card


def blocked(i, **kw):
    row = {"status": "NO_MODEL_OR_MARKET", "reason": "NO_ENGINE: X", "sport": "NFL",
           "market": "ANYTIME_TD", "selection": "YES", "player_name": "Jaxon Smith-Njigba",
           "input_index": i, "game": "A @ B"}
    row.update(kw)
    return row


def line(**kw):
    src = {"sport": "NFL", "away": "A", "home": "B", "market": "PLAYER_ANYTIME_TD",
           "side": "OVER", "odds": 100, "line": 0.5, "player_name": "Jaxon Smith-Njigba",
           "quote_source": "OWNER_DK_SCREENSHOT"}
    src.update(kw)
    return src


def card(*rows):
    return {"evaluated_rows": list(rows), "summary": {"rows": len(rows)},
            "min_ev": .02, "as_of_utc": "2026-10-15T22:39:11Z"}


def test_blocked_prop_row_shows_input_dk_price():
    view = build_phone_card(card(blocked(0)), input_lines=[line(odds=547)])
    sel = view["selections"][0]
    assert sel["odds"] == 547 and sel["odds_source"] == "USER_INPUT_LINE"
    assert sel["status"] == "BLOCKED"           # display only; disposition unchanged
    assert "| +547 | BLOCKED |" in render_phone_card(card(blocked(0)), input_lines=[line(odds=547)])


def test_missing_price_is_said_plainly_never_invented():
    text = render_phone_card(card(blocked(0)), input_lines=[line(odds=None)])
    assert "| no DK price in input | BLOCKED |" in text
    assert build_phone_card(card(blocked(0)), input_lines=[line(odds=None)])["selections"][0]["odds"] is None
    assert "| no DK price in input |" in render_phone_card(card(blocked(0)))


def test_unbound_input_line_is_not_used():
    # different player at that index -> never borrow its price
    view = build_phone_card(card(blocked(0)), input_lines=[line(player_name="Someone Else", odds=300)])
    assert view["selections"][0]["odds"] is None
    view = build_phone_card(card(blocked(0)), input_lines=[line(sport="MLB", odds=300)])
    assert view["selections"][0]["odds"] is None
    # count mismatch -> no binding at all
    view = build_phone_card(card(blocked(0)), input_lines=[line(), line()])
    assert view["selections"][0]["odds"] is None


def test_row_and_input_price_conflict_fails_closed():
    view = build_phone_card(card(blocked(0, odds_american=-120)), input_lines=[line(odds=100)])
    sel = view["selections"][0]
    assert sel["odds"] is None and sel["odds_source"] == "PRICE_CONFLICT"
    assert "| DK price conflict |" in render_phone_card(card(blocked(0, odds_american=-120)),
                                                        input_lines=[line(odds=100)])


def test_engine_row_price_still_used_and_agrees():
    view = build_phone_card(card(blocked(0, odds_american=100)), input_lines=[line(odds=100)])
    assert view["selections"][0]["odds"] == 100


def test_t197_card_renders_every_input_price(tmp_path):
    root = Path("/workspace/t197_in")
    if not (root / "after/card.json").exists():
        import pytest; pytest.skip("t197 fixture not on this machine")
    c = json.loads((root / "after/card.json").read_text())
    lines = json.loads((root / "after/lines.json").read_text())["lines"]
    view = build_phone_card(c, input_lines=lines)
    missing = [s for s, l in zip(view["selections"], lines) if s["odds"] is None and l.get("odds") is not None]
    assert missing == []
    assert all(s["odds"] == l["odds"] for s, l in zip(view["selections"], lines))


def test_team_qualified_input_name_binds_to_resolved_row_name():
    view = build_phone_card(card(blocked(0, sport="MLB", player_name="Will Smith")),
                            input_lines=[line(sport="MLB", player_name="Will Smith (LAD)", odds=547)])
    assert view["selections"][0]["odds"] == 547
