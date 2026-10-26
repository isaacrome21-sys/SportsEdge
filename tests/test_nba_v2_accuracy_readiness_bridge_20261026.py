"""Regression coverage: pinned-but-unfrozen NBA V2 is additive to V1.

These are synthetic inventory fixtures; they are not betting backtests or
evidence that the V2 preregistration has been frozen.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.audit_cross_sport_accuracy_readiness import (
    AuditRefusal,
    _status,
    accuracy_readiness,
)


def _candidate_pair(tmp_path: Path) -> tuple[Path, Path, Path]:
    configs = tmp_path / "sportsedge" / "forward_validation" / "configs"
    configs.mkdir(parents=True)
    v1_text, v2_text = tmp_path / "v1.md", tmp_path / "v2.md"
    v1_text.write_bytes(b"immutable V1 document\n")
    v2_text.write_bytes(b"final candidate, NOT frozen\n")
    base = {
        "sport": "NBA",
        "family": "player_assists",
        "markets": ["player_assists"],
        "engine_id": "NBA_PROP_EMPIRICAL_V1",
        "model_version": "NBA_PROP_EMPIRICAL_V1",
        "min_rows": 100,
        "min_events": 40,
        "min_slates": 4,
        "play_authority": False,
    }
    v1 = {
        **base, "status": "FROZEN -- V1",
        "prereg": "v1.md",
        "prereg_sha256": hashlib.sha256(v1_text.read_bytes()).hexdigest(),
    }
    v2 = {
        **base, "status": "FINAL-CANDIDATE -- NOT FROZEN",
        "prereg": "v2.md",
        "prereg_sha256": hashlib.sha256(v2_text.read_bytes()).hexdigest(),
    }
    v1_path = configs / "nba_player_assists.json"
    v2_path = configs / "nba_player_assists_v2.json"
    v1_path.write_text(json.dumps(v1), encoding="utf-8")
    v2_path.write_text(json.dumps(v2), encoding="utf-8")
    return v1_path, v2_path, v2_text


def test_pinned_candidate_remains_unfrozen_and_v1_registration_survives(tmp_path):
    _candidate_pair(tmp_path)
    report = accuracy_readiness(root=tmp_path)
    states = report["forward_config_states"]["NBA"]
    assert states["FROZEN_NO_VERDICT_ATTACHED"] == 1
    assert states["FINAL_CANDIDATE_NOT_FROZEN"] == 1
    assert report["forward_family_config_count"] == 2
    assert report["validated_families_conferred"] == 0
    assert report["play_authority_conferred"] is False
    assert [x["state"] for x in report["forward_family_configs"]] == [
        "FROZEN_NO_VERDICT_ATTACHED", "FINAL_CANDIDATE_NOT_FROZEN",
    ]


def test_real_v2_inventory_never_confers_counting_authority():
    report = accuracy_readiness()
    states = report["forward_config_states"]["NBA"]
    assert states["FINAL_CANDIDATE_NOT_FROZEN"] == 4
    assert states["FROZEN_NO_VERDICT_ATTACHED"] >= 4
    assert report["play_authority_conferred"] is False
    assert report["validated_families_conferred"] == 0


def test_candidate_document_tamper_fails_closed(tmp_path):
    _, _, doc = _candidate_pair(tmp_path)
    doc.write_bytes(doc.read_bytes() + b"tamper")
    with pytest.raises(AuditRefusal, match="PREREG_SHA_MISMATCH"):
        accuracy_readiness(root=tmp_path)


@pytest.mark.parametrize("field,value", [
    ("min_rows", 99),
    ("model_version", "UNREGISTERED"),
    ("engine_id", "DIFFERENT"),
])
def test_v2_amendment_cannot_drift_pricing_or_gate_terms(tmp_path, field, value):
    _, path, _ = _candidate_pair(tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc[field] = value
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(AuditRefusal, match="DUPLICATE_FORWARD_MARKET_CONFIG"):
        accuracy_readiness(root=tmp_path)


def test_arbitrary_second_config_cannot_overwrite_frozen_v1(tmp_path):
    _, path, _ = _candidate_pair(tmp_path)
    path.rename(path.with_name("nba_player_assists_extra.json"))
    with pytest.raises(AuditRefusal, match="DUPLICATE_FORWARD_MARKET_CONFIG"):
        accuracy_readiness(root=tmp_path)


@pytest.mark.parametrize("row,reason", [
    ({"status": "FINAL-CANDIDATE -- NOT FROZEN"}, "FINAL_CANDIDATE_PREREG_MISSING"),
    ({"status": "FINAL-CANDIDATE -- NOT FROZEN", "prereg": "v2.md"}, "FINAL_CANDIDATE_SHA_MISSING"),
    ({"status": "FINAL-CANDIDATE -- NOT FROZEN", "prereg": "v2.md",
      "prereg_sha256": "0" * 64}, "PREREG_SHA_MISMATCH"),
])
def test_unpinned_candidate_never_passes_audit(tmp_path, row, reason):
    (tmp_path / "v2.md").write_bytes(b"candidate")
    with pytest.raises(AuditRefusal, match=reason):
        _status(row, name="candidate", root=tmp_path)
