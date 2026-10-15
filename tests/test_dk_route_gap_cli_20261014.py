"""Read-only DK gap CLI synthetic smoke tests."""
import json

from sportsedge.dk_route_gap_cli import main


def test_cli_reports_gaps_and_never_authorizes_play(tmp_path, capsys):
    path = tmp_path / "menu.json"
    path.write_text(json.dumps({
        "schema": "SPORTSEDGE_DK_INSPECTED_MENU_CENSUS_V1",
        "sports": {"MLB": {"markets": [
            {"market_key": "GAME_TOTAL_RUNS"},
            {"market_key": "INNING_2_MARKETS", "provisional_group": True},
            {"market_key": "UNKNOWN_MARKET"},
        ]}},
    }))
    assert main([str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["play_authorized"] is False
    assert result["by_sport"]["MLB"]["priced_path_not_validated"] == 1
    assert result["by_sport"]["MLB"]["provisional_not_a_market"] == 1
    assert result["by_sport"]["MLB"]["no_canonical_route"] == 1
