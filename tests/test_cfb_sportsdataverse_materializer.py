import pytest
from sportsedge.sports.cfb.sportsdataverse_history import TeamSnapshot
from sportsedge.sports.cfb.sportsdataverse_materializer import (
    SDVMaterializationError, materialize_native_candidate_inputs,
)

def snap(team):
    return TeamSnapshot(team_id=team,season=2025,through_week=2,games_in_sample=2,
      off_ppa_rush=.1,off_ppa_dropback=.2,off_success_rate=.4,
      def_ppa_rush_allowed=-.1,def_ppa_dropback_allowed=.05,def_success_rate_allowed=.3,
      standard_down_ppa=.15,passing_down_success_rate=.35,explosive_rate=.1,net_field_position=-70)

def test_materializer_ignores_realized_scores_and_is_pregame_only():
    base={"game_id":9,"season":2025,"week":3,"home_id":1,"away_id":2,"neutral_site":False}
    a=materialize_native_candidate_inputs(games=[{**base,"home_points":99,"away_points":0}],snapshots=[snap(1),snap(2)],prior_season_snapshots=[prior_snap(1),prior_snap(2)])
    b=materialize_native_candidate_inputs(games=[{**base,"home_points":0,"away_points":99}],snapshots=[snap(2),snap(1)],prior_season_snapshots=[prior_snap(1),prior_snap(2)])
    assert a==b
    assert "home_points" not in a[0] and "away_points" not in a[0]
    assert a[0]["provenance_class"]=="RECONSTRUCTED_HISTORICAL_NOT_PIT"

def test_materializer_requires_exact_prior_week_snapshot():
    with pytest.raises(SDVMaterializationError,match="PREGAME_SNAPSHOT_MISSING"):
        materialize_native_candidate_inputs(
          games=[{"game_id":9,"season":2025,"week":3,"home_id":1,"away_id":2,"neutral_site":False}],
          snapshots=[snap(1)])

def test_materializer_rejects_2026():
    with pytest.raises(SDVMaterializationError,match="2026_OUTCOMES"):
        materialize_native_candidate_inputs(
          games=[{"game_id":9,"season":2026,"week":3,"home_id":1,"away_id":2,"neutral_site":False}],snapshots=[])

def prior_snap(team, through_week=14):
    s=snap(team)
    return TeamSnapshot(**{**s.__dict__,"season":2024,"through_week":through_week,"games_in_sample":12})

def test_week1_uses_latest_explicit_prior_season_snapshot():
    rows=materialize_native_candidate_inputs(
      games=[{"game_id":1,"season":2025,"week":1,"home_id":1,"away_id":2,"neutral_site":True,"home_score":50,"away_score":0}],
      snapshots=[],
      prior_season_snapshots=[prior_snap(1,13),prior_snap(1,14),prior_snap(2,14)],
    )
    assert rows[0]["home_games_in_sample"]==12
    assert rows[0]["away_games_in_sample"]==12
    assert "home_score" not in rows[0]

def test_week1_fails_closed_without_prior_season_snapshot():
    with pytest.raises(SDVMaterializationError,match="PRIOR_SEASON_SNAPSHOT_REQUIRED"):
        materialize_native_candidate_inputs(
          games=[{"game_id":1,"season":2025,"week":1,"home_id":1,"away_id":2,"neutral_site":False}],
          snapshots=[],prior_season_snapshots=[prior_snap(1)],
        )

def test_2015_week1_is_excluded_at_frozen_acquisition_boundary():
    prior=TeamSnapshot(**{**snap(1).__dict__,"season":2014,"through_week":14,"games_in_sample":12})
    rows=materialize_native_candidate_inputs(
      games=[{"game_id":201501,"season":2015,"week":1,"home_id":1,"away_id":1,"neutral_site":False,"home_score":99,"away_score":0}],
      snapshots=[],prior_season_snapshots=[prior])
    assert rows==[]


def test_materializer_preserves_neutral_site_and_rejects_missing_flag():
    rows=materialize_native_candidate_inputs(
      games=[{"game_id":2,"season":2025,"week":1,"home_id":1,"away_id":2,"neutral_site":True}],
      snapshots=[],
      prior_season_snapshots=[prior_snap(1),prior_snap(2)],
    )
    assert rows[0]["neutral_site"] is True
    with pytest.raises(SDVMaterializationError,match="NEUTRAL_SITE_REQUIRED"):
        materialize_native_candidate_inputs(
          games=[{"game_id":3,"season":2025,"week":1,"home_id":1,"away_id":2}],
          snapshots=[],
          prior_season_snapshots=[prior_snap(1),prior_snap(2)],
        )
