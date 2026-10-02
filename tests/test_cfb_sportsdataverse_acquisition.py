import pytest
from sportsedge.sports.cfb.sportsdataverse_acquisition import (
    SDVAcquisitionError, acquisition_plan, asset,
)

def test_frozen_plan_is_44_public_nonbetting_assets():
    plan=acquisition_plan()
    assert len(plan)==44
    assert {x.season for x in plan}==set(range(2015,2026))
    assert not any("betting" in x.dataset or "betting" in x.url for x in plan)

def test_asset_urls_match_upstream_cfbfastr_release_contract():
    assert asset("cfb_schedules",2015).url.endswith(
      "/cfb_schedules/cfb_schedules_2015.csv.gz")
    assert asset("espn_cfb_adv_team",2025).url.endswith(
      "/espn_cfb_adv_team/adv_team_2025.csv")
    assert asset("espn_cfb_adv_drives",2025).url.endswith(
      "/espn_cfb_adv_drives/adv_drives_2025.csv")
    assert asset("espn_cfb_adv_situational",2025).url.endswith(
      "/espn_cfb_adv_situational/adv_situational_2025.csv")

def test_betting_and_unregistered_sources_fail_closed():
    with pytest.raises(SDVAcquisitionError,match="BETTING_DATASET_PROHIBITED"):
        asset("espn_cfb_betting",2025)
    with pytest.raises(SDVAcquisitionError,match="NOT_ALLOWLISTED"):
        asset("something_else",2025)

def test_window_is_exactly_preregistered_history():
    with pytest.raises(SDVAcquisitionError,match="OUTSIDE_FROZEN_WINDOW"):
        asset("espn_cfb_adv_team",2026)
    with pytest.raises(SDVAcquisitionError,match="FROZEN_WINDOW_REQUIRED"):
        acquisition_plan(2016,2025)
