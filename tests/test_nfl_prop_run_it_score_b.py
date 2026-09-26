import pytest

from sportsedge.nfl_prop_run_it_score_b import PROP_FAMILIES, NflPropBoardError, run_prop_board


def snap(market: str, player: str = "P") -> dict:
    return {
        "game_id": "g",
        "market": market,
        "selection": player,
        "captured_at": "2026-09-23T12:00:00Z",
        "kickoff_at": "2026-09-24T00:00:00Z",
        "source_version": "v1",
        "feature_digest": "abc",
        "model_ready": True,
        "pit_safe": True,
        "role_stable": True,
        "usage_supported": True,
        "matchup_supported": True,
        "injury_context_ready": True,
        "shared_simulation_ready": True,
        "market_binding_ready": True,
    }


def quotes(market: str, line: float, over: int = 120, under: int = -140) -> list[dict]:
    return [
        {
            "game_id": "g",
            "player": "P",
            "market": market,
            "selection": "OVER",
            "line": line,
            "book": "draftkings",
            "price_american": over,
            "retrieved_at": "2026-09-23T12:00:00Z",
        },
        {
            "game_id": "g",
            "player": "P",
            "market": market,
            "selection": "UNDER",
            "line": line,
            "book": "draftkings",
            "price_american": under,
            "retrieved_at": "2026-09-23T12:00:00Z",
        },
    ]


@pytest.mark.parametrize("market", sorted(PROP_FAMILIES))
def test_all_supported_prop_families_price_and_score(market: str) -> None:
    row = run_prop_board(
        estimates=[
            {
                "game_id": "g",
                "player": "P",
                "market": market,
                "selection": "OVER",
                "line": 50.5,
                "estimate_p": 0.6,
            }
        ],
        quotes=quotes(market, 50.5),
        qualification_snapshots=[snap(market)],
        as_of="2026-09-23T12:00:30Z",
    )[0]
    assert row.market == market
    assert row.score_0_100 == 100
    assert row.estimate_p == 0.6


def test_score_does_not_derive_from_market_economics() -> None:
    a = run_prop_board(
        estimates=[
            {
                "game_id": "g",
                "player": "P",
                "market": "receptions",
                "selection": "OVER",
                "line": 4.5,
                "estimate_p": 0.6,
            }
        ],
        quotes=quotes("receptions", 4.5, 120, -140),
        qualification_snapshots=[snap("receptions")],
        as_of="2026-09-23T12:00:30Z",
    )[0]
    b = run_prop_board(
        estimates=[
            {
                "game_id": "g",
                "player": "P",
                "market": "receptions",
                "selection": "OVER",
                "line": 4.5,
                "estimate_p": 0.7,
            }
        ],
        quotes=quotes("receptions", 4.5, 150, -180),
        qualification_snapshots=[snap("receptions")],
        as_of="2026-09-23T12:00:30Z",
    )[0]
    assert a.score_0_100 == b.score_0_100 == 100
    assert a.ev_per_dollar != b.ev_per_dollar


def test_estimate_rejects_sportsbook_price_input() -> None:
    with pytest.raises(NflPropBoardError, match="MARKET_INPUT_FORBIDDEN"):
        run_prop_board(
            estimates=[
                {
                    "game_id": "g",
                    "player": "P",
                    "market": "receptions",
                    "selection": "OVER",
                    "line": 4.5,
                    "estimate_p": 0.6,
                    "price_american": 120,
                }
            ],
            quotes=[],
            qualification_snapshots=[],
            as_of="2026-09-23T12:00:00Z",
        )


def test_integer_line_push_is_conditioned_for_edge_and_ev() -> None:
    row = run_prop_board(
        estimates=[
            {
                "game_id": "g",
                "player": "P",
                "market": "pass_tds",
                "selection": "OVER",
                "line": 2,
                "estimate_p": 0.45,
                "push_p": 0.2,
            }
        ],
        quotes=quotes("pass_tds", 2, 130, -150),
        qualification_snapshots=[snap("pass_tds")],
        as_of="2026-09-23T12:00:30Z",
    )[0]
    assert row.push_p == 0.2
    assert row.fair_american != 0
