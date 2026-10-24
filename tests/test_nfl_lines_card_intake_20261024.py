"""[NFL LINES] card: capture time from the paste, kickoff from an independent schedule.

Fail closed: no capture line, stale capture, or no unique schedule match refuses
research pricing with a specific reason. The issue edit time is never a capture time.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from sportsedge.nfl_lines_intake import NflLinesIntakeError, parse_nfl_lines, tickets_to_dict

ROOT = Path(__file__).resolve().parents[1]
AS_OF = datetime(2026, 9, 20, 16, 0, 0, tzinfo=timezone.utc)
SCHEDULE = [
    {"id": "1", "commence_time": "2026-09-20T20:25:00Z", "away_team": "Kansas City Chiefs",
     "home_team": "Baltimore Ravens"},
    {"id": "2", "commence_time": "2026-09-20T17:00:00Z", "away_team": "Cincinnati Bengals",
     "home_team": "Las Vegas Raiders"},
    {"id": "3", "commence_time": "2026-09-20T17:00:00Z", "away_team": "Buffalo Bills",
     "home_team": "New York Jets"},
]


def _history() -> list[dict]:
    games = []
    for i in range(8):
        day = f"2026-09-{i + 1:02d}"
        games.append({"date": day, "id": f"a{i}", "home": "KC", "away": "LV", "hs": 27, "as": 20})
        games.append({"date": day, "id": f"b{i}", "home": "BAL", "away": "CIN", "hs": 24, "as": 21})
    return games


def _body(captured: str | None, *, second_game: bool = False) -> str:
    rows = ["Chiefs @ Ravens"]
    if captured:
        rows.append(f"Captured {captured}")
    rows += ["Spread +3.5 -110 -110", "Total 60.5 -120 +100", "ML +150 -175"]
    if second_game:
        rows += ["Bengals @ Raiders"]
        if captured:
            rows.append(f"Captured {captured}")
        rows += ["Spread -2.5 -110 -110", "Total 30.5 +100 -120"]
        rows += ["Bills @ Jets"]  # no prior history in the fixture -> unpriced
        if captured:
            rows.append(f"Captured {captured}")
        rows += ["Spread -6.5 -110 -110", "Total 41.5 -110 -110"]
    return "\n".join(rows)


def _ticket(body: str) -> dict:
    # observed_at stands in for the issue edit time; deliberately "fresh".
    ticket = tickets_to_dict(parse_nfl_lines(body), observed_at=AS_OF.isoformat())
    ticket["slate"] = "2026-09-20"
    return ticket


def _run(ticket: dict, schedule: list | None = SCHEDULE) -> tuple[dict, str]:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "ticket.json").write_text(json.dumps(ticket), encoding="utf-8")
        (t / "hist.json").write_text(json.dumps(_history()), encoding="utf-8")
        (t / "sched.json").write_text(json.dumps(schedule), encoding="utf-8")
        env = {"PYTHONPATH": str(ROOT)}
        subprocess.run([sys.executable, "scripts/run_nfl_lines_card.py", "--input", str(t / "ticket.json"),
                        "--history", str(t / "hist.json"), "--output", str(t / "card.json"),
                        "--as-of", AS_OF.isoformat(), "--schedule", str(t / "sched.json")],
                       cwd=ROOT, env=env, check=True)
        subprocess.run([sys.executable, "scripts/render_nfl_myspari_card.py", "--engine-output", str(t / "card.json"),
                        "--snapshot", str(t / "ticket.json"), "--out-dir", str(t / "out")],
                       cwd=ROOT, env=env, check=True)
        return json.loads((t / "card.json").read_text()), (t / "out" / "card.md").read_text()


def _iso(seconds_before: int) -> str:
    return (AS_OF - timedelta(seconds=seconds_before)).isoformat()


def test_fresh_capture_and_unique_schedule_match_prices_paired_rows():
    engine, md = _run(_ticket(_body(_iso(30))))
    game = engine["games"][0]
    assert game["residual_research_error"] is None
    assert game["commence_time"] == "2026-09-20T20:25:00+00:00"
    spread = [m for m in game["markets"] if m["market"] == "spread"][0]
    assert len(spread["residual_research_prices"]) == 2
    assert all(p["eligible_as_bet"] is False for p in game["residual_research_prices"])
    assert "Ranked by research EV per $" in md
    assert "OFFICIAL" not in md
    assert "Residual adjustments are research-only: not validated, no picks, no staking." in md
    assert "**BET**" not in md and "LEAN (" not in md


def test_missing_capture_line_refuses_with_quote_timestamp_even_if_issue_time_fresh():
    ticket = _ticket(_body(None))
    assert all("quote_retrieved_at" not in m for g in ticket["games"] for m in g["markets"])
    engine, md = _run(ticket)
    assert engine["games"][0]["residual_research_error"].startswith("QUOTE_TIMESTAMP")
    assert "capture-time line missing" in md


def test_capture_older_than_180_seconds_is_stale():
    engine, md = _run(_ticket(_body(_iso(200))))
    assert engine["games"][0]["residual_research_error"] == "QUOTE_STALE"
    assert "older than 180 seconds" in md


@pytest.mark.parametrize("schedule,code", [
    ([SCHEDULE[1]], "SCHEDULE_KICKOFF:NO_MATCH"),
    ([SCHEDULE[0], {**SCHEDULE[0], "id": "9"}], "SCHEDULE_KICKOFF:AMBIGUOUS"),
    ([{**SCHEDULE[0], "commence_time": "Sunday"}], "SCHEDULE_KICKOFF:INVALID"),
])
def test_schedule_without_exactly_one_match_fails_closed(schedule, code):
    ticket = _ticket(_body(_iso(30)))
    ticket["games"][0]["commence_time"] = "2026-09-20T20:25:00Z"  # pasted kickoff is not trusted
    engine, md = _run(ticket, schedule)
    assert engine["games"][0]["residual_research_error"] == code
    assert all(m.get("no_model") for m in engine["games"][0]["markets"])
    assert "Ranked by research EV" in md and "Not priced:" in md


def test_capture_line_requires_timezone_and_iso_instant():
    for bad in ("2026-09-20T11:00:00", "11:00 AM CT", "2026-09-20"):
        with pytest.raises(NflLinesIntakeError, match="NFL_INTAKE_CAPTURED_AT"):
            parse_nfl_lines(_body(bad))
    with pytest.raises(NflLinesIntakeError, match="DUPLICATE"):
        parse_nfl_lines("Chiefs @ Ravens\nCaptured 2026-09-20T15:59:30Z\nCaptured 2026-09-20T15:59:31Z\nSpread +3.5 -110 -110")


def test_priced_rows_ranked_by_ev_across_games_unpriced_last():
    ticket = _ticket(_body(_iso(30), second_game=True))
    engine, md = _run(ticket)
    block = md.split("Ranked by research EV per $", 1)[1].split("### ", 1)[0]
    priced, _, unpriced = block.partition("Not priced:")
    evs = [float(line.split("research EV ", 1)[1].split("%", 1)[0])
           for line in priced.splitlines() if "research EV" in line]
    assert len(evs) >= 3
    assert evs == sorted(evs, reverse=True)
    assert "Spread BUF" in unpriced and "not enough prior games" in unpriced
    assert all("**WATCH**" in line for line in priced.splitlines() if "research EV" in line)
