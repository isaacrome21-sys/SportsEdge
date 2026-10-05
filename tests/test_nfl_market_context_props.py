import pytest

from sportsedge.sports.nfl.market_context_props import (
    MarketContextPropError,
    run_market_context_props,
)


def test_market_context_sets_score_environment_without_game_picks():
    out = run_market_context_props(
        game_id="G1",
        home_team="HOME",
        away_team="AWAY",
        home_spread=-3.5,
        game_total=45.5,
        as_of="2026-10-05T16:00:00Z",
        n_sims=100,
        seed=7,
    )
    assert out["market_environment"]["fair_home_margin"] == pytest.approx(3.5)
    assert out["market_environment"]["game_total"] == pytest.approx(45.5)
    assert out["game_card"]["picks"] == []
    assert out["authority"]["creates_game_market_edge"] is False
    assert "attempt9_raw" not in out["model"]


def test_home_underdog_maps_to_negative_expected_margin():
    out = run_market_context_props(
        game_id="G2",
        home_team="HOME",
        away_team="AWAY",
        home_spread=2.5,
        game_total=42.0,
        as_of="2026-10-05T16:00:00Z",
        n_sims=50,
        seed=3,
    )
    assert out["market_environment"]["fair_home_margin"] == pytest.approx(-2.5)


def test_total_must_be_positive():
    with pytest.raises(MarketContextPropError, match="POSITIVE_REQUIRED"):
        run_market_context_props(
            game_id="G3",
            home_team="HOME",
            away_team="AWAY",
            home_spread=-3.0,
            game_total=0,
            as_of="2026-10-05T16:00:00Z",
        )


def _player(name, position, *, pa=0, comp=0.0, ypcmp=0.0, ra=0.0, ypc=0.0, tg=0.0, cr=0.0, ypr=0.0):
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
        "sample_size": 8,
        "context": {"shared_workload_sigma": 0.04},
    }


def _team(prefix):
    return {
        "qb": _player(f"{prefix}_QB", "QB", pa=34, comp=0.66, ypcmp=11.0, ra=4, ypc=4.5),
        "skill_players": [
            _player(f"{prefix}_RB", "RB", ra=15, ypc=4.3, tg=4.0, cr=0.75, ypr=8.0),
            _player(f"{prefix}_WR", "WR", tg=8.0, cr=0.65, ypr=11.5),
        ],
    }


def test_market_context_flows_player_probability_to_prop_board():
    quotes = []
    for book in ("draftkings", "fanduel", "betmgm"):
        for selection, price in (("OVER", 105), ("UNDER", -125)):
            quotes.append({
                "game_id": "G4",
                "player": "H_QB",
                "market": "passing_yards",
                "selection": selection,
                "line": 239.5,
                "book": book,
                "price_american": price,
                "retrieved_at": "2026-10-05T15:59:00Z",
            })
    qualification = [{
        "game_id": "G4",
        "market": "passing_yards",
        "selection": "H_QB",
        "captured_at": "2026-10-05T15:59:00Z",
        "kickoff_at": "2026-10-05T20:00:00Z",
        "source_version": "nfl-market-context-props-v1",
        "feature_digest": "ctx1",
        "model_ready": True,
        "pit_safe": True,
        "role_stable": True,
        "usage_supported": True,
        "matchup_supported": True,
        "injury_context_ready": True,
        "shared_simulation_ready": True,
        "market_binding_ready": True,
    }]
    out = run_market_context_props(
        game_id="G4",
        home_team="HOME",
        away_team="AWAY",
        home_spread=-2.5,
        game_total=46.0,
        prop_quotes=quotes,
        qualification_snapshots=qualification,
        home_model=_team("H"),
        away_model=_team("A"),
        as_of="2026-10-05T16:00:00Z",
        n_sims=400,
        seed=9,
    )
    rows = [row for row in out["prop_board"] if row["player"] == "H_QB" and row["market"] == "passing_yards"]
    assert rows
    assert all(row["status"] == "OK" for row in rows)
    assert out["game_card"]["picks"] == []
