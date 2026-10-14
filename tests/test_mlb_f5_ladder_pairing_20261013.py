"""F5 ladder pairing tests (2026-10-13 reviewer ruling). Offline only.

Pairing identity = book + event + gamePk + doubleheader game number +
period + market + entity + side-normalized rung line. Exactly one
opposite pair per key; anything else refuses. F5 stays ineligible.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sportsedge.mlb_f5_quote_binding import (
    F5_FIXTURE_BINDING_MISMATCH, F5_PAIR_SKEW_EXCEEDED, F5_QUOTE_STALE,
    F5_QUOTE_UNPAIRED, F5_SELECTION_UNVERIFIED, bind_f5_quotes,
)

NOW = datetime(2026, 9, 14, 23, 0, tzinfo=timezone.utc)
PK1, PK2 = 777001, 777002


def _fixture(pk, game_number=None):
    fx = {"game_pk": pk, "away_team_id": 101, "home_team_id": 202,
          "away_name": "Away Club", "home_name": "Home Club",
          "first_pitch_at": datetime(2026, 9, 14, 23, 10, tzinfo=timezone.utc),
          "official_date": "2026-09-14"}
    if game_number is not None:
        fx["game_number"] = game_number
    return fx


def _resolver(**kw):
    return _fixture(kw["game_pk"])


def _dh_resolver(**kw):
    return _fixture(kw["game_pk"], 1 if kw["game_pk"] == PK1 else 2)


def _rl(side, line, **over):
    row = {"sport": "MLB", "market": "F5_RUN_LINE", "book": "draftkings",
           "event_id": "DK-EVT-1", "game_pk": PK1, "away": "Away Club",
           "home": "Home Club", "kickoff": "2026-09-14T23:10:00Z",
           "side": side, "line": line, "odds": -110,
           "quote_captured_at": "2026-09-14T22:59:30Z"}
    row.update(over)
    return row


def _status(bound):
    return [r["status"] for r in bound["row_results"]]


def _codes(bound):
    return [r.get("reason_code") for r in bound["row_results"]]


def test_multi_rung_ladder_pairs_each_rung_separately():
    rows = [_rl("HOME", -0.5), _rl("AWAY", 0.5),
            _rl("HOME", -1.5), _rl("AWAY", 1.5),
            _rl("HOME", 0.5), _rl("AWAY", -0.5)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _status(bound) == ["BOUND"] * 6
    assert len(bound["pairs"]) == 3
    assert sorted(p["rung_key"] for p in bound["pairs"]) == [-1.5, -0.5, 0.5]
    for p in bound["pairs"]:
        sides = {q["side"]: q["line"] for q in p["quotes"]}
        assert sides["HOME"] == -sides["AWAY"]


def test_rows_interleaved_still_pair_by_rung():
    rows = [_rl("AWAY", 1.5), _rl("HOME", -0.5), _rl("HOME", -1.5),
            _rl("AWAY", 0.5)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _status(bound) == ["BOUND"] * 4
    for p in bound["pairs"]:
        assert {q["side"] for q in p["quotes"]} == {"HOME", "AWAY"}


def test_unpaired_rung_refuses_while_other_rungs_bind():
    rows = [_rl("HOME", -0.5), _rl("AWAY", 0.5), _rl("HOME", -1.5)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _status(bound) == ["BOUND", "BOUND", "BLOCKED"]
    assert _codes(bound)[2] == F5_QUOTE_UNPAIRED


def test_same_side_opposite_signs_do_not_pair():
    # HOME -1.5 vs AWAY -1.5 are different rungs: neither pairs.
    rows = [_rl("HOME", -1.5), _rl("AWAY", -1.5)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_UNPAIRED] * 2


def test_half_run_total_ladder_pairs_per_line():
    def tot(side, line):
        return _rl(side, line, market="F5_TOTALS")
    rows = [tot("OVER", 4.5), tot("UNDER", 4.5), tot("OVER", 5.0),
            tot("UNDER", 5.0), tot("OVER", 5.5)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _status(bound)[:4] == ["BOUND"] * 4
    assert _codes(bound)[4] == F5_QUOTE_UNPAIRED
    assert sorted(p["rung_key"] for p in bound["pairs"]) == [4.5, 5.0]


def test_three_way_draw_selection_refused():
    rows = [_rl("HOME", 0, market="F5_MONEYLINE"),
            _rl("AWAY", 0, market="F5_MONEYLINE"),
            _rl("DRAW", 0, market="F5_MONEYLINE")]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _status(bound)[:2] == ["BOUND", "BOUND"]
    assert _codes(bound)[2] == F5_SELECTION_UNVERIFIED


def test_doubleheader_games_not_cross_paired():
    rows = [_rl("HOME", -0.5, game_pk=PK1, game_number=1),
            _rl("AWAY", 0.5, game_pk=PK2, game_number=2,
                event_id="DK-EVT-1")]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_dh_resolver)
    assert _codes(bound) == [F5_QUOTE_UNPAIRED] * 2
    rows += [_rl("AWAY", 0.5, game_pk=PK1, game_number=1),
             _rl("HOME", -0.5, game_pk=PK2, game_number=2)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_dh_resolver)
    assert _status(bound) == ["BOUND"] * 4
    assert sorted(p["game_number"] for p in bound["pairs"]) == [1, 2]
    for p in bound["pairs"]:
        assert len({q["game_id"] for q in p["quotes"]}) == 1


def test_doubleheader_game_number_mismatch_refuses():
    rows = [_rl("HOME", -0.5, game_number=2), _rl("AWAY", 0.5)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_dh_resolver)
    assert _codes(bound)[0] == F5_FIXTURE_BINDING_MISMATCH
    assert _codes(bound)[1] == F5_QUOTE_UNPAIRED


def test_different_books_not_cross_paired():
    rows = [_rl("HOME", -0.5), _rl("AWAY", 0.5, book="fanduel")]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_UNPAIRED] * 2


def test_stale_quote_window_not_paired():
    rows = [_rl("HOME", -0.5, quote_captured_at="2026-09-14T22:55:00Z"),
            _rl("AWAY", 0.5)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_STALE, F5_QUOTE_UNPAIRED]
    rows = [_rl("HOME", -0.5, quote_captured_at="2026-09-14T22:57:20Z"),
            _rl("AWAY", 0.5, quote_captured_at="2026-09-14T22:59:40Z")]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_PAIR_SKEW_EXCEEDED] * 2


def test_duplicate_quote_same_key_refuses_whole_rung():
    rows = [_rl("HOME", -1.5), _rl("AWAY", 1.5),
            _rl("AWAY", 1.5, odds=105), _rl("HOME", -0.5), _rl("AWAY", 0.5)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound)[:3] == [F5_QUOTE_UNPAIRED] * 3
    assert _status(bound)[3:] == ["BOUND", "BOUND"]


def test_ladder_pairs_remain_research_only():
    rows = [_rl("HOME", -0.5), _rl("AWAY", 0.5)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert all(r["research_only"] for r in bound["row_results"])
