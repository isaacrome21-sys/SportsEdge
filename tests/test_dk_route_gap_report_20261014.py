"""Synthetic DK routing gap prioritization tests."""
import json

from sportsedge.dk_route_gap_report import build_route_gap_report


def _census(tmp_path, sports):
    path = tmp_path / "census.json"
    path.write_text(json.dumps({"schema": "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1",
                                "sports": {sport: {"markets": [{"market_key": key} for key in keys]}
                                           for sport, keys in sports.items()}}))
    return path


def test_mlb_gaps_before_nfl_and_priced_not_validated(tmp_path):
    report = build_route_gap_report(_census(tmp_path, {
        "NFL": ["SOMETHING_UNKNOWN"], "MLB": ["MONEYLINE", "UNSUPPORTED_MLB_MARKET"],
    }))
    assert report["by_sport"]["MLB"]["priced_path_not_validated"] == 1
    assert report["by_sport"]["MLB"]["no_canonical_route"] == 1
    assert report["gaps"][0]["sport"] == "MLB"
    assert report["play_authorized"] is False


def test_missing_nba_cbb_inventory_explicit(tmp_path):
    report = build_route_gap_report(_census(tmp_path, {"MLB": ["MONEYLINE"]}))
    assert report["by_sport"]["NBA"]["inventory_missing"] is True
    assert report["by_sport"]["CBB"]["inventory_missing"] is True
    assert report["by_sport"]["NBA"]["menu_markets"] == 0


def test_no_canonical_route_blocker_is_visible(tmp_path):
    report = build_route_gap_report(_census(tmp_path, {"MLB": ["UNMAPPED_PROP"]}))
    assert report["gaps"] == [{"sport": "MLB", "market": "UNMAPPED_PROP",
                                "blocker": "NO_ROUTE", "route_state": "NO_CANONICAL_ROUTE"}]
    assert report["by_sport"]["MLB"]["blockers"]["NO_ROUTE"] == 1
