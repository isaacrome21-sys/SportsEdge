"""Synthetic research-only contract tests: no odds or real-world claims."""
import json

import pytest

from sportsedge.dk_market_coverage_contract import (
    REQUIRED_EVIDENCE, adjudicate_market, inspect_census,
)


def test_menu_does_not_verify_engine(tmp_path):
    path = tmp_path / "census.json"
    path.write_text(json.dumps({"schema": "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1",
        "sports": {"MLB": {"markets": [{"market_key": "MONEYLINE", "group": "game"}]}}}))
    result = inspect_census(path)
    assert result["rows"][0]["status"] == "UNVERIFIED"
    assert result["rows"][0]["missing_evidence"] == list(REQUIRED_EVIDENCE)
    assert result["missing_sport_census"] == ["NFL", "CFB", "NBA", "CBB"]


def test_duplicate_market_key_refused(tmp_path):
    path = tmp_path / "census.json"
    path.write_text(json.dumps({"schema": "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1",
        "sports": {"MLB": {"markets": [{"market_key": "X"}, {"market_key": "X"}]}}}))
    with pytest.raises(ValueError, match="DUPLICATE_MARKET_KEY"):
        inspect_census(path)


@pytest.mark.parametrize("bad", ["", None, 42])
def test_invalid_market_key_refused(tmp_path, bad):
    path = tmp_path / "census.json"
    path.write_text(json.dumps({"schema": "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1",
        "sports": {"MLB": {"markets": [{"market_key": bad}]}}}))
    with pytest.raises(ValueError, match="INVALID_MARKET_KEY"):
        inspect_census(path)


def test_partial_evidence_cannot_pass():
    evidence = {key: True for key in REQUIRED_EVIDENCE}
    evidence["paired_fresh_quotes"] = False
    result = adjudicate_market(evidence)
    assert result["status"] == "UNVERIFIED"
    assert "paired_fresh_quotes" in result["missing_evidence"]
    assert result["play_authorized"] is False


def test_complete_evidence_still_requires_review():
    result = adjudicate_market({key: True for key in REQUIRED_EVIDENCE})
    assert result["status"] == "EVIDENCE_COMPLETE_REVIEW_REQUIRED"
    assert result["play_authorized"] is False
