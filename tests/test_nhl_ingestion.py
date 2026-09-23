import pytest
from sportsedge.sports.nhl.ingestion import NHLShotSnapshot, normalize_shot_rows, shot_snapshot_sha256


def row(**kw):
    base = dict(event_id="1", event_time_utc="2026-10-08T02:00:00Z", team_id="A",
                shooter_id="p1", goalie_id="g1", x=72.0, y=8.0, shot_type="wrist",
                strength_state="5v5", is_goal=False, is_rebound=False, is_rush=True)
    base.update(kw)
    return base


def test_normalizer_preserves_hockey_context_and_is_deterministic():
    events = normalize_shot_rows([row(event_id="2"), row(event_id="1", event_time_utc="2026-10-07T02:00:00Z")],
                                 game_id="g", source="fixture", source_version="v1")
    assert [e.event_id for e in events] == ["1", "2"]
    assert events[1].strength_state == "5v5"
    assert events[1].is_rush is True


def test_missing_xg_inputs_fail_closed_instead_of_imputation():
    bad = row(); del bad["strength_state"]
    with pytest.raises(ValueError):
        normalize_shot_rows([bad], game_id="g", source="fixture", source_version="v1")


def test_snapshot_rejects_current_game_leakage():
    events = normalize_shot_rows([row(event_time_utc="2026-10-10T00:01:00Z")], game_id="g", source="fixture", source_version="v1")
    with pytest.raises(ValueError):
        NHLShotSnapshot("g", "2026-10-10T00:00:00Z", "2026-10-09T20:00:00Z", "fixture", "v1", events)


def test_snapshot_rejects_post_drop_capture():
    events = normalize_shot_rows([row()], game_id="g", source="fixture", source_version="v1")
    with pytest.raises(ValueError):
        NHLShotSnapshot("g", "2026-10-10T00:00:00Z", "2026-10-10T00:01:00Z", "fixture", "v1", events)


def test_snapshot_hash_is_deterministic():
    events = normalize_shot_rows([row()], game_id="g", source="fixture", source_version="v1")
    snap = NHLShotSnapshot("g", "2026-10-10T00:00:00Z", "2026-10-09T20:00:00Z", "fixture", "v1", events)
    assert shot_snapshot_sha256(snap) == shot_snapshot_sha256(snap)
