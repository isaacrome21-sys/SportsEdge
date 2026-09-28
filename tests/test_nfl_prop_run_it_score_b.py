import pytest

from sportsedge.nfl_prop_run_it_score_b import PROP_FAMILIES, NflPropBoardError, run_prop_board
from sportsedge.truth_gate import american_to_decimal

BOOKS = ("draftkings", "fanduel", "betmgm")


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


def quotes(
    market: str,
    line: float,
    over: int = 120,
    under: int = -140,
    books: tuple[str, ...] = BOOKS,
    player: str = "P",
) -> list[dict]:
    rows = []
    for book in books:
        rows.append(
            {
                "game_id": "g",
                "player": player,
                "market": market,
                "selection": "OVER",
                "line": line,
                "book": book,
                "price_american": over,
                "retrieved_at": "2026-09-23T12:00:00Z",
            }
        )
        rows.append(
            {
                "game_id": "g",
                "player": player,
                "market": market,
                "selection": "UNDER",
                "line": line,
                "book": book,
                "price_american": under,
                "retrieved_at": "2026-09-23T12:00:00Z",
            }
        )
    return rows


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
    assert row.status == "OK"
    assert row.book == "draftkings"
    assert row.market == market
    assert row.score_0_100 == 100
    assert len(row.books_used) == 3


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


def test_estimate_rejects_nested_sportsbook_keys() -> None:
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
                    "diag": {"no_vig_hint": 0.55},
                }
            ],
            quotes=[],
            qualification_snapshots=[],
            as_of="2026-09-23T12:00:00Z",
        )


def test_line_disagreement_blocks_hygiene() -> None:
    q = quotes("receptions", 4.5, books=("draftkings",))
    q += quotes("receptions", 5.5, books=("fanduel",))
    q += quotes("receptions", 4.5, books=("betmgm",))
    rows = run_prop_board(
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
        quotes=q,
        qualification_snapshots=[snap("receptions")],
        as_of="2026-09-23T12:00:30Z",
    )
    assert rows[0].status == "BLOCKED"
    assert rows[0].block_reason == "BLOCKED_QUOTE_HYGIENE"


def test_insufficient_books_blocks_row_not_board() -> None:
    estimates = [
        {
            "game_id": "g",
            "player": "P",
            "market": "receptions",
            "selection": "OVER",
            "line": 4.5,
            "estimate_p": 0.6,
        },
        {
            "game_id": "g",
            "player": "Q",
            "market": "receptions",
            "selection": "OVER",
            "line": 3.5,
            "estimate_p": 0.55,
        },
    ]
    q = quotes("receptions", 4.5, player="P") + quotes(
        "receptions", 3.5, player="Q", books=("draftkings",)
    )
    rows = run_prop_board(
        estimates=estimates,
        quotes=q,
        qualification_snapshots=[snap("receptions", "P"), snap("receptions", "Q")],
        as_of="2026-09-23T12:00:30Z",
    )
    by_player = {r.player: r for r in rows}
    assert by_player["P"].status == "OK"
    assert by_player["Q"].status == "BLOCKED"
    assert by_player["Q"].block_reason == "BLOCKED_INSUFFICIENT_BOOKS"


def test_executable_price_is_declared_book_not_median() -> None:
    q = []
    for book, over, under in (
        ("draftkings", 110, -130),
        ("fanduel", 120, -140),
        ("betmgm", 130, -150),
    ):
        q.extend(quotes("receptions", 4.5, over=over, under=under, books=(book,)))
    row = run_prop_board(
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
        quotes=q,
        qualification_snapshots=[snap("receptions")],
        as_of="2026-09-23T12:00:30Z",
    )[0]
    assert row.status == "OK"
    assert row.book == "draftkings"
    assert row.price_american == 110
    assert row.price_american != 120
    expected_ev = 0.6 * (american_to_decimal(110) - 1) - 0.4
    assert abs(row.ev_per_dollar - expected_ev) < 1e-12
    assert len(row.books_used) == 3


def test_executable_book_missing_blocks_row() -> None:
    q = quotes("receptions", 4.5, books=("fanduel", "betmgm", "caesars"))
    row = run_prop_board(
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
        quotes=q,
        qualification_snapshots=[snap("receptions")],
        as_of="2026-09-23T12:00:30Z",
    )[0]
    assert row.status == "BLOCKED"
    assert row.block_reason == "BLOCKED_EXECUTABLE_BOOK_MISSING"


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
    assert row.status == "OK"
    assert row.push_p == 0.2
    assert row.book == "draftkings"
    assert row.fair_american != 0
