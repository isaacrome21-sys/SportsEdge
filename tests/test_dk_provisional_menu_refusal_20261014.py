"""Provisional DK menu groups are not independently priceable markets."""
import json

from sportsedge.dk_canonical_reconciliation import reconcile_dk_census
from sportsedge.dk_route_gap_report import build_route_gap_report


def test_provisional_menu_group_never_gets_a_route(tmp_path):
    path = tmp_path / "census.json"
    path.write_text(json.dumps({
        "schema": "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1",
        "sports": {"MLB": {"markets": [
            {"market_key": "MONEYLINE", "provisional_group": True},
            {"market_key": "RUN_LINE"},
        ]}},
    }))
    result = reconcile_dk_census(path)
    assert result["rows"][0]["route_state"] == "PROVISIONAL_NOT_A_MARKET"
    assert result["rows"][0]["blocker"] == "NO_NORMALIZED_MARKET_ID"
    assert result["rows"][0]["play_authorized"] is False
    assert result["rows"][1]["route_state"] == "PRICED_PATH"
    report = build_route_gap_report(path)
    assert report["by_sport"]["MLB"]["provisional_not_a_market"] == 1
    assert report["by_sport"]["MLB"]["priced_path_not_validated"] == 1
