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
    base={"game_id":9,"season":2025,"week":3,"home_id":1,"away_id":2}
    a=materialize_native_candidate_inputs(games=[{**base,"home_score":99,"away_score":0}],snapshots=[snap(1),snap(2)])
    b=materialize_native_candidate_inputs(games=[{**base,"home_score":0,"away_score":99}],snapshots=[snap(2),snap(1)])
    assert a==b
    assert "home_score" not in a[0] and "away_score" not in a[0]
    assert a[0]["provenance_class"]=="RECONSTRUCTED_HISTORICAL_NOT_PIT"

def test_materializer_requires_exact_prior_week_snapshot():
    with pytest.raises(SDVMaterializationError,match="PREGAME_SNAPSHOT_MISSING"):
        materialize_native_candidate_inputs(
          games=[{"game_id":9,"season":2025,"week":3,"home_id":1,"away_id":2}],
          snapshots=[snap(1)])

def test_materializer_rejects_2026():
    with pytest.raises(SDVMaterializationError,match="2026_OUTCOMES"):
        materialize_native_candidate_inputs(
          games=[{"game_id":9,"season":2026,"week":3,"home_id":1,"away_id":2}],snapshots=[])
