"""Fail-closed distinction between structural market catalogs and readiness."""
import json
from pathlib import Path

import pytest

from scripts.audit_market_coverage import football_engine_capability


ROOT = Path(__file__).resolve().parents[1]


def _fixture():
    return {"sports": ["NFL", "CFB"], "markets": [
        {"family": "game", "market": "moneyline",
         "engine_state_by_sport": {"NFL": "IMPLEMENTED", "CFB": "IMPLEMENTED"}},
        {"family": "game", "market": "team_total",
         "engine_state_by_sport": {"NFL": "NO_ENGINE", "CFB": "IMPLEMENTED"}},
        {"family": "player", "market": "targets",
         "engine_state_by_sport": {"NFL": "NO_ENGINE", "CFB": "NO_ENGINE"}},
    ]}


def test_engine_availability_is_not_market_validation():
    by_sport, invalid = football_engine_capability(_fixture())
    assert not invalid
    assert by_sport["NFL"]["implemented_count"] == 1
    assert by_sport["NFL"]["no_engine_count"] == 2
    assert by_sport["CFB"]["implemented_count"] == 2
    assert by_sport["CFB"]["no_engine_count"] == 1
    assert by_sport["NFL"]["no_engine_markets"] == [
        "game:team_total", "player:targets"]
    assert by_sport["NFL"]["engine_implemented_is_market_validated"] is False
    assert by_sport["NFL"]["all_engines_present"] is False


def test_missing_or_unknown_state_is_never_counted_as_implemented():
    data = _fixture()
    data["markets"][1]["engine_state_by_sport"].pop("NFL")
    data["markets"][2]["engine_state_by_sport"]["CFB"] = "PROMOTED_BY_ODDS"
    by_sport, invalid = football_engine_capability(data)
    assert len(invalid) == 2
    assert by_sport["NFL"]["implemented_count"] == 1
    assert by_sport["NFL"]["no_engine_count"] == 1
    assert by_sport["CFB"]["implemented_count"] == 2
    assert by_sport["CFB"]["no_engine_count"] == 0
    assert by_sport["NFL"]["all_engines_present"] is False


@pytest.mark.parametrize("sports", [[], ["NFL", "NFL"], "NFL", [""], [None]])
def test_invalid_sport_shapes_fail_closed(sports):
    data = _fixture()
    data["sports"] = sports
    with pytest.raises(ValueError, match="FOOTBALL_SPORTS_INVALID"):
        football_engine_capability(data)


def test_real_config_reports_code_gaps_without_promoting_model_p():
    football = json.loads((ROOT / "config/football_market_surface.json").read_text())
    by_sport, invalid = football_engine_capability(football)
    assert not invalid
    for sport in ("NFL", "CFB"):
        state = by_sport[sport]
        assert state["declared_market_count"] == len(football["markets"])
        assert state["implemented_count"] + state["no_engine_count"] == len(football["markets"])
        assert not state["engine_implemented_is_market_validated"]
    mlb = json.loads((ROOT / "config/deployments.json").read_text())["markets"]
    assert isinstance(mlb, dict) and mlb
    assert sum(bool(x.get("eligible")) for x in mlb.values()) == 0
