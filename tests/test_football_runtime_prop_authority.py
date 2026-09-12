import json
from pathlib import Path


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_runtime_capabilities_bind_prop_engine_authority_fail_closed():
    capabilities = _load("config/football_runtime_capabilities.json")
    authority_path = capabilities["prop_engine_authority"]
    authority = _load(authority_path)

    for sport in ("NFL", "CFB"):
        assert capabilities["prop_engine_state"][sport] == "NO_ENGINE"
        assert authority["sports"][sport]["engine_state"] == "NO_ENGINE"
        assert authority["sports"][sport]["readiness_state"] == "NO_ENGINE"

    assert capabilities["governance"]["prop_provider_capability_creates_prop_model_p"] is False
    assert capabilities["governance"]["prop_provider_capability_enables_bettor_facing_prop_lane"] is False


def test_game_market_runtime_capabilities_remain_implemented():
    capabilities = _load("config/football_runtime_capabilities.json")
    assert capabilities["game_markets"] == {
        "moneyline": "IMPLEMENTED",
        "spread": "IMPLEMENTED",
        "total": "IMPLEMENTED",
    }
