import pytest

from sportsedge.mlb_lineup_projection import project_from_history
from sportsedge.mlb_source import MLBSourceError


def test_project_from_history_prefers_recent_stable_order():
    newest=(101,102,103,104,105,106,107,108,109)
    prior=(101,102,103,104,105,106,107,109,108)
    older=(101,102,103,104,105,106,107,108,109)
    active=set(range(101,110))
    got=project_from_history([(3,newest),(2,prior),(1,older)],active)
    assert got[:7]==newest[:7]
    assert set(got)==active
    assert len(got)==len(set(got))==9


def test_project_from_history_filters_inactive_and_uses_recent_replacement():
    a=(1,2,3,4,5,6,7,8,9)
    b=(1,2,3,4,5,6,7,8,10)
    c=(1,2,3,4,5,6,7,10,8)
    active={1,2,3,4,5,6,7,8,10}
    got=project_from_history([(3,a),(2,b),(1,c)],active)
    assert 9 not in got
    assert set(got)==active


def test_projection_resolves_player_moving_slots_without_duplicates():
    a=(1,2,3,4,5,6,7,8,9)
    b=(2,1,3,4,5,6,7,8,9)
    c=(1,2,3,4,5,6,7,8,9)
    active=set(range(1,10))
    got=project_from_history([(3,a),(2,b),(1,c)],active)
    assert len(got)==9
    assert len(set(got))==9
    assert set(got)==active


def test_projection_is_deterministic():
    histories=[
        (6,(11,12,13,14,15,16,17,18,19)),
        (5,(11,12,13,14,15,16,17,19,18)),
        (4,(11,12,13,14,15,16,17,18,19)),
    ]
    active=set(range(11,20))
    assert project_from_history(histories,active)==project_from_history(histories,active)


def test_projection_fails_closed_with_insufficient_history():
    with pytest.raises(MLBSourceError,match='INSUFFICIENT_HISTORY'):
        project_from_history([(1,(1,2,3,4,5,6,7,8,9))],set(range(1,10)))
