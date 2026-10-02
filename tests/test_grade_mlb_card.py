import csv
from pathlib import Path

from scripts.grade_mlb_card import grade_issue, parse_card_rows, settle_actionable


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


def test_issue_1292_regression(tmp_path: Path):
    body = card(
        849848,
        [
            ("Moneyline Away", 113, "ACTIONABLE"),
            ("Totals Over 6.5", -122, "ACTIONABLE"),
            ("Boston Red Sox Team Totals Over 3.5", 120, "ACTIONABLE"),
        ],
    )
    game = feed(
        "Boston Red Sox",
        "New York Yankees",
        2,
        9,
        [(0, 0), (0, 2), (0, 0), (0, 0), (0, 0), (0, 4), (1, 1), (1, 2), (0, 0)],
    )
    rendered = grade_issue(
        1292,
        comments=[{"body": body}],
        feed=game,
        ledger_path=tmp_path / "mlb_ledger.csv",
        post_comment=False,
    )
    assert "Moneyline Away | +113 | L | -1.00u" in rendered
    assert "Totals Over 6.5 | -122 | W | +0.82u" in rendered
    assert "Boston Red Sox Team Totals Over 3.5 | +120 | L | -1.00u" in rendered
    assert "**Record:** 1-2-0 · **Net:** -1.18u" in rendered


def test_issue_1294_grades_all_nine_actionable_rows(tmp_path: Path):
    rows = [
        ("Totals Over 7.5", 101, "ACTIONABLE"),
        ("Chicago Cubs Team Totals Over 3.5", 105, "ACTIONABLE"),
        ("San Diego Padres Team Totals Over 4.5", 130, "ACTIONABLE"),
        ("San Diego Padres Team Totals Over 3.5", -130, "ACTIONABLE"),
        ("Moneyline Away", 123, "ACTIONABLE"),
        ("Totals Over 7", -126, "ACTIONABLE"),
        ("F5 Totals Over 5.5", 175, "ACTIONABLE"),
        ("Chicago Cubs F5 Team Totals Over 1.5", -120, "ACTIONABLE"),
        ("F5 Totals Over 4.5", 105, "ACTIONABLE"),
    ]
    body = card(849842, rows)
    game = feed(
        "Chicago Cubs",
        "San Diego Padres",
        1,
        4,
        [(0, 1), (0, 2), (1, 0), (0, 1), (0, 0), (0, 0), (0, 0), (0, 0), (0, 0)],
    )
    rendered = grade_issue(
        1294,
        comments=[{"body": body}],
        feed=game,
        ledger_path=tmp_path / "mlb_ledger.csv",
        post_comment=False,
    )
    assert "San Diego Padres Team Totals Over 3.5 | -130 | W | +0.77u" in rendered
    assert "F5 Totals Over 4.5 | +105 | W | +1.05u" in rendered
    assert "**Record:** 2-7-0 · **Net:** -5.18u" in rendered
    ledger = (tmp_path / "mlb_ledger.csv").read_text()
    assert "1294,849842,Chicago Cubs,San Diego Padres,1-4,2,7,0,-5.1808,-57.56" in ledger


def test_f5_run_line_and_first_inning_markets():
    game = feed("Away", "Home", 3, 4, [(1, 0), (0, 2), (1, 0), (0, 0), (0, 0), (1, 2)])
    rows = parse_card_rows(
        card(
            1,
            [
                ("F5 Run Line Away +0.5", -110, "ACTIONABLE"),
                ("Yrfi Yes", -105, "ACTIONABLE"),
                ("Nrfi Yes", -110, "ACTIONABLE"),
            ],
        )
    )
    assert settle_actionable(rows[0], game).result == "W"
    assert settle_actionable(rows[1], game).result == "W"
    assert settle_actionable(rows[2], game).result == "L"


