"""Explicit DK menu aliases are identities, not verified live prices."""
import json

import pytest

from sportsedge.dk_canonical_reconciliation import reconcile_dk_census


@pytest.mark.parametrize("key,canonical", [
    ("GAME_TOTAL_RUNS", "TOTALS"),
    ("TEAM_TOTAL_RUNS", "TEAM_TOTALS"),
    ("BATTER_HITS", "HITS"),
    ("BATTER_WALKS", "BATTER_BB"),
    ("BATTER_HITS_RUNS_RBI", "HITS_RUNS_RBIS"),
    ("F5_TEAM_TOTAL_RUNS", "F5_TEAM_TOTALS"),
])
def test_explicit_alias_does_not_authorize_play(tmp_path, key, canonical):
    path = tmp_path / "census.json"
    path.write_text(json.dumps({"schema": "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1",
                                "sports": {"MLB": {"markets": [{"market_key": key}]}}}))
    row = reconcile_dk_census(path)["rows"][0]
    assert row["canonical_market"] == canonical
    assert row["verified_probability"] is False
    assert row["play_authorized"] is False


def test_unknown_similar_market_never_aliases(tmp_path):
    path = tmp_path / "census.json"
    path.write_text(json.dumps({"schema": "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1",
                                "sports": {"MLB": {"markets": [
                                    {"market_key": "BATTER_HITS_PLUS"},
                                ]}}}))
    assert reconcile_dk_census(path)["rows"][0]["route_state"] == "NO_CANONICAL_ROUTE"
