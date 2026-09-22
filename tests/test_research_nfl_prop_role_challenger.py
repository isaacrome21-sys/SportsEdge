from __future__ import annotations

import json

import pytest

from sportsedge.research.nfl_prop_role_challenger import (
    AUTHORITY_FOOTER,
    NFLPropResearchError,
    PROP_FAMILIES,
    build_prop_card,
    evaluate_prop_market,
    price_simulated_prop,
    rank_prop_candidates,
    simulate_player_role,
    stabilize_role_metric,
)


AS_OF = "2026-09-21T18:00:00+00:00"


def _player() -> dict:
    return {
        "game_id": "2026-W3-CHI-DAL",
        "player_id": "player-1",
        "player_name": "Research Player",
        "team": "CHI",
        "opponent": "DAL",
        "position": "QB",
        "sample_size": 8,
        "role_prior": {
            "pass_attempts": 34.0,
            "completion_rate": 0.65,
            "pass_yards_per_completion": 11.5,
            "pass_td_rate": 0.045,
            "interception_rate": 0.025,
            "rush_attempts": 5.0,
            "rush_yards_per_attempt": 4.2,
            "targets": 7.0,
            "catch_rate": 0.68,
            "receiving_yards_per_reception": 10.5,
        },
        "trailing": {
            "pass_attempts": 36.0,
            "completion_rate": 0.67,
            "pass_yards_per_completion": 12.0,
            "pass_td_rate": 0.05,
            "interception_rate": 0.02,
            "rush_attempts": 6.0,
            "rush_yards_per_attempt": 4.5,
            "targets": 8.0,
            "catch_rate": 0.70,
            "receiving_yards_per_reception": 11.0,
        },
        "context": {
            "volume_multiplier": 1.0,
            "pass_multiplier": 1.0,
            "rush_multiplier": 1.0,
            "target_multiplier": 1.0,
            "efficiency_multiplier": 1.0,
            "shared_workload_sigma": 0.12,
        },
    }


def _quote(side: str, odds: int, *, market: str = "completions", line: float = 22.5, at: str = "2026-09-21T17:59:45+00:00") -> dict:
    return {
        "player_id": "player-1",
        "market": market,
        "side": side,
        "line": line,
        "price_american": odds,
        "book": "DraftKings",
        "retrieved_at": at,
    }


def test_all_ten_prop_families_are_priced_from_shared_draws() -> None:
    draws = simulate_player_role(_player(), n_sims=250, seed=7)
    assert set(PROP_FAMILIES) == {
        "receptions",
        "receiving_yards",
        "passing_yards",
        "rushing_yards",
        "rush_attempts",
        "pass_attempts",
        "completions",
        "pass_tds",
        "interceptions",
        "rush_receiving_yards",
    }
    for market in PROP_FAMILIES:
        result = price_simulated_prop(draws, market=market, line=2.0)
        assert result["over"] + result["under"] + result["push"] == pytest.approx(1.0)


def test_unknown_prop_is_rejected() -> None:
    draws = simulate_player_role(_player(), n_sims=10, seed=7)
    with pytest.raises(NFLPropResearchError, match="UNSUPPORTED_PROP"):
        price_simulated_prop(draws, market="first_touchdown", line=0.5)


def test_sparse_sample_stays_near_prior_and_large_sample_moves_to_observed() -> None:
    sparse = stabilize_role_metric(10.0, 20.0, 1, prior_strength=9)
    large = stabilize_role_metric(10.0, 20.0, 90, prior_strength=9)
    assert sparse == pytest.approx(11.0)
    assert large == pytest.approx(19.0909090909)
    assert abs(sparse - 10.0) < abs(sparse - 20.0)
    assert abs(large - 20.0) < abs(large - 10.0)


def test_shared_simulation_is_deterministic_and_coherent() -> None:
    left = simulate_player_role(_player(), n_sims=200, seed=21)
    right = simulate_player_role(_player(), n_sims=200, seed=21)
    assert left == right
    for draw in left:
        assert draw["completions"] <= draw["pass_attempts"]
        assert draw["receptions"] <= draw["targets"]
        assert draw["pass_tds"] <= draw["pass_attempts"]
        assert draw["interceptions"] <= draw["pass_attempts"]
        assert draw["rush_receiving_yards"] == draw["rushing_yards"] + draw["receiving_yards"]
        assert all(value >= 0 and isinstance(value, int) for value in draw.values())


def test_integer_line_preserves_push_mass() -> None:
    draws = [
        {"completions": 20},
        {"completions": 21},
        {"completions": 21},
        {"completions": 22},
    ]
    result = price_simulated_prop(draws, market="completions", line=21)
    assert result == {"over": 0.25, "under": 0.25, "push": 0.5}


def test_half_line_has_zero_push_mass() -> None:
    draws = [{"completions": 20}, {"completions": 21}, {"completions": 22}]
    result = price_simulated_prop(draws, market="completions", line=21.5)
    assert result["push"] == 0.0
    assert result["over"] + result["under"] == pytest.approx(1.0)


