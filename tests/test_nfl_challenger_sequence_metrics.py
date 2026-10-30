from __future__ import annotations

import pytest

from sportsedge.core.simulate.nfl_challenger_sequence_metrics import (
    summarize_reference_opening_metrics,
)
from sportsedge.core.simulate.nfl_possession_challenger import Possession,PossessionPath


def _path(simulation_id,opening="H",possessions=()):
    return PossessionPath(
        game_id="g",simulation_id=simulation_id,home_team="H",away_team="A",
        opening_receiver=opening,
        second_half_receiver="A" if opening=="H" else "H",
        possessions=tuple(possessions),
    )


def _pos(index,half,offense,outcome,points,start=1800,end=1700):
    defense="A" if offense=="H" else "H"
    return Possession(index,half,offense,defense,start,end,outcome,points)


def test_opening_drive_positive_points_and_first_score_receiver():
    paths=[
        _path(1,possessions=[_pos(0,1,"H","TD",7)]),
        _path(2,possessions=[_pos(0,1,"H","PUNT",0),_pos(1,1,"A","FG",3)]),
        _path(3,possessions=[_pos(0,1,"H","FG",3)]),
        _path(4,possessions=[_pos(0,1,"H","PUNT",0),_pos(1,1,"A","PUNT",0)]),
    ]
    report=summarize_reference_opening_metrics(paths)
    assert report["opening_drive_scoring_rate"]==.5
    assert report["first_score_opening_receiver_rate"]==pytest.approx(2/3)
    assert report["scored_path_count"]==3
    assert report["scoreless_path_count"]==1
    assert report["first_score_denominator"]=="paths_with_at_least_one_score"
    assert report["official_authority"] is False


def test_opening_drive_safety_scores_for_defense_not_receiver():
    path=_path(1,possessions=[_pos(0,1,"H","SAFETY",-2)])
    report=summarize_reference_opening_metrics([path])
    assert report["opening_drive_scoring_rate"]==0.0
    assert report["first_score_opening_receiver_rate"]==0.0
    assert report["scored_path_count"]==1
    assert report["safety_scoring_team"]=="defense"


def test_away_opening_receiver_is_handled_symmetrically():
    path=_path(1,opening="A",possessions=[_pos(0,1,"A","FG",3)])
    report=summarize_reference_opening_metrics([path])
    assert report["opening_drive_scoring_rate"]==1.0
    assert report["first_score_opening_receiver_rate"]==1.0


def test_scoreless_paths_report_undefined_first_score_rate():
    path=_path(1,possessions=[_pos(0,1,"H","PUNT",0)])
    report=summarize_reference_opening_metrics([path])
    assert report["scored_path_count"]==0
    assert report["scoreless_path_count"]==1
    assert report["first_score_opening_receiver_rate"] is None


def test_missing_first_half_possession_fails_closed():
    path=_path(1,possessions=[_pos(0,2,"A","FG",3)])
    with pytest.raises(ValueError,match="CHALLENGER_OPENING_POSSESSION_MISSING"):
        summarize_reference_opening_metrics([path])


def test_opening_receiver_path_mismatch_fails_closed():
    path=_path(1,opening="H",possessions=[_pos(0,1,"A","FG",3)])
    with pytest.raises(ValueError,match="CHALLENGER_OPENING_RECEIVER_PATH_MISMATCH"):
        summarize_reference_opening_metrics([path])


def test_non_possession_path_fails_closed():
    with pytest.raises(TypeError,match="POSSESSION_PATH_REQUIRED"):
        summarize_reference_opening_metrics([object()])
