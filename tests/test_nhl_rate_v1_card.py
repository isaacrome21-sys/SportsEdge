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


def test_away_team_strength_moves_win_probability() -> None:
    from sportsedge.nhl_rate_v1_card import simulate_matchup as sim
    strong_away = sim("COL", "SJS")
    weak_away = sim("SJS", "COL")
    assert strong_away is not None and weak_away is not None
    # Swapping venues must flip who is favored, not leave home at ~52% both ways.
    assert strong_away["away_win"] > 0.5 > weak_away["away_win"]


def test_total_push_mass_on_integer_line() -> None:
    from sportsedge.nhl_rate_v1_card import final_score_distribution, total_probs
    fsd = final_score_distribution("Rangers", "Bruins")
    over, push, under = total_probs(fsd, 6.0)
    assert push > 0.05
    assert abs(over + push + under - 1.0) < 1e-9
    assert total_probs(fsd, 5.5)[1] == 0.0


def test_puck_line_sign_convention() -> None:
    from sportsedge.nhl_rate_v1_card import final_score_distribution, puck_line_probs
    fsd = final_score_distribution("Rangers", "Bruins")
    away_plus, _, home_minus = puck_line_probs(fsd, 1.5)
    away_minus, _, home_plus = puck_line_probs(fsd, -1.5)
    assert away_plus > 0.5 > away_minus
    assert abs(away_plus + home_minus - 1.0) < 1e-9


def test_card_never_says_bet_without_validation() -> None:
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "render_nhl", Path(__file__).resolve().parents[1] / "scripts" / "render_nhl_myspari_card.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from sportsedge.nhl_rate_v1_card import final_score_distribution
    assert mod.VALIDATED_BET_MARKETS == frozenset()
    fsd = final_score_distribution("Utah", "Sharks")
    row = mod.price_row("TOTAL", 7.0, -110, -110, fsd) + mod.price_row("PUCK_LINE", 1.5, -250, +200, fsd)
    assert "BET" not in row.replace("LEAN", "")
    assert mod.price_row("MONEYLINE", None, 120, -142, fsd) == mod.ML_HOLD
