"""CBB adapter for the shared lines-intake parser + the CBB intake wrapper.

Covers: adapter registration and canonical names; a representative
[CBB LINES] body (ML / Spread / Total / both TeamTotals) parsing into
the parser-output shape the CBB forward runners consume; comment
event ids carried onto the capture while comment-carried extras stay
ignored; strict failure on an unrecognized priced line; the Illinois
exclusion applied at intake from fixture-supplied identity, reusing
the capture-scope module's denylist.
"""
from __future__ import annotations

import pytest

from sportsedge.cbb_capture_scope import (
    _ILLINOIS_ESPN_MBB_2027_DENYLIST as DENYLIST,
)
from sportsedge.cbb_lines_intake import (
    CbbLinesIntakeError,
    parse_cbb_lines,
)
from sportsedge.pipeline.adapters import ADAPTERS, adapter_for
from sportsedge.pipeline.intake import SharedIntakeError, parse_issue

CAPTURED = "2026-11-01T07:26:00-06:00"
AWAY = "Notre Dame Fighting Irish"
HOME = "Villanova Wildcats"
TITLE = f"[CBB LINES] {AWAY} @ {HOME}"

BODY = f"""{AWAY} @ {HOME}
Captured: {CAPTURED}
<!-- DK event: 33221100; ESPN event: 401920982; probables: n/a; quarters Q1 Total 35.5 -110 -110; SGP: player combos -->
ML +110 -130
Spread +2.5 -110 -110
Total 141.5 -110 -110
TeamTotal {AWAY} 69.5 -110 -110
TeamTotal {HOME} 72.5 -115 -105
"""

FIXTURES = {f"{AWAY}@{HOME}": {
    "espn_event_id": "401920982", "away_espn_id": "87",
    "home_espn_id": "222", "neutral_site": True,
    "tip_utc": "2026-11-01T14:30:00Z", "slate_date": "2026-11-01",
    "institution_state_away": "IN", "institution_state_home": "PA"}}


def test_adapter_registered_with_runner_canonical_names():
    adapter = adapter_for("CBB")
    assert ADAPTERS["CBB"] is adapter
    assert adapter.market("ML").market == "MONEYLINE"
    assert adapter.market("Spread").market == "SPREAD"
    assert adapter.market("Total").market == "TOTAL"
    team_total = adapter.market("TeamTotal")
    assert team_total.market == "TEAM_TOTAL"
    assert team_total.family == "team_total" and team_total.subject == "team"


def test_representative_body_parses_all_four_markets():
    capture = parse_cbb_lines(BODY, title=TITLE)
    assert capture.sport == "CBB"
    # Lane grammar puts the header on line 1 and Captured on line 2, so
    # the instant is the game's own capture (board_captured_at stays
    # None; the runners fall back game-first, exactly as designed).
    assert capture.board_captured_at is None
    assert len(capture.games) == 1
    game = capture.games[0]
    assert (game.away, game.home) == (AWAY, HOME)
    assert game.captured_at == CAPTURED
    by_market = [(m.market, m.line, m.price_a, m.price_b, m.team)
                 for m in game.markets]
    assert by_market == [
        ("MONEYLINE", None, 110, -130, None),
        ("SPREAD", 2.5, -110, -110, None),
        ("TOTAL", 141.5, -110, -110, None),
        ("TEAM_TOTAL", 69.5, -110, -110, AWAY),
        ("TEAM_TOTAL", 72.5, -115, -105, HOME),
    ]


def test_comment_event_ids_carried_and_comment_extras_ignored():
    game = parse_cbb_lines(BODY, title=TITLE).games[0]
    assert game.espn_event_id == "401920982"
    assert game.dk_event_id == "33221100"
    # The priced-looking quarter line lives inside the comment: the
    # parser strips comments, so it produces no market and no error.
    assert [m.market for m in game.markets] == [
        "MONEYLINE", "SPREAD", "TOTAL", "TEAM_TOTAL", "TEAM_TOTAL"]


def test_board_dict_matches_runner_consumed_shape():
    board = parse_cbb_lines(BODY, title=TITLE).to_board_dict()
    assert board["sport"] == "CBB"
    entry = board["games"][0]
    # Exactly the keys games_from_board reads, plus the additive ids.
    for key in ("away", "home", "header", "captured_at", "markets"):
        assert key in entry
    assert entry["espn_event_id"] == "401920982"
    spread = [m for m in entry["markets"] if m["market"] == "SPREAD"][0]
    assert (spread["line"], spread["price_a"], spread["price_b"]) == (
        2.5, -110, -110)
    totals = [m for m in entry["markets"] if m["market"] == "TEAM_TOTAL"]
    assert {m["team"] for m in totals} == {AWAY, HOME}


def test_strict_unknown_priced_line_fails_the_game():
    with pytest.raises(CbbLinesIntakeError, match="CBB_INTAKE_UNRECOGNIZED"):
        parse_cbb_lines(BODY + "1H Total 70.5 -110 -110\n", title=TITLE)
    with pytest.raises(CbbLinesIntakeError, match="CBB_INTAKE_UNRECOGNIZED"):
        parse_cbb_lines(BODY + "Player Points 18.5 -110 -110\n", title=TITLE)


def test_default_parse_issue_keeps_owner_default_skip_with_warning():
    # The wrapper is strict; the shared parser's own default for every
    # sport (skip-with-warning) is unchanged by registering CBB.
    board = parse_issue(BODY + "1H Total 70.5 -110 -110\n", "CBB", title=TITLE)
    assert len(board.games[0].markets) == 5
    assert any("SKIPPED_UNKNOWN" in w for w in board.warnings)


