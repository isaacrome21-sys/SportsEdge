import csv
from pathlib import Path

from scripts.grade_mlb_card import grade_issue, parse_card_rows, settle_actionable, settle_lean


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


def test_legacy_numeric_team_totals_and_actionable_pitcher_props():
    game = feed(
        "Chicago Cubs",
        "San Diego Padres",
        5,
        3,
        [(1, 0), (0, 1), (2, 0), (0, 1), (0, 0), (2, 1)],
    )
    game["gameData"]["teams"]["away"]["id"] = 112
    game["gameData"]["teams"]["home"]["id"] = 135
    away_box = game["liveData"]["boxscore"]["teams"]["away"]
    away_box["pitchers"] = [30]
    away_box["players"] = {
        "ID30": {
            "person": {"id": 30, "fullName": "Matthew Boyd"},
            "stats": {
                "pitching": {
                    "strikeOuts": 5,
                    "hits": 4,
                    "earnedRuns": 1,
                    "baseOnBalls": 2,
                    "inningsPitched": "6.0",
                }
            },
        },
    }
    game["liveData"]["decisions"] = {
        "winner": {"id": 30, "fullName": "Matthew Boyd"}
    }
    rows = parse_card_rows(
        card(
            849843,
            [
                ("112 Team Totals Over 3.5", -115, "ACTIONABLE"),
                ("135 Team Totals Under 3.5", -125, "ACTIONABLE"),
                ("112 F5 Team Totals Over 1.5", -125, "ACTIONABLE"),
                ("Matthew Boyd Pitcher K Over 4.5", 111, "ACTIONABLE"),
                ("Matthew Boyd Pitcher Hits Allowed Under 4.5", 117, "ACTIONABLE"),
                ("Matthew Boyd Pitcher Record Win Yes 0", 363, "ACTIONABLE"),
            ],
        )
    )
    assert [settle_actionable(row, game).result for row in rows] == [
        "W", "W", "W", "W", "W", "W"
    ]


def test_unknown_actionable_market_remains_fatal():
    game = feed("Away", "Home", 1, 0, [(1, 0)])
    row = parse_card_rows(
        card(7, [("Player Future Market Yes 0", 100, "ACTIONABLE")])
    )[0]
    try:
        settle_actionable(row, game)
    except ValueError as exc:
        assert str(exc).startswith("unsupported ACTIONABLE market:")
    else:
        raise AssertionError("unknown ACTIONABLE market must fail closed")


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


def test_extended_batter_lean_prop_families():
    game = feed("Away", "Home", 1, 0, [(1, 0)])
    away_box = game["liveData"]["boxscore"]["teams"]["away"]
    away_box["players"] = {
        "ID10": {
            "person": {"id": 10, "fullName": "Fernando Tatis Jr."},
            "battingOrder": "100",
            "stats": {
                "batting": {
                    "hits": 3,
                    "doubles": 1,
                    "triples": 0,
                    "homeRuns": 1,
                    "totalBases": 7,
                    "rbi": 2,
                    "runs": 2,
                    "baseOnBalls": 1,
                    "strikeOuts": 1,
                    "stolenBases": 1,
                }
            },
        }
    }
    cases = [
        ("Fernando Tatis Jr. Singles Over 0.5", "W"),
        ("Fernando Tatis Jr. Doubles Over 0.5", "W"),
        ("Fernando Tatis Jr. Triples Under 0.5", "W"),
        ("Fernando Tatis Jr. Home Runs Over 0.5", "W"),
        ("Fernando Tatis Jr. Runs Over 1.5", "W"),
        ("Fernando Tatis Jr. Stolen Bases Over 0.5", "W"),
        ("Fernando Tatis Jr. Batter K Over 0.5", "W"),
        ("Fernando Tatis Jr. Extra Base Hits Over 1.5", "W"),
        ("Fernando Tatis Jr. Hits Runs Rbis Over 6.5", "W"),
        ("Fernando Tatis Jr. Hits Runs Stolen Bases Over 5.5", "W"),
        ("Fernando Tatis Jr. Runs Rbis Over 3.5", "W"),
        ("Fernando Tatis Jr. Hits Stolen Bases Over 3.5", "W"),
        ("Fernando Tatis Jr. Hits Walks Stolen Bases Over 4.5", "W"),
    ]
    for pick, expected in cases:
        row = parse_card_rows(card(7, [(pick, -110, "LEAN")]))[0]
        assert settle_lean(row, game).result == expected, pick


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


