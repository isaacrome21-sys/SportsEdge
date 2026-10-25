"""MLB player headings bind only genuinely paired pitcher quote rows."""

from __future__ import annotations

import pytest

from sportsedge.pipeline.intake import SharedIntakeError, parse_issue


PREFIX = "MIL Brewers @ TB Rays\nCaptured: 2026-10-25T12:16:08-05:00\n"
FREDDY = (
    "Pitcher props — Freddy Peralta (TB):\n"
    "K 4.5 -132 +104\n"
    "Outs 15.5 +114 -152\n"
    "Hits Allowed 4.5 +114 -152\n"
    "ER Allowed 1.5 -127 -104\n"
    "Walks Allowed 1.5 -195 +146\n"
)
ROBERT = (
    "Pitcher props — Robert Gasser (MIL):\n"
    "K 3.5 -101 -127\n"
    "Outs 12.5 +108 -143\n"
    "Hits Allowed 3.5 -132 -101\n"
    "ER Allowed 1.5 +116 -154\n"
    "Walks Allowed 1.5 +173 -234\n"
)


def test_real_two_pitcher_board_preserves_all_ten_paired_quotes() -> None:
    body = PREFIX + "ML -105 -115\n" + FREDDY + ROBERT
    board = parse_issue(body, "MLB", resolve_teams=False)
    assert board.warnings == []
    assert len(board.games[0].markets) == 11
    pitcher = board.games[0].markets[1:]
    assert [r.market for r in pitcher] == [
        "PITCHER_STRIKEOUTS", "PITCHER_OUTS", "PITCHER_HITS_ALLOWED",
        "PITCHER_ER", "PITCHER_BB",
    ] * 2
    assert [r.subject for r in pitcher] == ["Freddy Peralta"] * 5 + ["Robert Gasser"] * 5
    assert [(r.line, r.price_a, r.price_b) for r in pitcher] == [
        (4.5, -132, 104), (15.5, 114, -152), (4.5, 114, -152),
        (1.5, -127, -104), (1.5, -195, 146),
        (3.5, -101, -127), (12.5, 108, -143), (3.5, -132, -101),
        (1.5, 116, -154), (1.5, 173, -234),
    ]


@pytest.mark.parametrize("body,error", [
    (PREFIX + "K 4.5 -132 +104", "SUBJECT_MISSING"),
    (PREFIX + "Pitcher props — :\nK 4.5 -132 +104", "PITCHER_SECTION_INVALID"),
    (PREFIX + "Pitcher props — Freddy Peralta (TB):\nK 4.5 -132", "ONE_SIDED_OR_MALFORMED"),
    (PREFIX + FREDDY + "Batter HR 1+: Junior Caminero +350\nK 1.5 -110 -110", "SUBJECT_MISSING"),
    (PREFIX + FREDDY + "Hits 1.5 -110 -110", "SUBJECT_MISSING"),
])
def test_paired_section_refuses_missing_identity_bad_price_and_batter_leak(body, error) -> None:
    with pytest.raises(SharedIntakeError, match=error):
        parse_issue(body, "MLB", resolve_teams=False)


def test_pitcher_context_never_leaks_to_second_game() -> None:
    body = PREFIX + FREDDY + "\nChicago Cubs @ San Diego Padres\nK 4.5 -110 -110"
    with pytest.raises(SharedIntakeError, match="SUBJECT_MISSING"):
        parse_issue(body, "MLB", resolve_teams=False)


def test_unknown_pitcher_market_stays_warning_only_not_invented_quote() -> None:
    body = PREFIX + FREDDY + "Pitcher Win +185 -230"
    board = parse_issue(body, "MLB", resolve_teams=False)
    assert len(board.games[0].markets) == 5
    assert any("SKIPPED_UNKNOWN" in warning and "Pitcher Win" in warning
               for warning in board.warnings)


def test_one_sided_hr_offer_is_explicitly_skipped_without_poisoning_paired_rows() -> None:
    body = (PREFIX + "Batter HR 1+: Junior Caminero +350\n"
            "Pitcher props — Freddy Peralta (TB):\nK 4.5 -132 +104")
    board = parse_issue(body, "MLB", resolve_teams=False)
    assert len(board.games[0].markets) == 1
    assert board.games[0].markets[0].subject == "Freddy Peralta"
    assert any("SKIPPED_UNPAIRED_OFFER" in warning and "Junior Caminero" in warning
               for warning in board.warnings)
    # Strict ingestion can still reject an unpaired offer wholesale.
    with pytest.raises(SharedIntakeError, match="ONE_SIDED_OR_MALFORMED"):
        parse_issue(body, "MLB", resolve_teams=False, strict_unknown=True)


def test_known_one_sided_moneyline_still_refuses_whole_board() -> None:
    with pytest.raises(SharedIntakeError, match="ONE_SIDED_OR_MALFORMED"):
        parse_issue(PREFIX + "ML +125", "MLB", resolve_teams=False)
