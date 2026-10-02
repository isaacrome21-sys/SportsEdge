import pytest
from sportsedge.sports.cfb.sportsdataverse_training_rows import SDVTrainingRowError,attach_training_labels

def pred():
    return {"game_id":"9","season":2025,"week":3,"home_id":1,"away_id":2,
            "home_features":{"x":1.0},"away_features":{"x":2.0},
            "provenance_class":"RECONSTRUCTED_HISTORICAL_NOT_PIT"}

def test_labels_attach_after_features_without_mutating_them():
    p=pred()
    out=attach_training_labels(predictive_rows=[p],completed_games=[
      {"game_id":"9","season":2025,"week":3,"home_id":1,"away_id":2,"home_points":24,"away_points":17}
    ])
    assert out[0]["home_features"]==p["home_features"]
    assert out[0]["away_features"]==p["away_features"]
    assert out[0]["home_points"]==24 and out[0]["away_points"]==17
    assert "home_points" not in p

def test_label_identity_mismatch_fails_closed():
    with pytest.raises(SDVTrainingRowError,match="IDENTITY_MISMATCH"):
        attach_training_labels(predictive_rows=[pred()],completed_games=[
          {"game_id":"9","season":2025,"week":3,"home_id":99,"away_id":2,"home_points":24,"away_points":17}
        ])

def test_2026_labels_are_prohibited():
    p={**pred(),"season":2026}
    with pytest.raises(SDVTrainingRowError,match="2026_OUTCOMES"):
        attach_training_labels(predictive_rows=[p],completed_games=[
          {"game_id":"9","season":2026,"week":3,"home_id":1,"away_id":2,"home_points":24,"away_points":17}
        ])
