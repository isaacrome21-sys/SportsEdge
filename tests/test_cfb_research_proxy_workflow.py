from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_research_surface_declares_proxy_without_engine_promotion():
    surface = json.loads(
        (ROOT / "config/cfb_research_market_surface_v1.json").read_text()
    )
    lane = surface["player_prop_lane"]
    proxy = lane["automatic_same_day_proxy"]
    assert lane["production_engine_state"] == "NO_ENGINE"
    assert proxy["status"] == "RESEARCH_PROXY_AVAILABLE"
    assert proxy["market_prices_consumed_to_build_usage"] is False
    assert proxy["production_eligible"] is False
    assert proxy["official_eligible"] is False
    assert "snap_share=1.0_NOT_OBSERVED_SNAP_RATE" in proxy["neutral_assumptions"]


def test_same_day_workflow_builds_usage_before_market_prices_and_props():
    text = (ROOT / ".github/workflows/cfb-today-research-card.yml").read_text()
    proxy = text.index("Build automatic market-blind research proxy usage")
    game_market = text.index("Build exact-line game market context")
    prop_market = text.index("Run frozen CFB prop research candidate")
    assert proxy < game_market < prop_market
    assert "sportsedge-paid-odds-api" in text
    assert "cfb_prop_live_features.json" in text
