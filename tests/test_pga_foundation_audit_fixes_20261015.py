"""Regression tests for #2352 audit findings + owner H2H withdrawal ruling (2026-10-15).

After-cut withdrawal settlement is PENDING DraftKings confirmation: a WIN for the
made-cut golfer is returned only with complete, confirmed rule evidence; otherwise
the named refusal SETTLEMENT_UNVERIFIED is raised (never a guessed WIN/LOSS).
"""
import pytest

from sportsedge.research import pga_foundation as F
from sportsedge.research.pga_foundation import FoundationError, TournamentPath


def _ev(pid="M", kind="WD", rnd=3, holes=9, opp="C", **kw):
    e = {"market_type": "TOURNAMENT_72_H2H", "both_teed_off": True,
         "official_cut_confirmed": True,
         "withdrawal": {"player_id": pid, "kind": kind, "round": rnd, "holes_completed": holes},
         "rule_confirmed": True, "rule_source": "DK_GOLF_SPORT_RULES_CURRENT",
         "tournament_id": "PGA-SYN-2026-01", "player_ids": ["M", opp],
         "market_instance_id": "MKT-1"}
    e.update(kw)
    return e


def _path(m_rounds=(70, 70), m_wd=3):
    # M made the cut then withdrew in round m_wd; C missed the cut; A won.
    return TournamentPath({"A": [68, 68, 68, 68], "M": list(m_rounds), "C": [80, 80],
                           "B": [70, 70, 70, 70]},
                          {"A", "M", "B"}, {"M": m_wd}, winner="A",
                          tournament_id="PGA-SYN-2026-01")


# --- check_path withdrawn-map validation ---------------------------------
@pytest.mark.parametrize("wd,code", [
    ({"GHOST": 1}, "PGA_WITHDRAWN_UNKNOWN_PLAYER"),
    ({"C": 5}, "PGA_WITHDRAWN_ROUND_INVALID"),
    ({"C": -1}, "PGA_WITHDRAWN_ROUND_INVALID"),
    ({"C": float("nan")}, "PGA_WITHDRAWN_ROUND_INVALID"),
    ({"C": float("inf")}, "PGA_WITHDRAWN_ROUND_INVALID"),
    ({"C": True}, "PGA_WITHDRAWN_ROUND_INVALID"),
    ({"C": 1.0}, "PGA_WITHDRAWN_ROUND_INVALID"),
    ({"C": 3}, "PGA_WITHDRAWN_CUT_INCONSISTENT"),   # missed cut cannot WD in R3
    ({"B": 1}, "PGA_WITHDRAWN_CUT_INCONSISTENT"),   # made cut cannot WD in R1
])
def test_withdrawn_map_validated(wd, code):
    p = TournamentPath({"A": [68, 68, 68, 68], "C": [80, 80], "B": [70, 70, 70, 70]},
                       {"A", "B"}, wd, winner="A")
    with pytest.raises(FoundationError) as e:
        F.check_path(p)
    assert e.value.code == code


# --- H2H after-cut withdrawal (owner ruling) ------------------------------
def test_made_cut_then_wd_mid_r3_beats_missed_cut_with_confirmed_evidence():
    p = _path()
    assert F.settle(p, "MATCHUP", player_id="M", opponent_id="C", evidence=_ev())[0] == "WIN"
    assert F.settle(p, "MATCHUP", player_id="C", opponent_id="M", evidence=_ev())[0] == "LOSE"


def test_dq_mid_r3_beats_missed_cut_with_confirmed_evidence():
    assert F.settle(_path(), "MATCHUP", player_id="M", opponent_id="C",
                    evidence=_ev(kind="DQ"))[0] == "WIN"


@pytest.mark.parametrize("ev", [
    None,
    _ev(rule_confirmed=False),
    _ev(market_type="ROUND_H2H"),
    _ev(both_teed_off=False),
    _ev(official_cut_confirmed=False),
    _ev(pid="C"),
    _ev(rnd=4),
    _ev(holes=None),
    _ev(kind="RETIRED"),
    _ev(rule_source=""),
])
def test_made_cut_then_wd_unverified_without_complete_evidence(ev):
    with pytest.raises(FoundationError) as e:
        F.settle(_path(), "MATCHUP", player_id="M", opponent_id="C", evidence=ev)
    assert e.value.code == "SETTLEMENT_UNVERIFIED"


def test_wd_immediately_after_36_holes_unverified_even_with_evidence():
    with pytest.raises(FoundationError) as e:
        F.settle(_path(), "MATCHUP", player_id="M", opponent_id="C", evidence=_ev(holes=0))
    assert e.value.code == "SETTLEMENT_UNVERIFIED"


def test_both_made_cut_one_wd_unverified_without_evidence_lose_with():
    p = _path()
    with pytest.raises(FoundationError) as e:
        F.settle(p, "MATCHUP", player_id="M", opponent_id="B")
    assert e.value.code == "SETTLEMENT_UNVERIFIED"
    assert F.settle(p, "MATCHUP", player_id="M", opponent_id="B", evidence=_ev(opp="B"))[0] == "LOSE"


def test_both_missed_cut_and_no_tee_off():
    p = TournamentPath({"A": [68, 68, 68, 68], "C": [80, 80], "D": [81, 81], "X": []},
                       {"A"}, {"X": 0}, winner="A")
    assert F.settle(p, "MATCHUP", player_id="C", opponent_id="D")[0] == "WIN"
    assert F.settle(p, "MATCHUP", player_id="A", opponent_id="X")[0] == "VOID"
    assert F.settle(p, "MATCHUP", player_id="X", opponent_id="C")[0] == "VOID"
