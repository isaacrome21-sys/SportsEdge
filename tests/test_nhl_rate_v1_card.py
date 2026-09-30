from __future__ import annotations

from sportsedge.nhl_rate_v1_card import load_freeze, resolve_team, simulate_matchup


def test_freeze_loads() -> None:
    p = load_freeze()
    assert p.version == "NHL_RATE_V1_OFFICIAL_STANDIN"
    assert p.home_ice == 0.047


def test_resolve_common_names() -> None:
    assert resolve_team("Rangers") == "NYR"
    assert resolve_team("BOS") == "BOS"
    assert resolve_team("Golden Knights") == "VGK"


def test_simulation_probabilities_in_unit_interval() -> None:
    sim = simulate_matchup("Rangers", "Bruins", n=2000, seed=7)
    assert sim is not None
    assert 0.05 < sim["home_win"] < 0.95
    assert abs(sim["home_win"] + sim["away_win"] - 1.0) < 0.02