def test_one_sided_quote_is_refused() -> None:
    draws = simulate_player_role(_player(), n_sims=100, seed=4)
    with pytest.raises(NFLPropResearchError, match="PAIRED_QUOTES_REQUIRED"):
        evaluate_prop_market(
            draws,
            player_id="player-1",
            player_name="Research Player",
            game_id="g1",
            market="completions",
            line=22.5,
            quotes=[_quote("OVER", -110)],
            as_of=AS_OF,
        )


def test_missing_timestamp_is_refused() -> None:
    over = _quote("OVER", -110)
    over.pop("retrieved_at")
    draws = simulate_player_role(_player(), n_sims=50, seed=4)
    with pytest.raises(NFLPropResearchError, match="retrieved_at:TIMESTAMP_REQUIRED"):
        evaluate_prop_market(
            draws,
            player_id="player-1",
            player_name="Research Player",
            game_id="g1",
            market="completions",
            line=22.5,
            quotes=[over, _quote("UNDER", -110)],
            as_of=AS_OF,
        )


def test_stale_quote_is_refused() -> None:
    draws = simulate_player_role(_player(), n_sims=50, seed=4)
    stale = "2026-09-21T17:56:59+00:00"
    with pytest.raises(NFLPropResearchError, match="QUOTE_STALE"):
        evaluate_prop_market(
            draws,
            player_id="player-1",
            player_name="Research Player",
            game_id="g1",
            market="completions",
            line=22.5,
            quotes=[_quote("OVER", -110, at=stale), _quote("UNDER", -110)],
            as_of=AS_OF,
        )


def test_future_clock_skew_is_refused() -> None:
    draws = simulate_player_role(_player(), n_sims=50, seed=4)
    future = "2026-09-21T18:00:31+00:00"
    with pytest.raises(NFLPropResearchError, match="QUOTE_CLOCK_SKEW"):
        evaluate_prop_market(
            draws,
            player_id="player-1",
            player_name="Research Player",
            game_id="g1",
            market="completions",
            line=22.5,
            quotes=[_quote("OVER", -110, at=future), _quote("UNDER", -110)],
            as_of=AS_OF,
        )


def test_pair_timestamp_skew_is_refused() -> None:
    draws = simulate_player_role(_player(), n_sims=50, seed=4)
    with pytest.raises(NFLPropResearchError, match="PAIRED_QUOTE_TIME_SKEW"):
        evaluate_prop_market(
            draws,
            player_id="player-1",
            player_name="Research Player",
            game_id="g1",
            market="completions",
            line=22.5,
            quotes=[
                _quote("OVER", -110, at="2026-09-21T17:59:55+00:00"),
                _quote("UNDER", -110, at="2026-09-21T17:59:20+00:00"),
            ],
            as_of=AS_OF,
        )


def test_longshot_devig_sensitivity_blocks_unstable_pair() -> None:
    draws = simulate_player_role(_player(), n_sims=100, seed=4)
    with pytest.raises(NFLPropResearchError, match="DEVIG_METHOD_SENSITIVITY"):
        evaluate_prop_market(
            draws,
            player_id="player-1",
            player_name="Research Player",
            game_id="g1",
            market="completions",
            line=22.5,
            quotes=[_quote("OVER", 500), _quote("UNDER", -800)],
            as_of=AS_OF,
        )


def test_valid_pair_outputs_estimate_p_push_ev_and_exact_authority_footer() -> None:
    draws = simulate_player_role(_player(), n_sims=400, seed=4)
    rows = evaluate_prop_market(
        draws,
        player_id="player-1",
        player_name="Research Player",
        game_id="g1",
        market="completions",
        line=22.0,
        quotes=[
            _quote("OVER", -110, line=22.0),
            _quote("UNDER", -110, line=22.0),
        ],
        as_of=AS_OF,
    )
    assert {row["side"] for row in rows} == {"OVER", "UNDER"}
    assert all(row["authority"] == AUTHORITY_FOOTER for row in rows)
    assert all("estimate_p" in row and "push_p" in row and "ev_per_dollar" in row for row in rows)
    text = json.dumps(rows)
    assert "model_p" not in text
    assert '"score"' not in text
    assert '"why"' not in text


def test_rank_is_economics_only() -> None:
    rows = [
        {"game_id": "g", "player_id": "p", "market": "receptions", "side": "OVER", "ev_per_dollar": 0.02, "edge_probability_points": 8.0},
        {"game_id": "g", "player_id": "p", "market": "receptions", "side": "UNDER", "ev_per_dollar": 0.05, "edge_probability_points": 1.0},
    ]
    ranked = rank_prop_candidates(rows)
    assert ranked[0]["side"] == "UNDER"
    assert [row["rank"] for row in ranked] == [1, 2]


def test_card_preserves_non_authority_and_quote_dispositions() -> None:
    card = build_prop_card(
        [_player()],
        [_quote("OVER", -110)],
        as_of=AS_OF,
        n_sims=100,
        seed=11,
    )
    assert card["authority"] == AUTHORITY_FOOTER
    assert card["candidates"] == []
    assert card["dispositions"][0]["reason"] == "PAIRED_QUOTES_REQUIRED"
