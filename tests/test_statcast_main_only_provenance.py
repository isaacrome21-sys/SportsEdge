import json
from pathlib import Path


WORKFLOW = Path(".github/workflows/statcast-daily-refresh.yml")
CONTRACT = Path("config/mlb_source_freshness_contract.json")


def test_statcast_durable_writer_is_main_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "branches: [main]" in text
    assert "if: github.ref == 'refs/heads/main'" in text
    assert "Record merged-main provenance" in text
    assert "eligible_for_forward_evaluation" in text
    assert '"head_branch": "main"' in text


def test_statcast_acceptance_requires_provenance_receipt():
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    required = payload["collector_promotion"]["required_non_empty_artifacts"]["statcast-daily-refresh"]
    assert required == ["manifest.json", "batters.json", "pitchers.json", "provenance.json"]
