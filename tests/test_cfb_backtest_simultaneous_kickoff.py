"""Regression: simultaneous CFB kickoffs must not ingest each other's results."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backtest_cfb_matchup_blend.py"
spec = importlib.util.spec_from_file_location("cfb_matchup_backtest_simultaneous", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_same_kickoff_does_not_use_other_games_final_score():
    # Build three prior games per team so both teams have a valid pregame projection.
    games = []
    for i in range(3):
        for team in ("A", "B"):
            games.append(dict(season=2026, start=f"2026-09-{i+1:02d}T12:00:00Z",
                              id=f"{team}-{i}", home=team, away=f"{team}opp{i}",
                              hs=28, **{'as': 21}, spread=0.0, total=49.0))
    # Two same-time records intentionally share A. This is an adversarial
    # fixture, not a claim that a real team can play twice at one kickoff.
    first = dict(season=2026, start="2026-09-10T12:00:00Z", id="1",
                 home="A", away="B", hs=10, **{'as': 10}, spread=0.0, total=49.0)
    second = dict(season=2026, start="2026-09-10T12:00:00Z", id="2",
                  home="A", away="B", hs=30, **{'as': 30}, spread=0.0, total=49.0)
    rows = module.project(sorted(games + [first, second], key=lambda g: (g["season"], g["start"], g["id"])))
    same_time = [r for r in rows if r["id"] in ("1", "2")]
    assert len(same_time) == 2
    assert same_time[0]["model_margin"] == same_time[1]["model_margin"]
    assert same_time[0]["model_total"] == same_time[1]["model_total"]
