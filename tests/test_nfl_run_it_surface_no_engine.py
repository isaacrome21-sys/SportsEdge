import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_IT_SURFACE = ROOT / "config/run_it_surface.json"
PROP_SURFACE = ROOT / "config/football_prop_engine_surface.json"


def test_nfl_run_it_surface_matches_prop_no_engine_authority():
    run_it = json.loads(RUN_IT_SURFACE.read_text(encoding="utf-8"))
    props = json.loads(PROP_SURFACE.read_text(encoding="utf-8"))

    nfl_run_it = run_it["sports"]["NFL"]
    nfl_props = props["sports"]["NFL"]

    assert nfl_props["engine_state"] == "NO_ENGINE"
    assert nfl_props["readiness_state"] == "NO_ENGINE"
    assert nfl_run_it["governance_source"] == "config/football_prop_engine_surface.json"
    assert "PROPS_NO_ENGINE" in nfl_run_it["lane"]
    assert "NFL_PROPS_NO_ENGINE" in nfl_run_it["blocker"]
    assert "PLAYER_PROPS lane is intentionally emitted as blocked NO_ENGINE" in nfl_run_it["notes"]
    assert "cannot create NFL prop Model_P" in nfl_run_it["notes"]
