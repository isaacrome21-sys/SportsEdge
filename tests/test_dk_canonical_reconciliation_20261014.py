"""Synthetic DK-to-canonical route reconciliation tests."""
import json

import pytest

from sportsedge.dk_canonical_reconciliation import reconcile_dk_census


def _write(tmp_path, sport, markets):
    path = tmp_path / "census.json"
    path.write_text(json.dumps({
        "schema": "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1",
        "sports": {sport: {"markets": [{"market_key": k} for k in markets]}},
    }))
    return path


def test_known_mlb_market_is_not_verified(tmp_path):
    result = reconcile_dk_census(_write(tmp_path, "MLB", ["MONEYLINE"]))
    row = result["rows"][0]
    assert row["route_state"] == "PRICED_PATH"
    assert row["verified_probability"] is False
    assert row["play_authorized"] is False


def test_unknown_market_never_inherits_nearby_route(tmp_path):
    result = reconcile_dk_census(_write(tmp_path, "MLB", ["MONEYLINE_UNKNOWN"]))
    row = result["rows"][0]
    assert row["route_state"] == "NO_CANONICAL_ROUTE"
    assert row["blocker"] == "NO_ROUTE"


def test_missing_sports_explicit(tmp_path):
    result = reconcile_dk_census(_write(tmp_path, "MLB", ["MONEYLINE"]))
    assert result["missing_sport_census"] == ["NFL", "CFB", "NBA", "CBB"]


def test_duplicate_menu_market_refused(tmp_path):
    with pytest.raises(ValueError, match="DUPLICATE_MARKET_KEY"):
        reconcile_dk_census(_write(tmp_path, "MLB", ["MONEYLINE", "MONEYLINE"]))


def test_unrecognized_sport_refused(tmp_path):
    with pytest.raises(ValueError, match="UNSUPPORTED_SPORT"):
        reconcile_dk_census(_write(tmp_path, "NHL", ["MONEYLINE"]))
