import pytest

from sportsedge.sports.nfl.unified_run_it import run_unified_nfl_run_it


AS_OF = "2026-10-01T23:00:30Z"
STAMP = "2026-10-01T23:00:00Z"
BOOKS = ("draftkings", "fanduel", "betmgm")


def role(name, position, *, pa=0, comp=0.0, ypcmp=0.0, ra=0.0, ypc=0.0, tg=0.0, cr=0.0, ypr=0.0):
    return {
        "player": name,
        "position": position,
        "role_prior": {
            "pass_attempts": pa,
            "completion_rate": comp,
            "pass_yards_per_completion": ypcmp,
            "pass_td_rate": 0.05 if position == "QB" else 0.0,
            "interception_rate": 0.025 if position == "QB" else 0.0,
            "rush_attempts": ra,
            "rush_yards_per_attempt": ypc,
            "targets": tg,
            "catch_rate": cr,
            "receiving_yards_per_reception": ypr,
        },
        "trailing": {},
        "sample_size": 0,
        "context": {"shared_workload_sigma": 0.04},
    }


def team(prefix):
    return {
        "qb": role(f"{prefix}_QB", "QB", pa=34, comp=0.66, ypcmp=11.0, ra=4, ypc=4.5),
        "skill_players": [
            role(f"{prefix}_RB1", "RB", ra=15, ypc=4.3, tg=5.5, cr=0.76, ypr=8.2),
            role(f"{prefix}_WR1", "WR", ra=0.4, ypc=5.0, tg=9, cr=0.67, ypr=12.1),
            role(f"{prefix}_WR2", "WR", ra=0.2, ypc=4.5, tg=6.5, cr=0.64, ypr=10.8),
            role(f"{prefix}_OTHER", "OTHER", ra=3, ypc=4.0, tg=5, cr=0.62, ypr=8.8),
        ],
    }


def game_quotes():
    rows = []
    for market, a_sel, a_line, b_sel, b_line in (
        ("moneyline", "HOME", None, "AWAY", None),
        ("spread", "HOME", -3.5, "AWAY", 3.5),
        ("total", "OVER", 45.5, "UNDER", 45.5),
    ):
        for selection, line, price in ((a_sel, a_line, -110), (b_sel, b_line, -110)):
            row = {
                "game_id": "2026_04_AWAY_HOME",
                "home": "HOME",
                "away": "AWAY",
                "market": market,
                "selection": selection,
                "price_american": price,
                "book": "draftkings",
                "retrieved_at": STAMP,
            }
            if line is not None:
                row["line"] = line
            rows.append(row)
    return rows


def prop_pair(player, market, line):
    rows = []
    for book in BOOKS:
        for selection, price in (("OVER", 110), ("UNDER", -130)):
            rows.append({
                "game_id": "2026_04_AWAY_HOME",
                "player": player,
                "market": market,
                "selection": selection,
                "line": line,
                "book": book,
                "price_american": price,
                "retrieved_at": STAMP,
            })
    return rows


def snap(market, selection):
    return {
        "game_id": "2026_04_AWAY_HOME",
        "market": market,
        "selection": selection,
        "captured_at": "2026-10-01T22:59:00Z",
        "kickoff_at": "2026-10-04T17:00:00Z",
        "source_version": "nfl-unified-v1",
        "feature_digest": "abc123",
        "model_ready": True,
        "pit_safe": True,
        "role_stable": True,
        "usage_supported": True,
        "matchup_supported": True,
        "injury_context_ready": True,
        "shared_simulation_ready": True,
        "market_binding_ready": True,
    }


def qualifications():
    rows = []
    for market, selections in (
        ("moneyline", ("HOME", "AWAY")),
        ("spread", ("HOME", "AWAY")),
        ("total", ("OVER", "UNDER")),
    ):
        for selection in selections:
            rows.append(snap(market, selection))
    for player, market in (
        ("H_QB", "passing_yards"),
        ("H_RB1", "rushing_yards"),
        ("H_WR1", "receiving_yards"),
        ("H_WR1", "receptions"),
    ):
        rows.append(snap(market, player))
    return rows


