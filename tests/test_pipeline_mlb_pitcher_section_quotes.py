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


def test_real_compound_team_totals_preserve_both_quoted_prices_and_team_identity() -> None:
    body = PREFIX + "Team Totals: MIL 3.5 +100 -130; TB 3.5 -105 -125"
    game = parse_issue(body, "MLB").games[0]
    assert len(game.markets) == 2
    assert [(m.market, m.family, m.subject, m.team, m.line, m.price_a, m.price_b)
            for m in game.markets] == [
        ("TEAM_TOTAL", "team_total", "MIL", "MIL Brewers", 3.5, 100, -130),
        ("TEAM_TOTAL", "team_total", "TB", "TB Rays", 3.5, -105, -125),
    ]
    assert all(m.raw == "Team Totals: MIL 3.5 +100 -130; TB 3.5 -105 -125"
               for m in game.markets)


@pytest.mark.parametrize("line,error", [
    ("Team Totals: MIL 3.5 +100 -130", "TEAM_TOTAL_PAIR_INVALID"),
    ("Team Totals: MIL 3.5 +100 -130; TB 3.5 -105", "ONE_SIDED_OR_MALFORMED"),
    ("Team Totals: MIL 3.5 +100 -130; MIL 3.5 -105 -125", "TEAM_TOTAL_TEAMS_MISMATCH"),
    ("Team Totals: MIL 3.5 +100 -130; NY 3.5 -105 -125", "TEAM_NOT_IN_GAME"),
])
def test_compound_team_totals_refuse_incomplete_or_misbound_teams(line, error) -> None:
    with pytest.raises(SharedIntakeError, match=error):
        parse_issue(PREFIX + line, "MLB")


def test_real_mlb_alt_lines_and_first_inning_pair_preserve_both_prices() -> None:
    game = parse_issue(PREFIX + (
        "Alt Total 3.5 -690 +425\n"
        "Alt Total 11.5 +495 -860\n"
        "Alt RL -4.5 +620 / +4.5 -1260\n"
        "Alt RL +1.5 -234 / -1.5 +175\n"
        "YRFI +100 / NRFI -130\n"
    ), "MLB").games[0]
    assert [(m.market, m.line, m.price_a, m.price_b, m.side_a, m.side_b)
            for m in game.markets] == [
        ("GAME_TOTAL", 3.5, -690, 425, "OVER", "UNDER"),
        ("GAME_TOTAL", 11.5, 495, -860, "OVER", "UNDER"),
        ("RUN_LINE", -4.5, 620, -1260, "AWAY", "HOME"),
        ("RUN_LINE", 1.5, -234, 175, "AWAY", "HOME"),
        ("FIRST_INNING_TOTAL", 0.5, 100, -130, "OVER", "UNDER"),
    ]


def test_first_inning_pair_handles_reverse_label_order_without_swapping_prices() -> None:
    game = parse_issue(PREFIX + "NRFI -130 / YRFI +100", "MLB").games[0]
    assert len(game.markets) == 1
    assert (game.markets[0].price_a, game.markets[0].price_b) == (100, -130)


@pytest.mark.parametrize("line", [
    "YRFI +100 / NRFI",
    "YRFI +100 / YRFI -130",
    "NRFI -130 / NRFI +100",
    "YRFI +100 / NRFI nan",
    "YRFI +100 / NRFI -50",
])
def test_first_inning_pair_refuses_missing_duplicate_and_invalid_quotes(line) -> None:
    with pytest.raises(SharedIntakeError, match="PAIR_INVALID|ODDS_INVALID"):
        parse_issue(PREFIX + line, "MLB")


def test_actual_mlb_game_market_inventory_prices_only_complete_binary_quotes() -> None:
    # The quoted main, alternate, first-five, pitcher and two team-total rows
    # from #2685. The HR and hit milestones have no quoted NO price.
    body = PREFIX + "\n".join([
        "ML -105 -115",
        "RL -1.5 +170 / +1.5 -208",
        "Total 7 -110 -109",
        *[f"Alt Total {point} {a} {b}" for point, a, b in [
            (3.5, -690, 425), (4, -630, 394), (4.5, -407, 282),
            (5, -334, 239), (5.5, -208, 157), (6, -180, 137),
            (6.5, -145, 111), (7.5, 117, -153), (8, 142, -186),
            (8.5, 159, -212), (9, 216, -297), (9.5, 246, -345),
            (10, 310, -457), (10.5, 332, -497), (11, 465, -790),
            (11.5, 495, -860),
        ]],
        "Alt RL -4.5 +620 / +4.5 -1260",
        "Alt RL -2.5 +274 / +2.5 -391",
        "Alt RL -1 +136 / +1 -178",
        "Alt RL +1 -165 / -1 +126",
        "Alt RL +1.5 -234 / -1.5 +175",
        "Alt RL +5 -2500 / -5 +870",
        "Team Totals: MIL 3.5 +100 -130; TB 3.5 -105 -125",
        "F5 ML -105 -125",
        "F5 RL -0.5 +135 / +0.5 -175",
        "F5 Total 3.5 -140 +110",
        "YRFI +100 / NRFI -130",
        FREDDY.rstrip("\n"),
        ROBERT.rstrip("\n"),
        "Batter HR 1+: Junior Caminero +350; Jake Bauers +455",
        "Batter HR 2+: Junior Caminero +3300; Jake Bauers +5500",
        "Batter Hits (1+ / 2+ / 3+): Jackson Chourio -246/+219/+980; Yandy Diaz -256/+216/+1000",
    ])
    parsed = parse_issue(body, "MLB")
    assert len(parsed.games) == 1
    assert len(parsed.games[0].markets) == 41
    assert sum(m.market == "GAME_TOTAL" for m in parsed.games[0].markets) == 17
    assert sum(m.market == "RUN_LINE" for m in parsed.games[0].markets) == 7
    assert sum(m.market.startswith("PITCHER_") for m in parsed.games[0].markets) == 10
    assert sum(m.market == "TEAM_TOTAL" for m in parsed.games[0].markets) == 2
    assert any("SKIPPED_UNPAIRED_OFFER" in warning for warning in parsed.warnings)
    assert not any(m.market.startswith("BATTER_") for m in parsed.games[0].markets)
