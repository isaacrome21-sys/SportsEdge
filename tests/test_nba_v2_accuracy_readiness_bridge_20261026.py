"""The NBA V2 source amendment must be additive, pinned and uncounted.

Synthetic structural inventory probes only; no market/backtest claims.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.audit_cross_sport_accuracy_readiness import (
    AuditRefusal, _status, accuracy_readiness,
)


def _pair(tmp_path: Path) -> tuple[Path, Path]:
    config_dir = tmp_path / "sportsedge" / "forward_validation" / "configs"
    config_dir.mkdir(parents=True)
    v1_doc, v2_doc = tmp_path / "v1.md", tmp_path / "v2.md"
    v1_doc.write_bytes(b"immutable frozen V1\n")
    v2_doc.write_bytes(b"final candidate not frozen V2\n")
    terms = {
        "sport": "NBA", "family": "player_assists",
        "markets": ["player_assists"],
        "engine_id": "NBA_PROP_EMPIRICAL_V1",
        "model_version": "NBA_PROP_EMPIRICAL_V1",
        "market_form": "TWO_SIDED", "sides": ["OVER", "UNDER"],
        "min_rows": 100, "min_events": 40, "min_slates": 4,
        "close_max_age_minutes": 60, "play_authority": False,
    }
    v1 = {
        **terms, "status": "FROZEN — V1",
        "prereg": "v1.md",
        "prereg_sha256": hashlib.sha256(v1_doc.read_bytes()).hexdigest(),
    }
    v2 = {
        **terms, "status": "FINAL-CANDIDATE -- NOT FROZEN",
        "prereg": "v2.md",
        "prereg_sha256": hashlib.sha256(v2_doc.read_bytes()).hexdigest(),
    }
    v1_file = config_dir / "nba_player_assists.json"
    v2_file = config_dir / "nba_player_assists_v2.json"
    v1_file.write_text(json.dumps(v1))
    v2_file.write_text(json.dumps(v2))
    return v2_file, v2_doc


def test_additive_pinned_unfrozen_v2_keeps_v1_canonical(tmp_path):
    _pair(tmp_path)
    report = accuracy_readiness(root=tmp_path)
    states = report["forward_config_states"]["NBA"]
    assert states["FROZEN_NO_VERDICT_ATTACHED"] == 1
    assert states["FINAL_CANDIDATE_NOT_FROZEN"] == 1
    assert report["forward_family_config_count"] == 2
    assert report["validated_families_conferred"] == 0
    assert report["play_authority_conferred"] is False
    assert any(row["file"].endswith("nba_player_assists.json")
               for row in report["forward_family_configs"])


def test_current_repo_has_four_frozen_pinned_v2_configs():
    # Post-freeze form: the four V2 configs register in the frozen
    # state (FROZEN_NO_VERDICT_ATTACHED), exactly 4 of them, with
    # zero candidate-state registrations anywhere in the NBA states,
    # and each config's pin present and matching the frozen document.
    report = accuracy_readiness()
    states = report["forward_config_states"]["NBA"]
    assert states.get("FINAL_CANDIDATE_NOT_FROZEN", 0) == 0
    rows = [r for r in report["forward_family_configs"]
            if r["file"].endswith("_v2.json") and r["sport"] == "NBA"]
    assert len(rows) == 4
    assert all(r["state"] == "FROZEN_NO_VERDICT_ATTACHED" for r in rows)
    assert report["validated_families_conferred"] == 0
    assert report["play_authority_conferred"] is False
    # pin present and matching, checked independently of the audit:
    # every V2 config carries a 64-char prereg_sha256 equal to the
    # sha256 of the frozen document it names.
    root = Path(__file__).resolve().parents[1]
    config_dir = root / "sportsedge" / "forward_validation" / "configs"
    for path in sorted(config_dir.glob("nba_player_*_v2.json")):
        config = json.loads(path.read_text(encoding="utf-8"))
        sha = config.get("prereg_sha256")
        assert isinstance(sha, str) and len(sha) == 64
        doc = (root / config["prereg"]).read_bytes()
        assert hashlib.sha256(doc).hexdigest() == sha


@pytest.mark.parametrize("field,value", [
    ("engine_id", "DIFFERENT_ENGINE"),
    ("model_version", "DIFFERENT_MODEL"),
    ("min_rows", 99),
    ("min_events", 39),
    ("min_slates", 3),
    ("close_max_age_minutes", 300),
    ("play_authority", True),
])
def test_drifted_v2_engine_or_gate_is_never_additive(tmp_path, field, value):
    v2_file, _ = _pair(tmp_path)
    record = json.loads(v2_file.read_text())
    record[field] = value
    v2_file.write_text(json.dumps(record))
    with pytest.raises(AuditRefusal, match="DUPLICATE_FORWARD_MARKET_CONFIG"):
        accuracy_readiness(root=tmp_path)


def test_arbitrary_renamed_duplicate_cannot_replace_v1(tmp_path):
    v2_file, _ = _pair(tmp_path)
    v2_file.rename(v2_file.with_name("nba_player_assists_extra.json"))
    with pytest.raises(AuditRefusal, match="DUPLICATE_FORWARD_MARKET_CONFIG"):
        accuracy_readiness(root=tmp_path)


def test_tampered_v2_prereg_is_refused(tmp_path):
    _, doc = _pair(tmp_path)
    doc.write_bytes(doc.read_bytes() + b"tampered")
    with pytest.raises(AuditRefusal, match="PREREG_SHA_MISMATCH"):
        accuracy_readiness(root=tmp_path)


@pytest.mark.parametrize("patch,reason", [
    ({"prereg": None}, "CANDIDATE_PREREG_MISSING"),
    ({"prereg_sha256": None}, "CANDIDATE_PREREG_SHA_MISSING"),
    ({"prereg_sha256": "0" * 64}, "PREREG_SHA_MISMATCH"),
])
def test_missing_or_mismatched_candidate_pin_fails_closed(tmp_path, patch, reason):
    v2_file, _ = _pair(tmp_path)
    record = json.loads(v2_file.read_text())
    record.update(patch)
    v2_file.write_text(json.dumps(record))
    with pytest.raises(AuditRefusal, match=reason):
        accuracy_readiness(root=tmp_path)


def test_candidate_status_parser_never_confers_freeze(tmp_path):
    _, doc = _pair(tmp_path)
    row = {"status": "FINAL-CANDIDATE -- NOT FROZEN",
           "prereg": "v2.md",
           "prereg_sha256": hashlib.sha256(doc.read_bytes()).hexdigest()}
    assert _status(row, name="v2", root=tmp_path) == "FINAL_CANDIDATE_NOT_FROZEN"
