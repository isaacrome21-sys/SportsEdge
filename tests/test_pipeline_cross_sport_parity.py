"""Same Muse-format body through every sport's existing entrypoint parser."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.intake_cfb_lines_issue import board_from_body
from sportsedge.mlb_lines_intake import parse_lines_with_warnings
from sportsedge.mlb_resolve import build_bound_input
from sportsedge.mlb_source import GameSnapshot
from sportsedge.nfl_lines_intake import NflLinesIntakeError, parse_nfl_lines
from sportsedge.nhl_lines_intake import NhlLinesIntakeError, parse_nhl_lines
from sportsedge.pipeline import grading, ladder
from sportsedge.pipeline.intake import SharedIntakeError, parse_envelope, parse_issue
from sportsedge.pipeline.picks import PickRecordError, expected_value, make_pick
from sportsedge.sports.nba.lines_card import NBALinesError
from sportsedge.sports.nba.lines_card import parse_lines as parse_nba

CAPTURED = "2026-10-25T11:58:30-05:00"
TEAMS = {
    "MLB": ("Cubs", "Padres"), "NFL": ("Chiefs", "Ravens"), "CFB": ("Michigan", "Minnesota"),
    "NBA": ("Celtics", "Knicks"), "NHL": ("Rangers", "Bruins"),
}
SPREAD = {"MLB": "RL", "NFL": "Spread", "CFB": "Spread", "NBA": "Spread", "NHL": "PL"}


def muse(sport: str, *, header: bool = True, extra: str = "") -> str:
    away, home = TEAMS[sport]
    rows = [f"{away} @ {home}"] if header else []
    rows += [f"Captured: {CAPTURED}", "<!-- entered by Muse from DK app;",
             "second note line -->", "ML +125 -145", f"{SPREAD[sport]} +1.5 -110 -110",
             "Total 7.5 -108 -112"]
    return "\n".join(rows) + ("\n" + extra if extra else "") + "\n"


def _quads(sport: str, body: str, title: str | None = None):
    """(market family, line, price_a, price_b) per parsed market, per sport entrypoint."""
    if sport == "NFL":
        g = parse_nfl_lines(body, title=title)[0]
        return g.captured_at, [(m.line, m.away_or_over_price, m.home_or_under_price) for m in g.markets]
    if sport == "NHL":
        g = parse_nhl_lines(body, title=title)[0]
        return g.captured_at, [(m.line, m.away_or_over_price, m.home_or_under_price) for m in g.markets]
    if sport == "NBA":
        g = parse_nba(body, title=title)[0]
        return parse_issue(body, "NBA", title=title).games[0].captured_at, [(m.line, m.p1, m.p2) for m in g.markets]
    if sport == "CFB":
        board, _, _ = board_from_body(body, title=title)
        row = board[0]
        return row["captured_at"], [(None, *row["ml"]), tuple(row["spread"]), tuple(row["total"])]
    env = parse_envelope(body, "MLB", title=title)
    rows, _ = parse_lines_with_warnings(env.text, title=title)
    return env.captured_at, [(None if r.market_type == "MONEYLINE" else r.line, r.price, r.paired_price) for r in rows]


EXPECTED = [(None, 125, -145), (1.5, -110, -110), (7.5, -108, -112)]
SPORTS = list(TEAMS)


@pytest.mark.parametrize("sport", SPORTS)
def test_same_body_same_board_every_sport(sport):
    captured, quads = _quads(sport, muse(sport))
    assert captured == CAPTURED
    assert quads == EXPECTED


@pytest.mark.parametrize("sport", SPORTS)
def test_title_is_header_fallback(sport):
    away, home = TEAMS[sport]
    captured, quads = _quads(sport, muse(sport, header=False), title=f"[{sport} LINES] {away} @ {home}")
    assert captured == CAPTURED and quads == EXPECTED


@pytest.mark.parametrize("sport", SPORTS)
def test_one_sided_price_fails_closed(sport):
    body = muse(sport).replace("ML +125 -145", "ML +125")
    with pytest.raises((SharedIntakeError, NflLinesIntakeError, NhlLinesIntakeError, NBALinesError, ValueError)):
        _quads(sport, body)


@pytest.mark.parametrize("sport", SPORTS)
@pytest.mark.parametrize("bad", ["2026-10-25T11:58:30", "11:58 AM CT", "2026-10-25"])
def test_captured_needs_offset_everywhere(sport, bad):
    with pytest.raises(SharedIntakeError, match="CAPTURED_AT"):
        parse_issue(muse(sport).replace(CAPTURED, bad), sport)


@pytest.mark.parametrize("sport", SPORTS)
def test_shared_parser_skips_unknown_market_with_warning(sport):
    board = parse_issue(muse(sport, extra="Mystery Market 3.5 -110 -110"), sport)
    assert len(board.games[0].markets) == 3
    assert any("SKIPPED_UNKNOWN" in w and "Mystery" in w for w in board.warnings)


@pytest.mark.parametrize("sport", SPORTS)
def test_shared_board_identical_across_sports(sport):
    board = parse_issue(muse(sport), sport, resolve_teams=False)
    g = board.games[0]
    assert (g.away, g.home) == TEAMS[sport] and g.captured_at == CAPTURED
    assert [(m.family, m.line, m.side_a, m.price_a, m.side_b, m.price_b) for m in g.markets] == [
        ("moneyline", None, "AWAY", 125, "HOME", -145),
        ("spread", 1.5, "AWAY", -110, "HOME", -110),
        ("total", 7.5, "OVER", -108, "UNDER", -112),
    ]


def test_mlb_bound_input_carries_capture_time():
    game = GameSnapshot(1, "2026-10-25T23:00:00Z", "Preview", 112, "Chicago Cubs", 135, "San Diego Padres",
                        None, None, None, None, "2026-10-25T16:00:00+00:00")
    env = parse_envelope(muse("MLB"), "MLB")
    payload = build_bound_input(env.text, observed_at="2026-10-25T12:00:00-05:00", schedule=[game])
    assert [r["market_type"] for r in payload["rows"]] == ["MONEYLINE", "RUN_LINE", "GAME_TOTAL"]
    assert not any("Captured" in w or "<!--" in w for w in payload.get("intake_warnings") or [])


def test_pick_record_grade_and_clv_are_sport_agnostic():
    data = ladder.load_ladder()
    for sport in SPORTS:
        market = parse_issue(muse(sport), sport, resolve_teams=False).games[0].markets[2]
        pick = make_pick(sport=sport, market=market.market, selection="OVER", line=market.line,
                         dk_price=market.price_a, captured_at=CAPTURED, model_p=0.55, engine="test",
                         opposite_price=market.price_b, ladder=data)
        assert pick.ladder_status == "PAPER"
        assert pick.ev == pytest.approx(expected_value(0.55, -108))
        assert grading.grade(pick, grading.FinalResult(4, 4), family="total") == "WIN"
        assert grading.grade(pick, grading.FinalResult(3, 3), family="total") == "LOSS"
        clv = grading.no_vig_clv(-108, -112, -120, +100, entry_line=7.5, close_line=7.5)
        assert clv > 0


def test_grader_settles_every_family():
    fr = grading.FinalResult(away_score=20, home_score=24)
    assert grading.grade({"selection": "HOME", "line": None}, fr, family="moneyline") == "WIN"
    assert grading.grade({"selection": "AWAY", "line": 4.0}, fr, family="spread") == "PUSH"
    assert grading.grade({"selection": "AWAY", "line": 3.5}, fr, family="spread") == "LOSS"
    assert grading.grade({"selection": "UNDER", "line": 44.5}, fr, family="total") == "WIN"
    assert grading.grade({"selection": "OVER", "line": 245.5}, grading.FinalResult(stat=250), family="prop") == "WIN"
    assert grading.grade({"selection": "YES", "line": None}, grading.FinalResult(occurred=False), family="yes_no") == "LOSS"
    assert grading.units("WIN", +150) == pytest.approx(1.5) and grading.units("PUSH", -110) == 0


def test_clv_refuses_moved_line():
    with pytest.raises(grading.GradeError, match="CLV_LINE_MOVED"):
        grading.no_vig_clv(-110, -110, -110, -110, entry_line=3.5, close_line=3.0)


def test_pick_record_rejects_naive_capture_and_bad_ev():
    with pytest.raises(PickRecordError):
        make_pick(sport="NFL", market="total", selection="OVER", line=47.5, dk_price=-110,
                  captured_at="2026-10-25T11:58:30", model_p=0.5, engine="t", ladder_status="PAPER")


def test_ladder_file_is_paper_everywhere_and_never_inherited():
    data = json.loads(Path("config/market_ladder_status.json").read_text())
    assert {v["status"] for v in data["markets"].values()} == {"PAPER"}
    assert ladder.status_for("NFL", "not_listed", ladder=data) == "PAPER"
    fake = {"markets": {"NFL:spread": {"status": "STAKE_0_25U"}}}
    assert ladder.status_for("NFL", "spread", ladder=fake) == "STAKE_0_25U"
    assert ladder.status_for("CFB", "SPREAD", ladder=fake) == "PAPER"
    assert ladder.status_for("NFL", "total", ladder=fake) == "PAPER"


def test_ladder_evidence_rule_matches_lane7_gate():
    win = [0.9] * 200
    assert ladder.evidence_supports([0.01] * 199, units=[0.9] * 199) == "PAPER"
    assert ladder.evidence_supports([0.01] * 200) == "PAPER"                      # no ROI evidence
    assert ladder.evidence_supports([0.01] * 200, units=[0.9] * 150) == "PAPER"   # mismatched
    assert ladder.evidence_supports([0.01] * 200, units=[-1.0] * 200) == "PAPER"  # ROI <= 0
    assert ladder.evidence_supports([-0.01] * 200, units=win) == "PAPER"          # CLV <= 0
    assert ladder.evidence_supports([0.01] * 200, units=win) == "STAKE_0_25U"
    assert ladder.evidence_supports([0.01] * 200, current="STAKE_0_25U", units=win) == "STAKE_0_5U"
    assert ladder.evidence_supports([-0.01] * 300, current="STAKE_0_5U", units=[0.9] * 300) == "PAPER"


@pytest.mark.parametrize("where", ["board", "after_header"])
def test_envelope_second_capture_fails_closed(where):
    other = "Captured: 2026-10-25T12:30:00-05:00"
    if where == "board":
        body = other + "\n" + muse("MLB", header=False)   # two captures, no header
    else:
        body = muse("MLB")
        body = body.replace("ML +125 -145", other + "\nML +125 -145")
    with pytest.raises(SharedIntakeError, match="CAPTURED_AT_DUPLICATE"):
        parse_envelope(body, "MLB")


def test_snapshot_hook_is_inert_without_store(monkeypatch):
    import importlib

    from sportsedge.pipeline import snapshot_hook
    real = importlib.import_module

    def fake(name, *a, **k):
        if name == "sportsedge.line_snapshots":
            raise ModuleNotFoundError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", fake)
    assert snapshot_hook.record(sport="nfl", issue_number=1, body="", title=None, game={},
                                board=[], picks=[], recorded_at=CAPTURED) == "SNAPSHOT_STORE_UNAVAILABLE"