def test_unified_run_it_drives_game_qb_rb_wr_surfaces():
    props = (
        prop_pair("H_QB", "passing_yards", 239.5)
        + prop_pair("H_RB1", "rushing_yards", 64.5)
        + prop_pair("H_WR1", "receiving_yards", 69.5)
        + prop_pair("H_WR1", "receptions", 5.5)
    )
    out = run_unified_nfl_run_it(
        game_id="2026_04_AWAY_HOME",
        home_team="HOME",
        away_team="AWAY",
        attempt9_margin=4.0,
        attempt9_total=45.0,
        game_quotes=game_quotes(),
        prop_quotes=props,
        qualification_snapshots=qualifications(),
        home_model=team("H"),
        away_model=team("A"),
        as_of=AS_OF,
        edge_floor=0.0,
        n_sims=1200,
        seed=31,
    )

    assert out["schema"] == "SPORTSEDGE_NFL_UNIFIED_RUN_IT_V1"
    assert out["model"]["score_distribution"]["sampled_paths"] == 1200
    assert out["authority"]["research_only"] is True
    assert out["authority"]["creates_model_p"] is False
    assert out["game_card"]["picks"]
    by_prop = {(row["player"], row["market"]): row for row in out["prop_board"]}
    for key in (
        ("H_QB", "passing_yards"),
        ("H_RB1", "rushing_yards"),
        ("H_WR1", "receiving_yards"),
        ("H_WR1", "receptions"),
    ):
        assert by_prop[key]["status"] == "OK"
        assert by_prop[key]["score_0_100"] == 100
        assert by_prop[key]["book"] == "draftkings"


def test_away_plus_spread_is_team_specific_through_operational_adapter():
    out = run_unified_nfl_run_it(
        game_id="2026_04_AWAY_HOME",
        home_team="HOME",
        away_team="AWAY",
        attempt9_margin=3.0,
        attempt9_total=44.0,
        game_quotes=game_quotes(),
        qualification_snapshots=qualifications(),
        home_model=team("H"),
        away_model=team("A"),
        as_of=AS_OF,
        edge_floor=0.0,
        n_sims=600,
        seed=7,
    )
    spread_rows = [row for row in out["model"]["game_markets"] if row["market"] == "spread"]
    home = next(row for row in spread_rows if row["selection"] == "home")
    away = next(row for row in spread_rows if row["selection"] == "away")
    assert home["line"] == -3.5
    assert away["line"] == 3.5
    assert home["push_p"] == 0.0
    assert away["push_p"] == 0.0
    assert home["estimate_p"] + away["estimate_p"] == pytest.approx(1.0)


def test_missing_td_prior_does_not_kill_non_td_prop_board():
    td_quotes = []
    for book in BOOKS:
        td_quotes += [
            {
                "game_id": "2026_04_AWAY_HOME",
                "player": "H_RB1",
                "selection": "YES",
                "book": book,
                "price_american": 150,
                "retrieved_at": STAMP,
            },
            {
                "game_id": "2026_04_AWAY_HOME",
                "player": "H_RB1",
                "selection": "NO",
                "book": book,
                "price_american": -180,
                "retrieved_at": STAMP,
            },
        ]
    q = qualifications() + [snap("anytime_td", "H_RB1")]
    out = run_unified_nfl_run_it(
        game_id="2026_04_AWAY_HOME",
        home_team="HOME",
        away_team="AWAY",
        attempt9_margin=2.0,
        attempt9_total=44.0,
        game_quotes=game_quotes(),
        prop_quotes=prop_pair("H_QB", "passing_yards", 229.5),
        td_quotes=td_quotes,
        qualification_snapshots=q,
        home_model=team("H"),
        away_model=team("A"),
        scoring_prior=None,
        as_of=AS_OF,
        edge_floor=0.0,
        n_sims=400,
        seed=11,
    )
    assert any(row["status"] == "OK" for row in out["prop_board"])
    assert out["td_board"] == []
    assert any(
        row.get("market") == "anytime_tds"
        and row.get("reason") == "SCORING_COMPOSITION_PRIOR_REQUIRED_FOR_TD_PROPS"
        for row in out["model_blocks"]
    )
