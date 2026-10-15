"""#2352 owner ruling (2026-10-15 21:46Z): both golfers withdraw after teeing off in a
tournament-long H2H -> settle from verified evidence (more completed rounds ranks
higher; then cumulative score after last COMPLETED round, partial rounds ignored;
then the ticket tie rule). Missing/inconsistent evidence -> SETTLEMENT_UNVERIFIED."""
import pytest

from sportsedge.research import pga_foundation as F
from sportsedge.research.pga_foundation import FoundationError, TournamentPath


def _path(p_rounds, p_wd, q_rounds, q_wd):
    return TournamentPath({"A": [68, 68, 68, 68], "P": list(p_rounds), "Q": list(q_rounds)},
                          {"A"} | ({"P"} if p_wd >= 3 else set()) | ({"Q"} if q_wd >= 3 else set()),
                          {"P": p_wd, "Q": q_wd}, winner="A")


def _w(path, pid, kind="WD"):
    rs = path.rounds[pid]
    return {"kind": kind, "round": path.withdrawn[pid], "completed_rounds": len(rs),
            "score_after_last_completed": sum(rs) if rs else None}


def _ev(path, **kw):
    e = {"market_type": "TOURNAMENT_72_H2H", "both_teed_off": True, "rule_confirmed": True,
         "rule_source": "DK Golf Sport Rules (current) - completed rounds / last full round",
         "withdrawals": {"P": _w(path, "P"), "Q": _w(path, "Q")}}
    e.update(kw)
    return e


def _s(path, a="P", b="Q", ev="auto"):
    return F.settle(path, "MATCHUP", player_id=a, opponent_id=b,
                    evidence=_ev(path) if ev == "auto" else ev)[0]


def test_both_wd_in_r1_before_completing_r1_unverified():
    p = _path([], 1, [], 1)
    with pytest.raises(FoundationError) as e:
        _s(p)
    assert e.value.code == "SETTLEMENT_UNVERIFIED"


def test_both_complete_r1_wd_r2_lower_r1_score_wins():
    p = _path([70], 2, [74], 2)
    assert _s(p) == "WIN" and _s(p, "Q", "P") == "LOSE"


def test_more_completed_rounds_ranks_higher_even_with_worse_score():
    p = _path([75, 75], 3 - 1, [66], 2)       # P completed R1+R2, Q only R1
    assert _s(p) == "WIN" and _s(p, "Q", "P") == "LOSE"


def test_both_wd_after_cut_more_rounds_wins():
    p = _path([70, 70, 75], 4, [69, 69], 3)
    assert _s(p) == "WIN"


def test_equal_score_uses_ticket_tie_rule():
    p = _path([72], 2, [72], 2)
    assert F.settle(p, "MATCHUP", player_id="P", opponent_id="Q",
                    evidence=_ev(p, tie_rule="PUSH"))[0] == "PUSH"
    with pytest.raises(FoundationError) as e:
        _s(p)                                  # no tie rule on ticket evidence
    assert e.value.code == "SETTLEMENT_UNVERIFIED"
    with pytest.raises(FoundationError) as e:
        F.settle(p, "MATCHUP", player_id="P", opponent_id="Q", evidence=_ev(p, tie_rule="GUESS"))
    assert e.value.code == "SETTLEMENT_UNVERIFIED"


def test_one_fails_to_tee_off_void():
    p = _path([70], 2, [], 0)
    assert _s(p) == "VOID" and _s(p, "Q", "P") == "VOID"


@pytest.mark.parametrize("mut", [
    lambda e: None,
    lambda e: {**e, "market_type": "ROUND_2_H2H"},
    lambda e: {**e, "market_type": "THREE_BALL"},
    lambda e: {**e, "both_teed_off": False},
    lambda e: {**e, "rule_confirmed": False},
    lambda e: {**e, "rule_source": ""},
    lambda e: {**e, "withdrawals": {"P": e["withdrawals"]["P"]}},
    lambda e: {**e, "withdrawals": {**e["withdrawals"], "Q": {**e["withdrawals"]["Q"], "completed_rounds": 2}}},
    lambda e: {**e, "withdrawals": {**e["withdrawals"], "Q": {**e["withdrawals"]["Q"], "score_after_last_completed": 99}}},
    lambda e: {**e, "withdrawals": {**e["withdrawals"], "Q": {**e["withdrawals"]["Q"], "round": 3}}},
    lambda e: {**e, "withdrawals": {**e["withdrawals"], "Q": {**e["withdrawals"]["Q"], "kind": "RETIRED"}}},
    lambda e: {**e, "withdrawals": {**e["withdrawals"], "Q": {**e["withdrawals"]["Q"], "completed_rounds": True}}},
])
def test_missing_or_inconsistent_evidence_unverified(mut):
    p = _path([70], 2, [74], 2)
    with pytest.raises(FoundationError) as e:
        _s(p, ev=mut(_ev(p)))
    assert e.value.code == "SETTLEMENT_UNVERIFIED"


def test_dq_counts_as_withdrawal_kind():
    p = _path([70], 2, [74], 2)
    ev = _ev(p)
    ev["withdrawals"]["Q"]["kind"] = "DQ"
    assert _s(p, ev=ev) == "WIN"
