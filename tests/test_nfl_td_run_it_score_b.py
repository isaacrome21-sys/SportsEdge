import pytest

from sportsedge.nfl_td_run_it_score_b import NflTdBoardError, run_td_board
from sportsedge.truth_gate import american_to_decimal

BOOKS = ("draftkings", "fanduel", "betmgm")


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


def pair_quotes(
    player: str,
    yes: int = 150,
    no: int = -180,
    books: tuple[str, ...] = BOOKS,
) -> list[dict]:
    rows = []
    for book in books:
        rows.append(
            {
                "game_id": "g",
                "player": player,
                "selection": "YES",
                "book": book,
                "price_american": yes,
                "retrieved_at": "2026-09-23T12:00:00Z",
            }
        )
        rows.append(
            {
                "game_id": "g",
                "player": player,
                "selection": "NO",
                "book": book,
                "price_american": no,
                "retrieved_at": "2026-09-23T12:00:00Z",
            }
        )
    return rows


def test_td_board_score_is_not_ev_and_rank_is_economics() -> None:
    estimates = [
        {"game_id": "g", "player": "RB One", "estimate_p": 0.50},
        {"game_id": "g", "player": "WR Two", "estimate_p": 0.40},
    ]
    quotes = pair_quotes("RB One", 150, -180) + pair_quotes("WR Two", 200, -240)
    rows = run_td_board(
        estimates=estimates,
        quotes=quotes,
        qualification_snapshots=[snap("RB One"), snap("WR Two")],
        as_of="2026-09-23T12:00:30Z",
    )
    ok = [r for r in rows if r.status == "OK"]
    assert [r.player for r in ok] == ["RB One", "WR Two"]
    assert ok[0].book == "draftkings"
    assert ok[0].score_0_100 == ok[1].score_0_100 == 100
    assert ok[0].ev_per_dollar != ok[1].ev_per_dollar
    assert len(ok[0].books_used) == 3


def test_td_estimate_rejects_nested_market_inputs() -> None:
    with pytest.raises(NflTdBoardError, match="MARKET_INPUT_FORBIDDEN"):
        run_td_board(
            estimates=[
                {
                    "game_id": "g",
                    "player": "RB One",
                    "estimate_p": 0.5,
                    "meta": {"implied_total": 0.4},
                }
            ],
            quotes=[],
            qualification_snapshots=[],
            as_of="2026-09-23T12:00:00Z",
        )


def test_insufficient_books_blocks_row_not_board() -> None:
    estimates = [
        {"game_id": "g", "player": "RB One", "estimate_p": 0.50},
        {"game_id": "g", "player": "WR Two", "estimate_p": 0.40},
    ]
    quotes = pair_quotes("RB One") + pair_quotes("WR Two", books=("draftkings",))
    rows = run_td_board(
        estimates=estimates,
        quotes=quotes,
        qualification_snapshots=[snap("RB One"), snap("WR Two")],
        as_of="2026-09-23T12:00:30Z",
    )
    by_player = {r.player: r for r in rows}
    assert by_player["RB One"].status == "OK"
    assert by_player["WR Two"].status == "BLOCKED"
    assert by_player["WR Two"].block_reason == "BLOCKED_INSUFFICIENT_BOOKS"


def test_missing_qualification_blocks_only_that_row() -> None:
    estimates = [
        {"game_id": "g", "player": "RB One", "estimate_p": 0.50},
        {"game_id": "g", "player": "WR Two", "estimate_p": 0.40},
    ]
    quotes = pair_quotes("RB One") + pair_quotes("WR Two")
    rows = run_td_board(
        estimates=estimates,
        quotes=quotes,
        qualification_snapshots=[snap("RB One")],
        as_of="2026-09-23T12:00:30Z",
    )
    by_player = {r.player: r for r in rows}
    assert by_player["RB One"].status == "OK"
    assert by_player["WR Two"].block_reason == "BLOCKED_MISSING_QUALIFICATION"


def test_executable_price_is_declared_book_not_median() -> None:
    # DK +110, FD +120, MGM +130 → median would be +120; executable must be DK +110
    quotes = []
    for book, yes, no in (
        ("draftkings", 110, -130),
        ("fanduel", 120, -140),
        ("betmgm", 130, -150),
    ):
        quotes.extend(pair_quotes("RB One", yes=yes, no=no, books=(book,)))
    row = run_td_board(
        estimates=[{"game_id": "g", "player": "RB One", "estimate_p": 0.5}],
        quotes=quotes,
        qualification_snapshots=[snap("RB One")],
        as_of="2026-09-23T12:00:30Z",
    )[0]
    assert row.status == "OK"
    assert row.book == "draftkings"
    assert row.price_american == 110
    assert row.price_american != 120  # not median
    # EV must be computed on executable price 110, not median 120
    expected_ev = 0.5 * (american_to_decimal(110) - 1) - 0.5
    assert abs(row.ev_per_dollar - expected_ev) < 1e-12
    # Benchmark still uses all 3 books
    assert len(row.books_used) == 3


def test_executable_book_missing_blocks_row() -> None:
    # 3 books but none is draftkings
    quotes = pair_quotes("RB One", books=("fanduel", "betmgm", "caesars"))
    row = run_td_board(
        estimates=[{"game_id": "g", "player": "RB One", "estimate_p": 0.5}],
        quotes=quotes,
        qualification_snapshots=[snap("RB One")],
        as_of="2026-09-23T12:00:30Z",
    )[0]
    assert row.status == "BLOCKED"
    assert row.block_reason == "BLOCKED_EXECUTABLE_BOOK_MISSING"
