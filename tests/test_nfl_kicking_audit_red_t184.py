"""RED battery for the t184 independent audit findings K1-K6 on #2342."""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.nfl_kicking_empirical import NflKickingError, estimate_kicking

BASE = datetime(2026, 8, 1, 17, tzinfo=timezone.utc)
TARGET = datetime(2026, 10, 15, 18, tzinfo=timezone.utc)


def _games(**override):
    rows = []
    for i in range(6):
        row = {"game_id": f"G{i}", "kicker_id": "K1",
               "kickoff": BASE + timedelta(days=7 * i),
               "fg_attempts": [(36.0, True), (49.0, False)],
               "pat_attempts": 2, "pat_makes": 2}
        if i == 3:
            row.update(override)
        rows.append(row)
    return rows


def _refuses(code, **override):
    with pytest.raises(NflKickingError, match=code):
        estimate_kicking(_games(**override), kicker_id="K1", kickoff=TARGET)


@pytest.mark.parametrize("dist", [None, "x", "", object()])  # K1
def test_k1_bad_distance_is_named_refusal_not_raw_error(dist):
    _refuses("KICKING_FG_DISTANCE_INVALID", fg_attempts=[(dist, True)])


@pytest.mark.parametrize("dist", ["36", "49.0", b"40"])  # K2
def test_k2_numeric_strings_rejected_for_distance(dist):
    _refuses("KICKING_FG_DISTANCE_INVALID", fg_attempts=[(dist, True)])


@pytest.mark.parametrize("field,val", [("pat_attempts", "2"), ("pat_makes", "1"),
                                       ("pat_attempts", "two")])
def test_k2_numeric_strings_rejected_for_pat(field, val):
    _refuses("KICKING_PAT_SUPPORT_INVALID", **{field: val})


@pytest.mark.parametrize("made", [1, 0, "made", None, 1.0])  # K3
def test_k3_made_must_be_bool(made):
    _refuses("KICKING_FG_RESULT_INVALID", fg_attempts=[(36.0, made)])


@pytest.mark.parametrize("dist", [0, 5, 17.9, 75.1, 99, 150, float("inf"), float("nan"), -30])  # K4
def test_k4_distance_outside_plausible_range(dist):
    _refuses("KICKING_FG_DISTANCE_INVALID", fg_attempts=[(dist, True)])


@pytest.mark.parametrize("dist", [18, 18.0, 66, 75])
def test_k4_boundary_distances_accepted(dist):
    r = estimate_kicking(_games(fg_attempts=[(dist, True)]), kicker_id="K1", kickoff=TARGET)
    assert r["validation_status"] == "NOT_VALIDATED"


def test_k5_none_fg_attempts_is_missing_not_zero():
    _refuses("KICKING_FG_ATTEMPTS_MISSING", fg_attempts=None)


@pytest.mark.parametrize("bad", ["36,True", {"d": 36}, [(36.0,)], [36.0]])
def test_k5_malformed_fg_attempts(bad):
    _refuses("KICKING_FG_ATTEMPTS_INVALID", fg_attempts=bad)


def test_k5_empty_list_is_genuine_zero():
    r = estimate_kicking(_games(fg_attempts=[]), kicker_id="K1", kickoff=TARGET)
    assert r["fg_attempts_used"] == 10


@pytest.mark.parametrize("ko", [datetime(2026, 8, 22, 17), "2026-08-22T17:00:00Z"])  # K6
def test_k6_naive_or_nondatetime_history_kickoff(ko):
    _refuses("KICKING_HISTORY_KICKOFF_TIMEZONE_REQUIRED", kickoff=ko)
