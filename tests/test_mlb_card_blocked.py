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


def test_render_includes_priced_rows_and_blocked_line() -> None:
    payload = {
        "blocked": [{"game_id": "White Sox@Astros", "reason": "GAME_NOT_PREGAME"}],
        "results": [{"ok": True}],
        "games": [{"resolved_game": {"away_team": "Phillies", "home_team": "Braves"}}],
    }
    priced = [{
        "market": "MONEYLINE",
        "selection": "Phillies",
        "model_p": 0.52,
        "price": -117,
        "status": "PASS",
    }]
    text = render_markdown(priced, header="SportsEdge MLB card", notes=blocked_notes(payload))
    assert "Phillies" in text
    assert "BLOCKED White Sox@Astros: GAME_NOT_PREGAME" in text
