from sportsedge.nfl_td_run_it_score_b import NflTdBoardError, run_td_board


def snap(player: str = "RB One", score: bool = True) -> dict:
    return {
        "game_id": "g",
        "market": "anytime_td",
        "selection": player,
        "captured_at": "2026-09-23T12:00:00Z",
        "kickoff_at": "2026-09-24T00:00:00Z",
        "source_version": "v1",
        "feature_digest": "abc",
        "model_ready": score,
        "pit_safe": score,
        "role_stable": score,
        "usage_supported": score,
        "matchup_supported": score,
        "injury_context_ready": score,
        "shared_simulation_ready": score,
        "market_binding_ready": score,
    }


def test_td_board_score_is_not_ev_and_rank_is_economics() -> None:
    estimates = [
        {"game_id": "g", "player": "RB One", "estimate_p": 0.50},
        {"game_id": "g", "player": "WR Two", "estimate_p": 0.40},
    ]
    quotes = [
        {
            "game_id": "g",
            "player": "RB One",
            "selection": "YES",
            "book": "draftkings",
            "price_american": 150,
            "retrieved_at": "2026-09-23T12:00:00Z",
        },
        {
            "game_id": "g",
            "player": "RB One",
            "selection": "NO",
            "book": "draftkings",
            "price_american": -180,
            "retrieved_at": "2026-09-23T12:00:00Z",
        },
        {
            "game_id": "g",
            "player": "WR Two",
            "selection": "YES",
            "book": "draftkings",
            "price_american": 200,
            "retrieved_at": "2026-09-23T12:00:00Z",
        },
        {
            "game_id": "g",
            "player": "WR Two",
            "selection": "NO",
            "book": "draftkings",
            "price_american": -240,
            "retrieved_at": "2026-09-23T12:00:00Z",
        },
    ]
    rows = run_td_board(
        estimates=estimates,
        quotes=quotes,
        qualification_snapshots=[snap("RB One"), snap("WR Two")],
        as_of="2026-09-23T12:00:30Z",
    )
    assert [r.player for r in rows] == ["RB One", "WR Two"]
    assert rows[0].score_0_100 == rows[1].score_0_100 == 100
    assert rows[0].ev_per_dollar != rows[1].ev_per_dollar


def test_td_estimate_rejects_market_inputs() -> None:
    import pytest

    with pytest.raises(NflTdBoardError, match="MARKET_INPUT_FORBIDDEN"):
        run_td_board(
            estimates=[{"game_id": "g", "player": "RB One", "estimate_p": 0.5, "price_american": 150}],
            quotes=[],
            qualification_snapshots=[],
            as_of="2026-09-23T12:00:00Z",
        )
