"""Lane 4 (#2447 work order 6390303271): every MLB World Series market prices
or fails closed with an explicit reason, and the card ranks by EV/$.

The fixture body is the issue template's own example board (synthetic test
input, not captured prices). No network: the canonical engine run is not
exercised here; the card renderer is fed synthetic engine rows.
"""
from __future__ import annotations

import re

from sportsedge.mlb_lines_intake import parse_lines
from sportsedge.mlb_myspari_own_model import render_markdown

TEMPLATE_BODY = """Red Sox @ Yankees
ML +116 -140
RL +1.5 -193 +159
Total 6 -116 -104
YRFI +130 -165
Yankees TT 3.5 +114 -145
F5 ML +100 -130
F5 RL +0.5 -145 +114
F5 Total 3.5 -110 -120
Yankees F5 TT 1.5 -154 +120
Cam Schlittler K 6.5 -149 +117
Cam Schlittler outs 17.5 -174 +130
Cam Schlittler win +159 -223
Payton Tolle hits+walks+er 7.5 +103 -137
Aaron Judge hits 1.5 +120 -150
Aaron Judge TB 1.5 +105 -135
Aaron Judge HR 0.5 +150 -200
Aaron Judge walks 0.5 -110 -120
Aaron Judge batter K 1.5 +125 -155
Aaron Judge first HR +550 -900
"""

WORK_ORDER_MARKETS = {
    "MONEYLINE", "RUN_LINE", "GAME_TOTAL",
    "FIRST_FIVE_MONEYLINE", "FIRST_FIVE_RUN_LINE", "FIRST_FIVE_TOTAL",
    "TEAM_TOTAL", "FIRST_FIVE_TEAM_TOTAL", "FIRST_INNING_TOTAL",
    "PITCHER_STRIKEOUTS", "PITCHER_OUTS", "PITCHER_RECORD_WIN", "PITCHER_HITS_WALKS_ER",
    "BATTER_HITS", "BATTER_TOTAL_BASES", "BATTER_HOME_RUNS", "BATTER_WALKS", "BATTER_STRIKEOUTS",
}


def test_template_board_parses_every_work_order_market_with_both_prices():
    rows = parse_lines(TEMPLATE_BODY)
    assert WORK_ORDER_MARKETS <= {r.market_type for r in rows}
    for r in rows:
        assert r.price and r.paired_price, r


def _row(market, side, ev, status="PASS", **extra):
    base = {"game_id": "1", "market": market, "side": side, "line": 0.5, "american_odds": -110,
            "model_p": 0.5 if ev is not None else None, "model_p_raw": 0.5 if ev is not None else None,
            "edge": ev, "ev_per_dollar": ev, "fair_odds": -100 if ev is not None else None,
            "scored_status": status}
    base.update(extra)
    return base


def _board_evs(md: str) -> list[float]:
    section = md.split("## Full board", 1)[1].split("\n\n_Win p", 1)[0]
    evs = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 11 and re.fullmatch(r"\d+", cells[0]) and cells[9] != "—":
            evs.append(float(cells[9]))
    return evs


def test_full_board_ranks_by_ev_highest_first_regardless_of_status():
    rows = [
        _row("YRFI", "YES", 0.05, "ACTIONABLE"),
        _row("HITS", "UNDER", 0.02, "LEAN"),
        _row("TOTALS", "OVER", 0.28, "PASS"),
        _row("TEAM_TOTALS", "OVER", 0.22, "PASS"),
        _row("MONEYLINE", "AWAY", -0.05, "PASS"),
        _row("PITCHER_K", "OVER", None, "BLOCKED", engine_reason="SUBJECT_UNRESOLVED:X"),
    ]
    md = render_markdown(rows, header="t")
    evs = _board_evs(md)
    assert evs == sorted(evs, reverse=True) and len(evs) == 5
    # Unpriced rows stay on the board (last) and carry an explicit reason.
    assert "SUBJECT_UNRESOLVED:X" in md
    assert md.split("## Full board", 1)[1].index("Pitcher K") > md.split("## Full board", 1)[1].index("Moneyline")


def test_no_silent_drop_every_row_appears_on_board():
    rows = [_row(m, "OVER", None if i % 3 == 0 else 0.01 * i, "BLOCKED" if i % 3 == 0 else "PASS",
                 engine_reason=f"REASON_{i}" if i % 3 == 0 else None)
            for i, m in enumerate(["MONEYLINE", "RUN_LINE", "TOTALS", "YRFI", "PITCHER_K", "HITS"])]
    md = render_markdown(rows, header="t")
    board = md.split("## Full board", 1)[1]
    numbered = [l for l in board.splitlines() if re.match(r"\| \d+ \|", l)]
    assert len(numbered) == len(rows)
    for i in (0, 3):
        assert f"REASON_{i}" in md


def test_card_has_no_score_or_official_wording():
    md = render_markdown([_row("YRFI", "YES", 0.05, "ACTIONABLE")], header="t")
    low = md.lower().replace("not official", "")
    assert "official" not in low
    header_cells = [c.strip().lower() for l in md.splitlines() if l.startswith("| ") for c in l.split("|")]
    assert "score" not in header_cells
