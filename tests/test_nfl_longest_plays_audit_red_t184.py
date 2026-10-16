"""RED battery for the t184 independent audit findings L1-L2 on #2343."""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.nfl_longest_plays_empirical import (
    NflLongestPlaysError, estimate_longest_plays,
)

BASE = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
TARGET = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)


def _rec(day, player, plays, role="RECEIVER"):
    return {"game_id": f"G{day}{player}", "player_id": player, "role": role,
            "team": "T", "kickoff": BASE + timedelta(days=day),
            "play_yards": list(plays), "first_reception_yards": plays[0]}


def _pool():
    rows = []
    for i in range(8):
        rows.append(_rec(i * 7, "P1", (6, 12, 9)))
        rows.append(_rec(i * 7 + 1, "L1", (-4, 8, 15)))
    return rows


def _est(rows):
    return estimate_longest_plays(rows, player_id="P1", role="RECEIVER", kickoff=TARGET)


@pytest.mark.parametrize("bad", [100, 150, 999, -100, -250])  # L1
@pytest.mark.parametrize("who", ["P1", "L1"])
def test_l1_impossible_yards_refused_before_clamp(bad, who):
    rows = _pool()
    rows.append(_rec(60, who, (5, bad)))
    with pytest.raises(NflLongestPlaysError, match="LONGEST_HISTORY_YARDS_INVALID"):
        _est(rows)


@pytest.mark.parametrize("ok", [99, -99, 0])
def test_l1_field_boundaries_accepted(ok):
    rows = _pool()
    rows.append(_rec(60, "L1", (ok, 3)))
    assert _est(rows)["validation_status"] == "NOT_VALIDATED"


@pytest.mark.parametrize("other", ["RUSHER", "PASSER", "", None])  # L2
def test_l2_target_player_under_other_role_refused(other):
    rows = _pool()
    rows.append(_rec(61, "P1", (40,), role=other))
    with pytest.raises(NflLongestPlaysError, match="LONGEST_HISTORY_ROLE_MISMATCH"):
        _est(rows)


def test_l2_other_players_other_roles_still_ignored():
    rows = _pool()
    rows.append(_rec(61, "L1", (40,), role="RUSHER"))
    assert _est(rows)["validation_status"] == "NOT_VALIDATED"
