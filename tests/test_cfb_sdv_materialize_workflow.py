from pathlib import Path


def test_sdv_materialization_workflow_is_zero_attempt_only():
    text=Path(".github/workflows/cfb-sdv-materialize-training.yml").read_text()
    assert "workflow_dispatch:" in text
    assert "scripts/acquire_cfb_sportsdataverse_training_inputs.py" in text
    assert "scripts/materialize_cfb_sportsdataverse_training.py" in text
    assert "history/cfb/sportsdataverse-selection" in text
    assert "training_rows.json" in text
    assert "CFBD_API_KEY" in text
    assert "SPORTSEDGE_ODDS_API_KEY" not in text
    assert "ODDS_API_KEY" not in text
    assert "run_cfb_sportsdataverse_bakeoff.py" not in text
    assert "CONSUME_ALL_FOUR_CFB_SDV_ATTEMPTS" not in text
