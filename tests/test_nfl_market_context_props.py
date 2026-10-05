import pytest

from sportsedge.sports.nfl.market_context_props import (
    MarketContextPropError,
    run_market_context_props,
)


AS_OF = "2026-10-05T16:00:00Z"
STAMP = "2026-10-05T15:59:00Z"
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
        "sample_size": 8,
        "context": {"shared_workload_sigma": 0.04},
    }


def team(prefix):
    return {
        "qb": role(f"{prefix}_QB", "QB", pa=34, comp=0.66, ypcmp=11.0, ra=4, ypc=4.5),
        "skill_players": [
            role(f"{prefix}_RB1", "RB", ra=15, ypc=4.3, tg=5.5, cr=0.76, ypr=8.2),
            role(f"{prefix}_WR1", "WR", tg=9, cr=0.67, ypr=12.1),
            role(f"{prefix}_WR2", "WR", tg=6.5, cr=0.64, ypr=10.8),
        ],
    }


def prop_pair(player, market, line):
    rows = []
    for book in BOOKS:
        for selection, price in (("OVER", 110), ("UNDER", -130)):
            rows.append({
                "game_id": "G1",
                "player": player,
                "market": market,
                "selection": selection,
                "line": line,
                "book": book,
                "price_american": price,
                "retrieved_at": STAMP,
            })
    return rows


def snap(market, player):
    return {
        "game_id": "G1",
        "market": market,
        "selection": player,
        "captured_at": STAMP,
        "kickoff_at": "2026-10-05T20:00:00Z",
        "source_version": "nfl-market-context-props-v1",
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


def test_market_context_prices_props_without_game_edge_rows():
    props = (
        prop_pair("H_QB", "passing_yards", 239.5)
        + prop_pair("H_RB1", "rushing_yards", 64.5)
        + prop_pair("H_WR1", "receiving_yards", 69.5)
    )
    q = [
        snap("passing_yards", "H_QB"),
        snap("rushing_yards", "H_RB1"),
        snap("receiving_yards", "H_WR1"),
    ]
    out = run_market_context_props(
        game_id="G1",
        home_team="HOME",
        away_team="AWAY",
        home_spread=-3.5,
        game_total=45.5,
        prop_quotes=props,
        qualification_snapshots=q,
        home_model=team("H"),
        away_model=team("A"),
        as_of=AS_OF,
        n_sims=1000,
        seed=13,
    )
    assert out["schema"] == "SPORTSEDGE_NFL_MARKET_CONTEXT_PROP_RUN_IT_V1"
    assert out["market_environment"]["fair_home_margin"] == pytest.approx(3.5)
    assert out["market_environment"]["game_total"] == pytest.approx(45.5)
    assert out["game_card"]["picks"] == []
    assert out["game_card"]["status"] == "DISABLED_GAME_EDGE_MODEL_FAILED"
    assert out["authority"]["creates_game_market_edge"] is False
    assert out["authority"]["creates_model_p"] is False
    assert "attempt9_raw" not in out["model"]
    by_prop = {(r["player"], r["market"]): r for r in out["prop_board"]}
    assert by_prop[("H_QB", "passing_yards")]["status"] == "OK"
    assert by_prop[("H_RB1", "rushing_yards")]["status"] == "OK"
    assert by_prop[("H_WR1", "receiving_yards")]["status"] == "OK"


def test_home_underdog_sign_maps_to_negative_expected_margin():
    out = run_market_context_props(
        game_id="G1",
        home_team="HOME",
        away_team="AWAY",
        home_spread=2.5,
        game_total=42.0,
        home_model=team("H"),
        away_model=team("A"),
        as_of=AS_OF,
        n_sims=100,
        seed=1,
    )
    assert out["market_environment"]["fair_home_margin"] == pytest.approx(-2.5)


def test_total_must_be_positive():
    with pytest.raises(MarketContextPropError, match="POSITIVE_REQUIRED"):
        run_market_context_props(
            game_id="G1",
            home_team="HOME",
            away_team="AWAY",
            home_spread=-3.0,
            game_total=0,
            home_model=team("H"),
            away_model=team("A"),
            as_of=AS_OF,
        )
