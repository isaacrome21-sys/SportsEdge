from sportsedge.sports.cfb.sportsdataverse_manifest import build_manifest


def test_manifest_is_order_independent_and_zero_authority():
    ds1={"espn_cfb_adv_team":[{"game_id":2,"x":1},{"game_id":1,"x":2}]}
    ds2={"espn_cfb_adv_team":[{"game_id":1,"x":2},{"game_id":2,"x":1}]}
    a=build_manifest(season=2025,target_week=4,datasets=ds1,feature_names=["x"])
    b=build_manifest(season=2025,target_week=4,datasets=ds2,feature_names=["x"])
    assert a==b
    assert a["classification"]=="RECONSTRUCTED_HISTORICAL_NOT_PIT"
    assert a["through_week"]==3
    assert a["market_features_used"] is False
    assert a["pit_evidence"] is False
    assert a["model_p_authority"] is False
    assert a["promotion_authority"] is False
    assert a["official_authority"] is False


def test_manifest_rejects_2026_outcomes():
    import pytest
    with pytest.raises(ValueError,match="2026_OUTCOMES_PROHIBITED"):
        build_manifest(season=2026,target_week=2,datasets={},feature_names=[])
