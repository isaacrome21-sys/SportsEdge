"""#2352 re-audit: partial rounds never count as completed (WD in round wd => at most
wd-1 completed rounds, partial strokes recorded separately), and settlement evidence
must be bound to tournament id, both player ids, market instance id and an
allowlisted rule_source; otherwise SETTLEMENT_UNVERIFIED."""
import pytest

from sportsedge.research import pga_foundation as F
from sportsedge.research.pga_foundation import FoundationError, TournamentPath

TID = "PGA-SYN-2026-01"
SRC = "DK_GOLF_SPORT_RULES_CURRENT"


def _bind(ev, a, b, **kw):
    e = {**ev, "tournament_id": TID, "player_ids": [a, b], "market_instance_id": "MKT-1",
         "rule_source": SRC}
    e.update(kw)
    return e


# --- partial rounds -------------------------------------------------------
def test_wd_round_allows_at_most_wd_minus_one_completed_rounds():
    p = TournamentPath({"A": [68, 68, 68, 68], "W": [71]}, {"A"}, {"W": 1}, winner="A")
    with pytest.raises(FoundationError) as e:
        F.check_path(p)
    assert e.value.code == "PGA_WITHDRAWN_ROUND_INVALID"


def test_partial_round_recorded_separately_and_never_counted():
    p = TournamentPath({"A": [68, 68, 68, 68], "W": [71]}, {"A"}, {"W": 2}, winner="A",
                       partial_round={"W": 40}, tournament_id=TID)
    assert F.check_path(p)
    assert p.completed_rounds("W") == 1 and p.total("W") == 71


@pytest.mark.parametrize("partial,code", [
    ({"A": 30}, "PGA_PARTIAL_ROUND_INVALID"),          # not withdrawn
    ({"W": float("nan")}, "PGA_PARTIAL_ROUND_INVALID"),
    ({"W": True}, "PGA_PARTIAL_ROUND_INVALID"),
    ({"GHOST": 30}, "PGA_PARTIAL_ROUND_INVALID"),
])
def test_partial_round_map_validated(partial, code):
    p = TournamentPath({"A": [68, 68, 68, 68], "W": [71]}, {"A"}, {"W": 2}, winner="A",
                       partial_round=partial)
    with pytest.raises(FoundationError) as e:
        F.check_path(p)
    assert e.value.code == code


def test_partial_round_strokes_ignored_in_both_wd_ranking():
    p = TournamentPath({"A": [68, 68, 68, 68], "P": [72], "Q": [70]}, {"A"},
                       {"P": 2, "Q": 2}, winner="A", partial_round={"P": 20, "Q": 60},
                       tournament_id=TID)
    w = lambda pid, sc: {"kind": "WD", "round": 2, "completed_rounds": 1,
                         "score_after_last_completed": sc}
    ev = _bind({"market_type": "TOURNAMENT_72_H2H", "both_teed_off": True, "rule_confirmed": True,
                "withdrawals": {"P": w("P", 72), "Q": w("Q", 70)}}, "P", "Q")
    assert F.settle(p, "MATCHUP", player_id="Q", opponent_id="P", evidence=ev)[0] == "WIN"


# --- evidence binding -----------------------------------------------------
def _after_cut_case():
    p = TournamentPath({"A": [68, 68, 68, 68], "M": [70, 70], "C": [80, 80]}, {"A", "M"},
                       {"M": 3}, winner="A", tournament_id=TID)
    ev = {"market_type": "TOURNAMENT_72_H2H", "both_teed_off": True,
          "official_cut_confirmed": True, "rule_confirmed": True,
          "withdrawal": {"player_id": "M", "kind": "WD", "round": 3, "holes_completed": 9}}
    return p, ev


def test_fully_bound_evidence_settles():
    p, ev = _after_cut_case()
    assert F.settle(p, "MATCHUP", player_id="M", opponent_id="C",
                    evidence=_bind(ev, "M", "C"))[0] == "WIN"


@pytest.mark.parametrize("kw", [
    {"tournament_id": "PGA-OTHER"}, {"tournament_id": None},
    {"player_ids": ["M", "A"]}, {"player_ids": ["M"]}, {"player_ids": None},
    {"market_instance_id": ""}, {"market_instance_id": None},
    {"rule_source": "?"}, {"rule_source": "TBD"}, {"rule_source": "DK house rules v15"},
    {"rule_source": ""},
])
def test_unbound_or_placeholder_evidence_unverified(kw):
    p, ev = _after_cut_case()
    with pytest.raises(FoundationError) as e:
        F.settle(p, "MATCHUP", player_id="M", opponent_id="C", evidence=_bind(ev, "M", "C", **kw))
    assert e.value.code == "SETTLEMENT_UNVERIFIED"


def test_path_without_tournament_id_unverified():
    p, ev = _after_cut_case()
    p.tournament_id = None
    with pytest.raises(FoundationError) as e:
        F.settle(p, "MATCHUP", player_id="M", opponent_id="C", evidence=_bind(ev, "M", "C"))
    assert e.value.code == "SETTLEMENT_UNVERIFIED"


def test_rule_source_registry_is_allowlist():
    assert SRC in F.RULE_SOURCE_REGISTRY
    assert "?" not in F.RULE_SOURCE_REGISTRY
