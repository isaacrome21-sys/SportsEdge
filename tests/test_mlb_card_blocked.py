from sportsedge.mlb_card_blocked import blocked_notes
from sportsedge.mlb_myspari_own_model import render_markdown


def test_all_blocked_is_visible() -> None:
    notes = blocked_notes({
        "blocked": [{"game_id": "Phillies@Braves", "reason": "MANUAL_QUOTE_NOT_PREGAME"}],
        "results": [],
        "games": [],
    })
    assert notes[0].startswith("BLOCKED Phillies@Braves")
    assert notes[-1].startswith("ALL_BLOCKED")


def test_empty_rendered_card_includes_all_blocked() -> None:
    payload = {
        "blocked": [{"game_id": "Phillies@Braves", "reason": "AMBIGUOUS_GAME"}],
        "results": [],
        "games": [],
    }
    text = render_markdown([], header="SportsEdge MLB card", notes=blocked_notes(payload))
    assert "| Game |" in text or "Game" in text
    assert "BLOCKED Phillies@Braves: AMBIGUOUS_GAME" in text
    assert "ALL_BLOCKED: no priced rows. This is not a pass." in text


def test_render_includes_priced_rows_and_blocked_line() -> None:
    payload = {
        "blocked": [{"game_id": "White Sox@Astros", "reason": "GAME_NOT_PREGAME"}],
        "results": [{"ok": True}],
        "games": [{"resolved_game": {"away_team": "Phillies", "home_team": "Braves"}}],
    }
    priced = [{"game_id": "Phillies@Braves", "market": "MONEYLINE", "side": "AWAY"}]
    text = render_markdown(priced, header="SportsEdge MLB card", notes=blocked_notes(payload))
    assert "Phillies@Braves" in text
    assert "BLOCKED White Sox@Astros: GAME_NOT_PREGAME" in text
    assert "ALL_BLOCKED" not in text