def test_pitcher_record_win_lean_uses_official_decision():
    game = feed("Away", "Home", 4, 2, [(1, 0)])
    away_box = game["liveData"]["boxscore"]["teams"]["away"]
    away_box["pitchers"] = [30]
    away_box["players"] = {
        "ID30": {
            "person": {"id": 30, "fullName": "Tyler Mahle"},
            "stats": {"pitching": {"strikeOuts": 5, "inningsPitched": "6.0"}},
        },
    }
    game["liveData"]["decisions"] = {
        "winner": {"id": 30, "fullName": "Tyler Mahle"}
    }
    yes = parse_card_rows(
        card(7, [("Tyler Mahle Pitcher Record Win Yes 0", 340, "LEAN")])
    )[0]
    no = parse_card_rows(
        card(7, [("Tyler Mahle Pitcher Record Win No 0", -120, "LEAN")])
    )[0]
    assert settle_lean(yes, game).result == "W"
    assert settle_lean(no, game).result == "L"


def test_unknown_lean_market_is_unresolved_not_fatal():
    game = feed("Away", "Home", 1, 0, [(1, 0)])
    row = parse_card_rows(card(7, [("Player Future Market Yes 0", 100, "LEAN")]))[0]
    settled = settle_lean(row, game)
    assert settled.result == "UNRESOLVED"
    assert settled.units == 0.0


def test_multigame_card_grades_per_game_and_keeps_distinct_ledger_rows(tmp_path: Path):
    body_lines = card(1, [("Moneyline Away", 100, "ACTIONABLE")]).splitlines()
    body_lines.append(
        "| 2 | 2 | Moneyline Home | +100 | 50% | 0% | 50% | +100 | 0% | 0 | 100 | ACTIONABLE |"
    )
    body = "\n".join(body_lines)
    feeds = {
        1: feed("Away One", "Home One", 2, 1, [(1, 0), (1, 1)]),
        2: feed("Away Two", "Home Two", 1, 3, [(0, 1), (1, 2)]),
    }
    path = tmp_path / "mlb_ledger.csv"
    rendered = grade_issue(
        1460,
        comments=[{"body": body}],
        feeds=feeds,
        ledger_path=path,
        post_comment=False,
    )
    assert "Away One @ Home One (2-1)" in rendered
    assert "Away Two @ Home Two (1-3)" in rendered
    assert rendered.count("<!-- sportsedge-mlb-auto-grade:v1 issue=1460 -->") == 1
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [(row["issue_number"], row["game_pk"]) for row in rows] == [
        ("1460", "1"),
        ("1460", "2"),
    ]
    assert [row["wins"] for row in rows] == ["1", "1"]


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


def test_lean_only_final_card_grades_without_main_ledger(tmp_path: Path):
    body = card(7, [("Starter Pitcher Pitcher K Over 4.5", 120, "LEAN")])
    game = feed("Away", "Home", 1, 0, [(1, 0)])
    away_box = game["liveData"]["boxscore"]["teams"]["away"]
    away_box["pitchers"] = [30]
    away_box["players"] = {
        "ID30": {
            "person": {"id": 30, "fullName": "Starter Pitcher"},
            "stats": {"pitching": {"strikeOuts": 6, "inningsPitched": "5.0"}},
        },
    }
    path = tmp_path / "mlb_ledger.csv"
    rendered = grade_issue(
        88,
        comments=[{"body": body}],
        feed=game,
        ledger_path=path,
        post_comment=False,
    )
    assert "**Record:** 0-0-0 · **Net:** +0.00u" in rendered
    assert "Starter Pitcher Pitcher K Over 4.5 | +120 | W | +1.20u" in rendered
    assert not path.exists()


def test_final_card_without_actionable_or_lean_rows_is_skipped(tmp_path: Path):
    path = tmp_path / "mlb_ledger.csv"
    body = card(1, [("Moneyline Away", 100, "BLOCKED")])
    assert (
        grade_issue(
            1807,
            comments=[{"body": body}],
            feed=feed("Away", "Home", 1, 0, [(1, 0)]),
            ledger_path=path,
            post_comment=False,
        )
        == "SKIP_NO_GRADEABLE_ROWS"
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