def test_one_sided_and_subject_failures_stay_fail_closed():
    with pytest.raises(CbbLinesIntakeError, match="ONE_SIDED_OR_MALFORMED"):
        parse_cbb_lines(BODY.replace("ML +110 -130", "ML +110"), title=TITLE)
    with pytest.raises(CbbLinesIntakeError, match="TEAM_NOT_IN_GAME"):
        parse_cbb_lines(
            BODY + "TeamTotal Duke Blue Devils 80.5 -110 -110\n", title=TITLE)


def test_no_fixture_stamps_unverified_but_keeps_comment_identity():
    game = parse_cbb_lines(BODY, title=TITLE).games[0]
    assert game.identity_state == "UNVERIFIED"
    assert game.espn_event_id == "401920982"


def test_clean_fixture_marks_identity_supplied():
    game = parse_cbb_lines(BODY, title=TITLE, fixtures=FIXTURES).games[0]
    assert game.identity_state == "FIXTURE_SUPPLIED"


def test_fixture_comment_event_id_mismatch_refuses():
    fixtures = {key: dict(value, espn_event_id="401920999")
                for key, value in FIXTURES.items()}
    with pytest.raises(CbbLinesIntakeError, match="EVENT_ID_MISMATCH"):
        parse_cbb_lines(BODY, title=TITLE, fixtures=fixtures)


def test_conflicting_comment_event_ids_refuse():
    body = BODY.replace(
        "<!-- DK event: 33221100;",
        "<!-- ESPN event: 401920983 -->\n<!-- DK event: 33221100;")
    with pytest.raises(CbbLinesIntakeError, match="EVENT_ID_CONFLICT"):
        parse_cbb_lines(body, title=TITLE)


def _illinois_body_and_fixtures(**fixture_overrides):
    away, home = "Example State Redbirds", "Duke Blue Devils"
    body = (f"{away} @ {home}\nCaptured: {CAPTURED}\n"
            f"<!-- DK event: 33221101; ESPN event: 401920984 -->\n"
            "ML +145 -165\nSpread +3.5 -110 -110\nTotal 138.5 -110 -110\n"
            f"TeamTotal {away} 66.5 -110 -110\n"
            f"TeamTotal {home} 71.5 -110 -110\n")
    fixture = {"espn_event_id": "401920984", "away_espn_id": "150",
               "home_espn_id": "2305", "neutral_site": False,
               "tip_utc": "2026-11-02T00:00:00Z", "slate_date": "2026-11-01",
               "institution_state_away": "IN",
               "institution_state_home": "NC"}
    fixture.update(fixture_overrides)
    return body, {f"{away}@{home}": fixture}


def test_illinois_excluded_by_denylist_id():
    denied = sorted(DENYLIST)[0]
    body, fixtures = _illinois_body_and_fixtures(away_espn_id=denied)
    with pytest.raises(CbbLinesIntakeError, match="ILLINOIS_COLLEGE_EXCLUDED"):
        parse_cbb_lines(body, fixtures=fixtures)


def test_illinois_excluded_by_institution_state():
    assert "999999" not in DENYLIST
    body, fixtures = _illinois_body_and_fixtures(
        home_espn_id="999999", institution_state_home="IL")
    with pytest.raises(CbbLinesIntakeError, match="ILLINOIS_COLLEGE_EXCLUDED"):
        parse_cbb_lines(body, fixtures=fixtures)


def test_illinois_excluded_by_crosswalk_flag():
    body, fixtures = _illinois_body_and_fixtures(
        capture_excluded_illinois_away=True)
    with pytest.raises(CbbLinesIntakeError, match="ILLINOIS_COLLEGE_EXCLUDED"):
        parse_cbb_lines(body, fixtures=fixtures)


def test_non_illinois_fixture_passes():
    body, fixtures = _illinois_body_and_fixtures()
    game = parse_cbb_lines(body, fixtures=fixtures).games[0]
    assert game.identity_state == "FIXTURE_SUPPLIED"
    assert game.espn_event_id == "401920984"


def test_title_fallback_game_gets_pre_header_comment_ids():
    body = (f"Captured: {CAPTURED}\n"
            "<!-- DK event: 33221100; ESPN event: 401920982 -->\n"
            "ML +110 -130\nSpread +2.5 -110 -110\nTotal 141.5 -110 -110\n")
    game = parse_cbb_lines(body, title=TITLE).games[0]
    assert (game.away, game.home) == (AWAY, HOME)
    assert game.espn_event_id == "401920982"


def test_two_game_body_keeps_event_ids_on_their_own_games():
    second = ("Kansas Jayhawks @ Duke Blue Devils\n"
              f"Captured: {CAPTURED}\n"
              "<!-- DK event: 33221102; ESPN event: 401920985 -->\n"
              "ML -120 +100\nSpread -1.5 -110 -110\nTotal 150.5 -110 -110\n")
    capture = parse_cbb_lines(BODY + second, title=TITLE)
    assert [g.espn_event_id for g in capture.games] == [
        "401920982", "401920985"]
    assert [g.dk_event_id for g in capture.games] == ["33221100", "33221102"]


def test_shared_parser_error_surfaces_with_sport_prefix():
    with pytest.raises(SharedIntakeError, match="CBB_INTAKE_NO_GAMES"):
        parse_issue("no games here\n", "CBB")
    with pytest.raises(CbbLinesIntakeError, match="CBB_INTAKE_NO_GAMES"):
        parse_cbb_lines("no games here\n")
