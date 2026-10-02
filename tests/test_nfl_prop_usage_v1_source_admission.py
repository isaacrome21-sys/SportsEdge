import json
from pathlib import Path

from scripts.probe_nfl_prop_usage_v1_sources import (
    extract_week,
    parse_player_bullet,
    team_from_heading,
)

CONFIG = Path("config/research/nfl_prop_usage_v1_source_admission.json")

def test_source_admission_keeps_frozen_windows_and_no_scoring():
    cfg = json.loads(CONFIG.read_text())
    assert cfg["fit_window"]["seasons"] == [2021, 2022, 2023, 2024]
    assert cfg["validation_window"]["season"] == 2025
    assert cfg["validation_window"]["one_look"] is True
    assert cfg["validation_window"]["model_scoring_spent"] is False
    assert cfg["market_gate"]["allow_actual_value_as_model_input"] is False
    assert cfg["market_gate"]["allow_hit_over_as_model_input"] is False
    assert cfg["inactive_source"]["required_2025_schedule_team_week_coverage"] == 1.0
    assert cfg["lineup_rule"]["no_inactive_or_starter_evidence"] == "ZERO_MODEL_ROWS"

def test_inactive_parser_contract():
    assert extract_week("NFL Week 7 inactives") == 7
    assert extract_week("NFL postseason inactives") is None
    assert team_from_heading("Chicago Bears") == "CHI"
    assert team_from_heading("Los Angeles Rams") == "LAR"
    assert parse_player_bullet("QB Caleb Example") == ("QB", "Caleb Example")
    assert parse_player_bullet("WHERE: Chicago") is None
