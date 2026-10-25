"""CLV vs DraftKings close for graded MLB card picks."""
import csv
from pathlib import Path

from scripts.grade_mlb_card import grade_issue
from scripts.mlb_card_clv import compute_clv, fair_probability, parse_captured_at, pick_key
from scripts.grade_mlb_card import CardRow


def feed(away_name, home_name, away_runs, home_runs, innings):
    return {
        "gameData": {
            "status": {"abstractGameState": "Final", "detailedState": "Final"},
            "datetime": {"officialDate": "2026-09-30"},
            "teams": {"away": {"name": away_name}, "home": {"name": home_name}},
        },
        "liveData": {
            "linescore": {
                "teams": {"away": {"runs": away_runs}, "home": {"runs": home_runs}},
                "innings": [
                    {"num": i + 1, "away": {"runs": a}, "home": {"runs": h}}
                    for i, (a, h) in enumerate(innings)
                ],
            },
            "boxscore": {
                "teams": {
                    "away": {"players": {}, "pitchers": []},
                    "home": {"players": {}, "pitchers": []},
                }
            },
        },
    }


def card(game_pk, rows):
    head = [
        "# SportsEdge MLB card (MLB_MYSPARI_OWN_MODEL_V1)",
        "",
        "| # | Game | Pick | Odds | Win p | Push p | Win p ex-push | Fair | Edge | EV/$ | Score | Status |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, (pick, price, status) in enumerate(rows, 1):
        head.append(
            f"| {i} | {game_pk} | {pick} | {price:+d} | 50% | 0% | 50% | +100 | 0% | 0 | 100 | {status} |"
        )
    return "\n".join(head)


NAMES = {"away": "Tampa Bay Rays", "home": "Milwaukee Brewers"}
TITLE = "[MLB LINES] TB Rays @ MIL Brewers WS G2"


def _feed():
    game = feed("Tampa Bay Rays", "Milwaukee Brewers", 2, 4,
                [(1, 0), (0, 2), (0, 0), (0, 0), (1, 0), (0, 2), (0, 0), (0, 0), (0, 0)])
    game["gameData"]["datetime"]["dateTime"] = "2026-10-25T00:00:00Z"
    return game


def _issue(number, captured, body_lines, created="2026-10-24T22:00:00Z"):
    head = ["TB Rays @ MIL Brewers"]
    if captured:
        head.append(f"Captured: {captured}")
    return {"number": number, "title": TITLE, "created_at": created,
            "body": "\n".join(head + body_lines)}


ENTRY = _issue(100, "2026-10-24T22:20:00Z", [
    "ML +100 -120", "Total 6.5 -108 -111", "RL -1.5 +180 / +1.5 -221",
    "Team Totals: MIL 3.5 +120 -154; TB 3.5 +120 -154",
    "Pitcher props — Drew Rasmussen (TB):", "K 5.5 -159 +125",
])
CLOSE = _issue(101, "2026-10-24T23:50:00Z", [
    "ML +110 -130", "Total 6.5 -120 +100", "RL -1.5 +190 / +1.5 -230",
    "Team Totals: MIL 3.5 +110 -140",
    "Pitcher props — Drew Rasmussen (TB):", "K 5.5 -170 +135",
])
AFTER_START = _issue(102, "2026-10-25T00:10:00Z", ["ML +300 -400"])
NO_CAPTURED = _issue(103, None, ["ML +150 -180"], created="2026-10-24T23:59:00Z")


def test_captured_line_parse():
    assert parse_captured_at(CLOSE["body"]).isoformat() == "2026-10-24T23:50:00+00:00"
    assert parse_captured_at(NO_CAPTURED["body"]) is None
    assert parse_captured_at("A @ B\nCaptured: 2026-10-24T17:00:00") is None  # naive refused


def test_pick_keys():
    assert pick_key("Run Line Home +1.5", NAMES).line == -1.5
    assert pick_key("Nrfi Yes", NAMES).side == "UNDER"
    assert pick_key("Milwaukee Brewers Team Totals Over 3.5", NAMES).team_side == "HOME"
    assert pick_key("Drew Rasmussen Pitcher K Over 5.5", NAMES).market_type == "PITCHER_STRIKEOUTS"
    assert pick_key("Mystery Market", NAMES) is None


def _run(picks, others):
    return {r["pick"]: r for r in compute_clv(
        issue_number=100, picks=picks, feed=_feed(), entry_issue=ENTRY, other_issues=others)}


def test_clv_uses_last_pregame_captured_issue_only():
    picks = [
        CardRow(1, "Moneyline Home", -120, "ACTIONABLE"),
        CardRow(1, "Totals Over 6.5", -108, "ACTIONABLE"),
        CardRow(1, "Run Line Home +1.5", -221, "ACTIONABLE"),
        CardRow(1, "Milwaukee Brewers Team Totals Over 3.5", 120, "ACTIONABLE"),
        CardRow(1, "Drew Rasmussen Pitcher K Over 5.5", -159, "LEAN"),
    ]
    out = _run(picks, [ENTRY, CLOSE, AFTER_START, NO_CAPTURED])
    ml = out["Moneyline Home"]
    assert ml["clv_status"] == "CLV_TRACKED" and ml["close_issue"] == "101"
    expect = fair_probability(-130, 110) - fair_probability(-120, 100)
    assert abs(float(ml["clv_prob"]) - expect) < 1e-6 and expect > 0
    assert float(out["Totals Over 6.5"]["clv_prob"]) > 0
    assert out["Run Line Home +1.5"]["close_price"] == "-230"
    assert float(out["Milwaukee Brewers Team Totals Over 3.5"]["clv_prob"]) > 0
    assert out["Drew Rasmussen Pitcher K Over 5.5"]["clv_status"] == "CLV_TRACKED"


def test_missing_close_and_price_mismatch_fail_closed():
    out = _run([CardRow(1, "Moneyline Home", -120, "ACTIONABLE")], [AFTER_START, NO_CAPTURED])
    assert out["Moneyline Home"]["clv_status"] == "NO_CLOSE_QUOTE"
    out = _run([CardRow(1, "Moneyline Home", -125, "ACTIONABLE")], [CLOSE])
    assert out["Moneyline Home"]["clv_status"] == "NO_ENTRY_QUOTE"
    out = _run([CardRow(1, "Yrfi Yes", 130, "ACTIONABLE")], [CLOSE])
    assert out["Yrfi Yes"]["clv_status"] == "NO_ENTRY_QUOTE"


def test_grade_issue_writes_clv_ledger_and_comment(tmp_path: Path):
    body = card(1, [("Moneyline Home", -120, "ACTIONABLE")])
    clv_path = tmp_path / "mlb_clv_ledger.csv"
    rendered = grade_issue(100, comments=[{"body": body}], feed=_feed(),
                           ledger_path=tmp_path / "l.csv", post_comment=False,
                           issue=ENTRY, line_issues=[ENTRY, CLOSE], clv_ledger_path=clv_path)
    assert "CLV vs DraftKings close" in rendered and "CLV_TRACKED" in rendered
    rows = list(csv.DictReader(clv_path.open()))
    assert len(rows) == 1 and rows[0]["close_issue"] == "101"
    # Idempotent re-grade.
    grade_issue(100, comments=[{"body": body}], feed=_feed(), ledger_path=tmp_path / "l.csv",
                post_comment=False, issue=ENTRY, line_issues=[ENTRY, CLOSE], clv_ledger_path=clv_path)
    assert len(list(csv.DictReader(clv_path.open()))) == 1
