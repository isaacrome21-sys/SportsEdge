"""#2351 re-audit: stats props under a NO_CONTEST settle already-decided lines
(Over reached -> OVER, Under exceeded -> LOSE); lines not yet reached VOID."""
import pytest

from sportsedge.research import ufc_foundation_props as P
from sportsedge.research.ufc_foundation import BoutPath

NC = BoutPath("RED", "BLU", 3, "NO_CONTEST", None, 2, 40)


def _path(sig=30, td=2, kd=1):
    zero = {s: 0 for s in P.STATS}
    r1 = dict(zero, SIG=sig, TD=td, TDA=td + 1, KD=kd)
    rounds = {(f, r): dict(r1 if (f, r) == ("RED", 1) else zero)
              for f in ("RED", "BLU") for r in (1, 2)}
    p = P.StatsPath(NC, rounds)
    assert P.check_stats(p)
    return p


@pytest.mark.parametrize("m,line", [("SIGNIFICANT_STRIKES", 25.5), ("TAKEDOWNS", 1.5),
                                    ("KNOCKDOWNS", 0.5)])
def test_reached_line_settles(m, line):
    p = _path()
    assert P.settle_stat(p, m, fighter_id="RED", line=line) == "OVER"
    assert P.settle_stat(p, m, fighter_id="RED", line=line, side="OVER") == "OVER"
    assert P.settle_stat(p, m, fighter_id="RED", line=line, side="UNDER") == "LOSE"


@pytest.mark.parametrize("m,line", [("SIGNIFICANT_STRIKES", 30.5), ("TAKEDOWNS", 2.5),
                                    ("KNOCKDOWNS", 1.5), ("SIGNIFICANT_STRIKES", 30)])
def test_unreached_line_void(m, line):
    p = _path()
    for side in (None, "OVER", "UNDER"):
        assert P.settle_stat(p, m, fighter_id="RED", line=line, side=side) == "VOID"


def test_side_validated():
    with pytest.raises(P.FoundationError):
        P.settle_stat(_path(), "TAKEDOWNS", fighter_id="RED", line=0.5, side="MAYBE")
