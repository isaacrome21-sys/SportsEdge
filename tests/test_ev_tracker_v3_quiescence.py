import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_quiescence_is_resolved_without_manual_evidence_override():
    r = json.loads((ROOT / "config/ev_tracker_v3_quiescence_disposition.json").read_text())
    assert r["prior_state"] == "QUIESCED"
    assert r["disposition"] == "RESOLVED"
    assert r["effective_only_after_main_activation"] is True
    assert r["manual_override"] is False
    assert r["evidence_authority"] is False
