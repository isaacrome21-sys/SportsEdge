"""F5 ladder pairing tests (2026-10-13). Offline fixtures only.

Owner ruling (2026-10-13, final): the rung line IS part of the F5
pairing identity -- pairing key = game identity, period, market type,
LINE, sportsbook, quote window, with team-side normalization (an
away -0.5 / home +0.5 pair is one rung group; away -1.5 / home +1.5
is another). Before this ruling's implementation the binder grouped
by book/event/fixture/market/entity only, so a multi-rung run-line
ladder collapsed into ONE binding group and every rung stopped at
F5_QUOTE_UNPAIRED under the exactly-one-pair rule (unmasked by the
gate-2.5 fixture-binding build, PR #2210).

Proves (sportsedge.mlb_f5_quote_binding):
* opposite sides at the same rung pair; different rungs never
  cross-pair, and a missing rung-mate refuses alone without
  disturbing the rungs that do pair;
* half-run and whole-number rungs form separate two-sided groups
  for run lines, totals and team totals alike;
* a three-way F5 moneyline row set (HOME / AWAY / DRAW) refuses the
  DRAW row named -- the DraftKings F5 moneyline settlement basis is
  TWO_WAY (ties push, no Draw outcome) -- and the two team rows
  still pair uncorrupted;
* doubleheaders: rung identity never merges across gamePks;
* tonight's real board shape (14 F5 rows: a moneyline pair, two
  team-total pairs and an 8-row four-rung run-line ladder) binds
  into 7 pairs and reaches the deployment gate
  F5_DEPLOYMENT_NOT_ELIGIBLE instead of F5_QUOTE_UNPAIRED;
* single-sided rungs refuse F5_QUOTE_UNPAIRED as before, and stale
  quotes still refuse F5_QUOTE_STALE at parse, before pairing.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json

from sportsedge.mlb_f5_quote_binding import (
    F5_DEPLOYMENT_NOT_ELIGIBLE, F5_PAIR_SKEW_EXCEEDED, F5_QUOTE_STALE,
    F5_QUOTE_UNPAIRED, F5_SELECTION_UNVERIFIED, bind_f5_quotes,
    phone_f5_binding_rows,
)

NOW = datetime(2026, 9, 14, 23, 0, tzinfo=timezone.utc)
GAME_PK = 777001
DH_GAME_PK = 777102
KICKOFF = "2026-09-14T23:10:00Z"
DH_KICKOFF = "2026-09-14T23:40:00Z"
FRESH_A = "2026-09-14T22:59:00Z"
FRESH_B = "2026-09-14T22:59:30Z"

FIXTURES = {
    GAME_PK: {
        "game_pk": GAME_PK,
        "away_team_id": 101, "home_team_id": 202,
        "away_name": "Away Club", "home_name": "Home Club",
        "first_pitch_at": datetime(2026, 9, 14, 23, 10,
                                   tzinfo=timezone.utc),
        "official_date": "2026-09-14",
    },
    DH_GAME_PK: {
        "game_pk": DH_GAME_PK,
        "away_team_id": 101, "home_team_id": 202,
        "away_name": "Away Club", "home_name": "Home Club",
        "first_pitch_at": datetime(2026, 9, 14, 23, 40,
                                   tzinfo=timezone.utc),
        "official_date": "2026-09-14",
    },
}


def _resolver(*, game_pk, slate_date):
    fixture = FIXTURES.get(game_pk)
    return dict(fixture) if fixture else None


def _row(**over):
    base = {
        "sport": "MLB", "market": "F5_RUN_LINE", "book": "DraftKings",
        "event_id": "34817298", "game_pk": GAME_PK,
        "away": "Away Club", "home": "Home Club", "kickoff": KICKOFF,
        "side": "AWAY", "line": -0.5, "odds": -110,
        "quote_captured_at": FRESH_A,
    }
    base.update(over)
    return base


def _rl_pair(away_line, *, game_pk=GAME_PK, kickoff=KICKOFF,
             captured_a=FRESH_A, captured_b=FRESH_B, **over):
    """One rung of a run-line ladder: away at ``away_line``, home at
    the negated line (the paired contract)."""
    return [
        _row(game_pk=game_pk, kickoff=kickoff, side="AWAY",
             line=away_line, quote_captured_at=captured_a, **over),
        _row(game_pk=game_pk, kickoff=kickoff, side="HOME",
             line=-away_line, odds=-105,
             quote_captured_at=captured_b, **over),
    ]


def _codes(bound):
    return [r.get("reason_code") for r in bound["row_results"]]


def _statuses(bound):
    return [r["status"] for r in bound["row_results"]]


# ------------------------------------------- rung identity: the ruling

def test_opposite_sides_at_same_rung_pair():
    bound = bind_f5_quotes(_rl_pair(-0.5), now=NOW,
                           fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND", "BOUND"]
    assert len(bound["pairs"]) == 1
    pair = bound["pairs"][0]
    # The pair record carries its rung identity: away -0.5 / home
    # +0.5 is the -0.5 rung -- rungs are recorded as the AWAY side's
    # signed line under team-side normalization.
    assert pair["rung_line"] == -0.5
    assert sorted(q["line"] for q in pair["quotes"]) == [-0.5, 0.5]


def test_different_rungs_do_not_cross_pair():
    # An away -0.5 quote must not pair with a home +1.5 quote: each
    # sits alone in its own rung group and refuses unpaired.
    rows = [
        _row(side="AWAY", line=-0.5),
        _row(side="HOME", line=1.5, quote_captured_at=FRESH_B),
    ]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_UNPAIRED] * 2
    assert bound["pairs"] == []


def test_complete_rung_pairs_while_orphan_rung_refuses_alone():
    rows = _rl_pair(-0.5) + [
        _row(side="HOME", line=1.5, quote_captured_at=FRESH_B)]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND", "BOUND", "BLOCKED"]
    assert bound["row_results"][2]["reason_code"] == F5_QUOTE_UNPAIRED
    assert len(bound["pairs"]) == 1
    assert bound["pairs"][0]["rung_line"] == -0.5


def test_four_rung_ladder_forms_four_separate_pairs():
    rows = []
    for away_line in (1.5, 0.5, -0.5, -1.5):  # tonight's ladder shape
        rows += _rl_pair(away_line)
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND"] * 8
    assert len(bound["pairs"]) == 4
    assert sorted(p["rung_line"] for p in bound["pairs"]) == \
        [-1.5, -0.5, 0.5, 1.5]
    for pair in bound["pairs"]:
        lines = sorted(q["line"] for q in pair["quotes"])
        assert lines[0] + lines[1] == 0  # paired lines negate
        assert {q["side"] for q in pair["quotes"]} == {"HOME", "AWAY"}


def test_whole_number_rung_pairs_and_stays_its_own_group():
    rows = _rl_pair(-2.0) + _rl_pair(-0.5)
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND"] * 4
    assert sorted(p["rung_line"] for p in bound["pairs"]) == [-2.0, -0.5]


def test_same_rung_wrong_sign_pair_still_refuses():
    # HOME -1.5 / AWAY -1.5 share a rung group (abs 1.5) but the
    # lines do not negate: not a pair, exactly as before the ruling.
    rows = [
        _row(side="HOME", line=-1.5),
        _row(side="AWAY", line=-1.5, quote_captured_at=FRESH_B),
    ]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_UNPAIRED] * 2


def test_totals_ladder_rungs_pair_independently():
    rows = []
    for line in (3.5, 4.5):
        rows.append(_row(market="F5_TOTALS", side="OVER", line=line))
        rows.append(_row(market="F5_TOTALS", side="UNDER", line=line,
                         odds=-105, quote_captured_at=FRESH_B))
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND"] * 4
    assert sorted(p["rung_line"] for p in bound["pairs"]) == [3.5, 4.5]


def test_totals_mismatched_rungs_never_pair():
    rows = [
        _row(market="F5_TOTALS", side="OVER", line=3.5),
        _row(market="F5_TOTALS", side="UNDER", line=4.5,
             quote_captured_at=FRESH_B),
    ]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_UNPAIRED] * 2


def test_team_totals_ladders_pair_per_team_per_rung():
    rows = []
    for team_side in ("AWAY", "HOME"):
        for line in (1.5, 2.5):
            rows.append(_row(market="F5_TEAM_TOTALS",
                             team_side=team_side, side="OVER",
                             line=line))
            rows.append(_row(market="F5_TEAM_TOTALS",
                             team_side=team_side, side="UNDER",
                             line=line, odds=-105,
                             quote_captured_at=FRESH_B))
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND"] * 8
    assert len(bound["pairs"]) == 4
    assert {(p["entity_id"], p["rung_line"]) for p in bound["pairs"]} \
        == {("101", 1.5), ("101", 2.5), ("202", 1.5), ("202", 2.5)}


# ------------------------------------------------------- three-way ML

def test_three_way_moneyline_draw_refuses_named_pair_uncorrupted():
    rows = [
        _row(market="F5_MONEYLINE", side="HOME", line=None, odds=-120),
        _row(market="F5_MONEYLINE", side="AWAY", line=None, odds=100,
             quote_captured_at=FRESH_B),
        _row(market="F5_MONEYLINE", side="DRAW", line=None, odds=450,
             quote_captured_at=FRESH_B),
    ]
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND", "BOUND", "BLOCKED"]
    draw = bound["row_results"][2]
    assert draw["reason_code"] == F5_SELECTION_UNVERIFIED
    # The refusal names the contract mismatch: the DraftKings F5
    # moneyline basis is TWO_WAY (ties push); there is no DRAW
    # outcome to bind, and the row never joins the two-way group.
    assert "three-way" in draw["detail"].lower()
    assert "TWO_WAY" in draw["detail"]
    assert len(bound["pairs"]) == 1
    pair = bound["pairs"][0]
    assert pair["settlement_basis"]["settlement_type"] == "TWO_WAY"
    assert {q["side"] for q in pair["quotes"]} == {"HOME", "AWAY"}
    assert pair["rung_line"] == 0.0


# ------------------------------------------------------- doubleheader

def test_doubleheader_rungs_never_merge_across_fixtures():
    # Game 1 carries a complete 0.5-rung pair; game 2 (same teams,
    # same rung) carries only the away side. Game 2's row must not
    # borrow game 1's home quote across the fixture boundary.
    rows = _rl_pair(-0.5)
    rows.append(_row(game_pk=DH_GAME_PK, kickoff=DH_KICKOFF,
                     event_id="34817301", side="AWAY", line=-0.5))
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND", "BOUND", "BLOCKED"]
    assert bound["row_results"][2]["reason_code"] == F5_QUOTE_UNPAIRED
    assert len(bound["pairs"]) == 1
    assert bound["pairs"][0]["fixture"]["game_pk"] == GAME_PK


def test_doubleheader_each_fixture_pairs_its_own_rungs():
    rows = _rl_pair(-0.5)
    rows += _rl_pair(-1.5, game_pk=DH_GAME_PK, kickoff=DH_KICKOFF)
    for row in rows[2:]:
        row["event_id"] = "34817301"
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND"] * 4
    by_pk = {p["fixture"]["game_pk"]: p for p in bound["pairs"]}
    assert set(by_pk) == {GAME_PK, DH_GAME_PK}
    assert by_pk[GAME_PK]["rung_line"] == -0.5
    assert by_pk[DH_GAME_PK]["rung_line"] == -1.5


# ------------------------------------------- preserved refusals

def test_single_sided_rung_refuses_while_sibling_rungs_pair():
    rows = _rl_pair(-0.5)
    rows += _rl_pair(1.5)[:1]  # away +1.5 only; home -1.5 missing
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND", "BOUND", "BLOCKED"]
    assert bound["row_results"][2]["reason_code"] == F5_QUOTE_UNPAIRED
    assert len(bound["pairs"]) == 1


def test_stale_quotes_refuse_on_freshness_before_pairing():
    # One rung captured 10 minutes before pricing: those rows refuse
    # F5_QUOTE_STALE at parse (gate 7), never reaching the pairing
    # gate; the fresh rung still pairs.
    rows = _rl_pair(-0.5, captured_a="2026-09-14T22:50:00Z",
                    captured_b="2026-09-14T22:50:30Z")
    rows += _rl_pair(-1.5)
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound)[:2] == [F5_QUOTE_STALE] * 2
    assert _statuses(bound)[2:] == ["BOUND", "BOUND"]
    assert len(bound["pairs"]) == 1
    assert bound["pairs"][0]["rung_line"] == -1.5


def test_pair_skew_still_applies_within_a_rung():
    rows = _rl_pair(-0.5, captured_a="2026-09-14T22:57:10Z",
                    captured_b="2026-09-14T22:59:50Z")
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_PAIR_SKEW_EXCEEDED] * 2


def test_cross_book_same_rung_does_not_pair():
    rows = _rl_pair(-0.5)
    rows[1]["book"] = "FanDuel"
    bound = bind_f5_quotes(rows, now=NOW, fixture_resolver=_resolver)
    assert _codes(bound) == [F5_QUOTE_UNPAIRED] * 2


# ------------------------------------------- tonight's board, replayed

class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def _inning(num, away, home):
    return {"num": num, "away": {"runs": away}, "home": {"runs": home}}


def _history_payload(games=120):
    """The binder battery's synthetic strictly-prior slate (team IDs
    101/202, complete innings 1-5 linescores, all before 2026-09-14)."""
    out = []
    for i in range(games):
        day = 1 + (i % 13)
        away_f5, home_f5 = i % 4, (i + 1) % 3
        innings = [_inning(1, away_f5, home_f5)] + [
            _inning(n, 0, 0) for n in range(2, 8)]
        out.append({
            "gamePk": 9000 + i,
            "gameDate": f"2026-09-{day:02d}T23:10:00Z",
            "officialDate": f"2026-09-{day:02d}",
            "status": {"abstractGameState": "Final"},
            "teams": {
                "away": {"team": {"id": 101}, "score": away_f5 + 3},
                "home": {"team": {"id": 202}, "score": home_f5 + 2},
            },
            "linescore": {"innings": innings},
        })
    return {"dates": [{"date": "2026-09-13", "games": out}]}


def _history_opener(request, timeout=0):
    return _Response(_history_payload())


def _tonights_board():
    """The 14 F5 rows of tonight's real board shape (gate-2.5 replay):
    an F5 moneyline pair, two F5 team-total pairs (one per team) and
    an 8-row, four-rung F5 run-line ladder -- every row carrying its
    verified gamePk, as the gate-2.5 resolution stamps it."""
    rows = [
        _row(market="F5_MONEYLINE", side="AWAY", line=None, odds=113),
        _row(market="F5_MONEYLINE", side="HOME", line=None, odds=-135,
             quote_captured_at=FRESH_B),
        _row(market="F5_TEAM_TOTALS", team_side="AWAY", side="OVER",
             line=2.5, odds=-120),
        _row(market="F5_TEAM_TOTALS", team_side="AWAY", side="UNDER",
             line=2.5, odds=-105, quote_captured_at=FRESH_B),
        _row(market="F5_TEAM_TOTALS", team_side="HOME", side="OVER",
             line=2.5, odds=-115),
        _row(market="F5_TEAM_TOTALS", team_side="HOME", side="UNDER",
             line=2.5, odds=-110, quote_captured_at=FRESH_B),
    ]
    for away_line in (1.5, 0.5, -0.5, -1.5):
        rows += _rl_pair(away_line)
    return rows


def test_tonights_board_binds_seven_pairs_at_bind_level():
    bound = bind_f5_quotes(_tonights_board(), now=NOW,
                           fixture_resolver=_resolver)
    assert _statuses(bound) == ["BOUND"] * 14
    assert len(bound["pairs"]) == 7
    assert F5_QUOTE_UNPAIRED not in _codes(bound)


def test_tonights_board_reaches_deployment_gate_through_stage():
    results, receipts = phone_f5_binding_rows(
        _tonights_board(), now=NOW, fixture_resolver=_resolver,
        opener=_history_opener)
    assert len(results) == 14
    for result in results:
        assert result["status"] == "NO_MODEL_OR_MARKET"
        assert result["f5_reason"] == F5_DEPLOYMENT_NOT_ELIGIBLE
        assert result["blocker"] == "NO_VALIDATION"
        assert result["f5_deployment"]["stage"] == "F5_STATE_CANDIDATE"
        assert result["f5_deployment"]["eligible"] is False
        assert "model_p" not in result
    assert receipts[0]["bound_pairs"] == 7
