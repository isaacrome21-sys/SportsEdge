"""Independent RED audit battery for N43/N44/N45 NFL kicking research.

Stacked only on PR #2338's unmodified construction, at exact base
6a95529343350cdfc438fe0d1341e354c7ce76a7.
No production code, registry, or model authority is changed by this file.

Expected REDs expose fail-open identity/outcome/quote support errors.
Positive controls establish the engine already handles coherent input.
"""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.nfl_kicking_empirical import (
    NflKickingError,
    build_kicking_games,
    estimate_kicking,
    prob_over_under,
)

BASE = datetime(2026, 9, 6, 17, 0, tzinfo=timezone.utc)
TARGET = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)


def _history(kid="K1", *, fg=((35, True), (48, False)),
             pat_attempts=2, pat_makes=2, n=6, offset=0):
    return [{
        "game_id": f"{kid}-G{i}",
        "kicker_id": kid,
        "kickoff": BASE + timedelta(days=i * 7 + offset),
        "fg_attempts": list(fg),
        "pat_attempts": pat_attempts,
        "pat_makes": pat_makes,
    } for i in range(n)]


def _pbp_frame(*, distance=35, fg_result="made"):
    import pandas as pd
    pbp = pd.DataFrame([{
        "game_id": "2026_01_A_B",
        "kicker_player_id": "K1",
        "kicker_player_name": "Synthetic Kicker",
        "posteam": "A",
        "field_goal_attempt": 1,
        "field_goal_result": fg_result,
        "kick_distance": distance,
        "extra_point_attempt": 0,
        "extra_point_result": None,
    }])
    games = pd.DataFrame([{
        "game_id": "2026_01_A_B",
        "gameday": "2026-09-13",
        "gametime": "13:00",
    }])
    return pbp, games


# GREEN controls: coherent rows are admissible; target/future inputs stay out.

def test_control_valid_history_and_settlement_mass():
    result = estimate_kicking(_history(), kicker_id="K1", kickoff=TARGET)
    assert result["games_used"] == 6
    for market in ("fg_made", "xp_made", "kicking_points"):
        assert sum(result[market]["pmf"].values()) == pytest.approx(1.0)
    assert result["validation_status"] == "NOT_VALIDATED"


def test_control_post_cutoff_target_kicker_is_excluded():
    history = _history()
    clean = estimate_kicking(history, kicker_id="K1", kickoff=TARGET)
    future = {
        "game_id": "FUTURE", "kicker_id": "K1", "kickoff": TARGET,
        "fg_attempts": [(20, True)] * 10,
        "pat_attempts": 10, "pat_makes": 10,
    }
    later = estimate_kicking(history + [future], kicker_id="K1", kickoff=TARGET)
    assert clean == later


def test_control_named_insufficient_history_refusal():
    with pytest.raises(NflKickingError, match="KICKING_HISTORY_INSUFFICIENT"):
        estimate_kicking(_history(n=4), kicker_id="K1", kickoff=TARGET)


def test_control_valid_pbp_fg_record():
    pbp, games = _pbp_frame()
    records = build_kicking_games(pbp, games)
    assert len(records) == 1
    assert records[0]["kicker_id"] == "K1"
    assert records[0]["fg_attempts"] == [(35.0, True)]


# RED: target kicker must be the same athlete in *every* history row.

def test_foreign_kicker_history_never_counts_toward_minimum():
    # All six genuine rows belong to K2; K1 has NO prior data.
    with pytest.raises(NflKickingError, match="KICKING_"):
        estimate_kicking(_history("K2"), kicker_id="K1", kickoff=TARGET)


def test_foreign_kicker_rows_cannot_change_target_distribution():
    own = _history("K1", fg=((25, True),))
    foreign = _history("K2", fg=((58, False), (60, False),
                                   (55, False)), offset=1)
    baseline = estimate_kicking(own, kicker_id="K1", kickoff=TARGET)
    mixed = estimate_kicking(own + foreign, kicker_id="K1",
                             kickoff=TARGET)
    assert mixed["games_used"] == baseline["games_used"]
    assert mixed["fg_made"]["pmf"] == baseline["fg_made"]["pmf"]
    assert mixed["xp_made"]["pmf"] == baseline["xp_made"]["pmf"]


def test_duplicate_game_id_cannot_inflate_prior_game_count():
    duplicate = _history(n=1)[0]
    six_copies = [dict(duplicate) for _ in range(6)]
    with pytest.raises(NflKickingError, match="KICKING_"):
        estimate_kicking(six_copies, kicker_id="K1", kickoff=TARGET)


def test_pat_makes_cannot_exceed_pat_attempts():
    with pytest.raises(NflKickingError, match="KICKING_"):
        estimate_kicking(
            _history(pat_attempts=1, pat_makes=2),
            kicker_id="K1", kickoff=TARGET)


def test_negative_pat_attempts_must_refuse():
    with pytest.raises(NflKickingError, match="KICKING_"):
        estimate_kicking(
            _history(pat_attempts=-1, pat_makes=0),
            kicker_id="K1", kickoff=TARGET)


@pytest.mark.parametrize("distance", [None, float("nan"), -5, float("inf")])
def test_missing_or_nonphysical_fg_distance_cannot_be_imputed(distance):
    # The unmodified reader maps absent distance to 0 yards, and puts
    # negative / infinite distance into its last 60+ band.
    pbp, games = _pbp_frame(distance=distance)
    with pytest.raises(NflKickingError, match="KICKING_"):
        build_kicking_games(pbp, games)


def test_missing_fg_result_is_not_a_measured_miss():
    pbp, games = _pbp_frame(fg_result=None)
    with pytest.raises(NflKickingError, match="KICKING_"):
        build_kicking_games(pbp, games)


def test_nonfinite_quote_line_must_refuse_not_return_zero_mass():
    with pytest.raises(NflKickingError, match="KICKING_"):
        prob_over_under({0: 0.3, 1: 0.7}, float("nan"))


def test_history_with_naive_timestamp_refuses_by_name():
    history = _history()
    history[0]["kickoff"] = datetime(2026, 9, 6, 17, 0)
    with pytest.raises(NflKickingError, match="KICKING_"):
        estimate_kicking(history, kicker_id="K1", kickoff=TARGET)
