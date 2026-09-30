from sportsedge.mlb_card_blocked import blocked_notes


def test_all_blocked_is_visible() -> None:
    notes = blocked_notes({
        "blocked": [{"game_id": "Phillies@Braves", "reason": "MANUAL_QUOTE_NOT_PREGAME"}],
        "results": [],
        "games": [],
    })
    assert notes[0].startswith("BLOCKED Phillies@Braves")
    assert notes[-1].startswith("ALL_BLOCKED")