def test_lean_props_grade_separately_and_nonstarters_void(tmp_path: Path):
    body = card(
        7,
        [
            ("Moneyline Away", 100, "ACTIONABLE"),
            ("Starter Batter Hits Over 0.5", -110, "LEAN"),
            ("Bench Bat Hits Over 0.5", -110, "LEAN"),
            ("Starter Pitcher Pitcher K Over 4.5", 120, "LEAN"),
        ],
    )
    game = feed("Away", "Home", 1, 0, [(1, 0)])
    away_box = game["liveData"]["boxscore"]["teams"]["away"]
    away_box["pitchers"] = [30, 40]
    away_box["players"] = {
        "ID10": {
            "person": {"id": 10, "fullName": "Starter Batter"},
            "battingOrder": "100",
            "stats": {"batting": {"hits": 1}},
        },
        "ID20": {
            "person": {"id": 20, "fullName": "Bench Bat"},
            "battingOrder": "101",
            "stats": {"batting": {"hits": 1}},
        },
        "ID30": {
            "person": {"id": 30, "fullName": "Starter Pitcher"},
            "stats": {"pitching": {"strikeOuts": 6, "inningsPitched": "5.0"}},
        },
    }
    rendered = grade_issue(
        77,
        comments=[{"body": body}],
        feed=game,
        ledger_path=tmp_path / "mlb_ledger.csv",
        post_comment=False,
    )
    assert "**Record:** 1-0-0 · **Net:** +1.00u" in rendered
    assert "Starter Batter Hits Over 0.5 | -110 | W | +0.91u" in rendered
    assert "Bench Bat Hits Over 0.5 | -110 | VOID | +0.00u" in rendered
    assert "Starter Pitcher Pitcher K Over 4.5 | +120 | W | +1.20u" in rendered
    with (tmp_path / "mlb_ledger.csv").open(newline="") as handle:
        ledger_rows = list(csv.DictReader(handle))
    assert ledger_rows[0]["wins"] == "1"
    assert ledger_rows[0]["losses"] == "0"


def test_ledger_upsert_is_idempotent_for_same_settlement(tmp_path: Path):
    body = card(1, [("Moneyline Away", 100, "ACTIONABLE")])
    game = feed("Away", "Home", 1, 0, [(1, 0)])
    path = tmp_path / "mlb_ledger.csv"
    grade_issue(10, comments=[{"body": body}], feed=game, ledger_path=path, post_comment=False)
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows[0]["graded_at_utc"] = "2000-01-01T00:00:00+00:00"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    grade_issue(10, comments=[{"body": body}], feed=game, ledger_path=path, post_comment=False)
    with path.open(newline="") as handle:
        rerun = list(csv.DictReader(handle))
    assert len(rerun) == 1
    assert rerun[0]["graded_at_utc"] == "2000-01-01T00:00:00+00:00"


def test_non_final_game_is_skipped_without_ledger(tmp_path: Path):
    body = card(1, [("Moneyline Away", 100, "ACTIONABLE")])
    game = feed("Away", "Home", 0, 0, [])
    game["gameData"]["status"] = {
        "abstractGameState": "Live",
        "detailedState": "In Progress",
    }
    path = tmp_path / "mlb_ledger.csv"
    assert (
        grade_issue(
            10,
            comments=[{"body": body}],
            feed=game,
            ledger_path=path,
            post_comment=False,
        )
        == "SKIP_NOT_FINAL"
    )
    assert not path.exists()


def test_issue_without_final_card_is_skipped(tmp_path: Path):
    path = tmp_path / "mlb_ledger.csv"
    assert (
        grade_issue(
            10,
            comments=[{"body": "# SportsEdge MLB card (PRE-CONTEXT · NOT FINAL)"}],
            feed=feed("Away", "Home", 1, 0, [(1, 0)]),
            ledger_path=path,
            post_comment=False,
        )
        == "SKIP_NO_FINAL_CARD"
    )
    assert not path.exists()
