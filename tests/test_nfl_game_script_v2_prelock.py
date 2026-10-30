import json
from pathlib import Path


PRELOCK = Path("config/research/nfl_game_script_v2_prelock.json")


def test_game_script_v2_uses_fresh_fit_window_and_keeps_2025_clean():
    cfg = json.loads(PRELOCK.read_text())

    assert cfg["schema"] == "SPORTSEDGE_NFL_GAME_SCRIPT_V2_PRELOCK"
    assert cfg["status"] == "FROZEN_BEFORE_V2_SCORING"

    fit = cfg["fit_window"]["seasons"]
    exposed = cfg["excluded_from_v2_fit_or_selection"]["seasons"]

    assert fit == [2011, 2012, 2013, 2014, 2015]
    assert exposed == list(range(2016, 2025))
    assert not (set(fit) & set(exposed))

    validation = cfg["validation_window"]
    assert validation["season"] == 2025
    assert validation["one_look"] is True
    assert validation["status"] == "CLEAN_UNUSED_BY_V1"

    failed_v1 = cfg["supersedes_failed_candidate"]
    assert failed_v1["v1_validation_2025_accessed"] is False
    assert failed_v1["reuse_v1_fit_window_for_v2_fit"] is False

    model = cfg["model"]
    assert model["basis"]["fixed_knots"] == [-14, -7, 0, 7, 14]
    assert model["monotonic_constraint"] is False
    assert model["post_fit_clipping"] is False

    authority = cfg["authority"]
    assert all(value is False for value in authority.values())
