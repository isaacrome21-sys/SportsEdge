import pytest
from scripts.run_nba_lines_issue import evidence_rows
from sportsedge.sports.nba.lines_card import parse_lines, price_game

class Ratings:
    def margin_total(self, home, away):
        return 40.0, 240.0

def test_blocked_card_cannot_export_hidden_model_picks(monkeypatch):
    from scripts import run_nba_lines_issue as runner
    games = parse_lines("Captured: 2026-10-24T18:00:00-05:00\nCeltics @ Knicks\nML +130 -155\nSpread +3.5 -110 -110\nTotal 224.5 -110 -110")
    # This ratings stub produced positive hidden picks before the fix.
    assert any(r.ev >= 0.02 for r in price_game(games[0], Ratings())[2])
    def forbidden(*args, **kwargs):
        pytest.fail("Registry-blocked export must not invoke the pricer")
    monkeypatch.setattr(runner, "price_game", forbidden)
    captures, picks = evidence_rows(games, Ratings(), game_date="2026-10-24", issue=123, engine_id="v1")
    assert len(captures) == 6
    assert all(c["captured_at"] == "2026-10-24T18:00:00-05:00" for c in captures)
    assert picks == []
    assert all("model_p" not in c and "ev_per_unit" not in c for c in captures)


def test_ungated_export_matches_card_and_retains_paper_state(monkeypatch):
    # Hypothetical unblocked path only; this does not change the real registry.
    monkeypatch.setattr("scripts.run_nba_lines_issue.family_gate_row", lambda *a: None)
    games = parse_lines("Captured: 2026-10-24T18:00:00-05:00\nCeltics @ Knicks\nML +130 -155\nSpread +3.5 -110 -110\nTotal 224.5 -110 -110")
    captures, picks = evidence_rows(games, Ratings(), game_date="2026-10-24", issue=123, engine_id="test-version")
    assert len(captures) == 6
    _, _, rows = price_game(games[0], Ratings())
    expected = {r.side: r for r in rows if r.ev >= 0.02}
    assert {p["pick"] for p in picks} == set(expected)
    for pick in picks:
        assert pick["model_p"] == expected[pick["pick"]].model_p
        assert pick["price"] == expected[pick["pick"]].price
        assert pick["status"] == "EXPERIMENTAL"
        assert pick["countable"] is False
        assert pick["engine_id"] == "test-version"

def test_missing_capture_refuses_evidence():
    games = parse_lines("Celtics @ Knicks\nML +130 -155")
    with pytest.raises(ValueError, match="CAPTURED_AT_MISSING"):
        evidence_rows(games, Ratings(), game_date="2026-10-24", issue=1, engine_id="v1")
