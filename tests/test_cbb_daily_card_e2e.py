"""End-to-end NON_COUNTED path on the real pinned runner: [CBB LINES] body
-> intake -> ESPN-style fixtures -> morning vintage -> price_slate -> card.
Synthetic vintage (365 rows) and scoreboard; no network."""
import hashlib
import json
from datetime import datetime, timezone

from sportsedge.cbb_daily_card import card_rows, fixtures_from_espn, render_card_markdown
from sportsedge.cbb_efficiency_forward import (
    CbbEfficiencyForwardRunner, games_from_board, load_vintage,
)
from sportsedge.cbb_lines_intake import parse_cbb_lines

DATE = "2026-11-02"
BODY = """High Point Panthers @ Liberty Flames
Captured: 2026-11-02T12:00:00-06:00
Spread -7.5 -108 -112
Total 155.5 -105 -115
"""
EVENTS = [{"id": "401999", "date": "2026-11-03T03:59Z", "competitions": [{
    "neutralSite": False, "competitors": [
        {"homeAway": "home", "team": {"id": "2335", "displayName": "Liberty Flames",
                                      "shortDisplayName": "Liberty", "location": "Liberty", "abbreviation": "LIB"}},
        {"homeAway": "away", "team": {"id": "2272", "displayName": "High Point Panthers",
                                      "shortDisplayName": "High Point", "location": "High Point", "abbreviation": "HPU"}}]}]}]


def _vintage(tmp_path):
    rows = ["team,adjoe,adjde,adjt,barthag"]
    rows += [f"Filler {i},106.0,106.0,68.0,0.5" for i in range(361)]
    rows += ["High Point,114.5,101.6,72.0,0.8", "Liberty,106.4,105.0,62.0,0.55"]
    raw = ("\n".join(rows) + "\n").encode()
    (tmp_path / f"{DATE}.csv").write_bytes(raw)
    (tmp_path / f"{DATE}.json").write_text(json.dumps({
        "sha256": hashlib.sha256(raw).hexdigest(), "evidence_state": "verified-by-pull",
        "as_of_local_date": DATE, "bytes": len(raw), "team_rows": 363}))
    return load_vintage(DATE, tmp_path)


def test_end_to_end_card(tmp_path):
    board = parse_cbb_lines(BODY, title="[CBB LINES] HPU @ LIB").to_board_dict()
    fixtures, notes = fixtures_from_espn(board, EVENTS, DATE)
    assert notes == [] and list(fixtures) == ["High Point Panthers@Liberty Flames"]
    priced = CbbEfficiencyForwardRunner().price_slate(
        DATE, games_from_board(board, fixtures), vintage=_vintage(tmp_path),
        now=datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc))
    assert priced["counted"] is False and priced["refusals"] == []
    recs = {r["market"]: r for r in priced["records"]}
    assert set(recs) == {"SPREAD", "TOTAL"}
    rows = card_rows(priced, fixtures)
    for r in rows:
        assert r["market"] in recs and r["bucket"] != "REFUSED"
        rec = recs[r["market"]]
        assert rec["classification"] == "PICKED"
    md = render_card_markdown(rows, DATE, priced, notes, "Ratings: test vintage.")
    assert "CBB card" in md and "Liberty margin: model" in md and "vs market -7.5" in md
    assert all(r["counted"] is False and r["label"] == "NON_COUNTED" for r in rows)
    print(md)
