from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nfl-location-symmetric-g1-readout.yml"


def test_development_readout_never_runs_on_pull_request():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "development-readout:" in text
    assert "if: github.event_name != 'pull_request'" in text
    assert "branches: [main]" in text


def test_readout_is_explicitly_zero_authority():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "fresh_holdout_claim" in text
    assert "prospective_validation_started" in text
    assert "production_registry_consumes_this_artifact" in text
    assert "NFL_LOCATION_G1_READOUT_ZERO_AUTHORITY" in text
