"""Evidence inventory cannot confuse test registration with model accuracy."""

from hashlib import sha256
from pathlib import Path

import pytest

from scripts.audit_cross_sport_accuracy_readiness import (
    AuditRefusal, _status, accuracy_readiness,
)
from sportsedge.canonical_coverage import MARKET_RESOLUTIONS


def test_current_inventory_is_complete_for_its_declared_scope():
    report = accuracy_readiness()
    assert report["canonical_market_count"] == len(MARKET_RESOLUTIONS)
    assert len(report["canonical_markets"]) == report["canonical_market_count"]
    assert len(report["forward_family_configs"]) == report["forward_family_config_count"]
    assert report["canonical_by_sport"]["MLB"] > 0
    assert report["canonical_by_sport"]["NFL"] > 0
    assert report["forward_config_states"]["NBA"]["FROZEN_NO_VERDICT_ATTACHED"] > 0
    assert report["forward_config_states"]["MLB"]["DRAFT_NOT_FROZEN"] > 0
    assert report["validated_families_conferred"] == 0
    assert report["play_authority_conferred"] is False
    assert all(not row["validated_accuracy_in_this_audit"] for row in report["canonical_markets"])


def test_word_frozen_inside_not_frozen_does_not_start_clock(tmp_path):
    path = Path("draft.md")
    (tmp_path / path).write_text("not a frozen prereg", encoding="utf-8")
    row = {"status": "DRAFT — NOT FROZEN", "prereg_draft": str(path)}
    assert _status(row, name="draft", root=tmp_path) == "DRAFT_NOT_FROZEN"


def test_first_inning_sides_share_existing_draft_without_promotion():
    report = accuracy_readiness()
    sides = [r for r in report["canonical_markets"]
             if r["sport"] == "MLB" and r["market"] in ("NRFI", "YRFI")]
    assert len(sides) == 2
    for row in sides:
        assert row["forward_test_config"] == "mlb_first_inning_run.json"
        assert row["readiness"] == "RESEARCH_PRICED_NOT_VALIDATED"
        assert row["validated_accuracy_in_this_audit"] is False
        assert row["play_authority_from_readiness"] is False
    configs = [r for r in report["forward_family_configs"]
               if r["family"] == "FIRST_INNING_RUN"]
    assert len(configs) == 1
    assert configs[0]["state"] == "DRAFT_NOT_FROZEN"
    assert report["canonical_missing_forward_config_count"] == sum(
        row["forward_test_config"] is None for row in report["canonical_markets"])


def test_frozen_identity_requires_exact_prereg_sha(tmp_path):
    path = Path("frozen.md")
    original = b"frozen text with no retrospective edits\n"
    (tmp_path / path).write_bytes(original)
    row = {"status": "FROZEN — TEST", "prereg": str(path),
           "prereg_sha256": sha256(original).hexdigest()}
    assert _status(row, name="lock", root=tmp_path) == "FROZEN_NO_VERDICT_ATTACHED"
    (tmp_path / path).write_bytes(b"retuned after looking at results\n")
    with pytest.raises(AuditRefusal, match="PREREG_SHA_MISMATCH"):
        _status(row, name="lock", root=tmp_path)


def test_frozen_without_hash_or_with_path_escape_refused(tmp_path):
    (tmp_path / "p.md").write_text("p", encoding="utf-8")
    with pytest.raises(AuditRefusal, match="FROZEN_PREREG_SHA_MISSING"):
        _status({"status": "FROZEN", "prereg": "p.md"},
                name="no-hash", root=tmp_path)
    with pytest.raises(AuditRefusal, match="PREREG_PATH_NOT_RELATIVE"):
        _status({"status": "DRAFT — NOT FROZEN", "prereg_draft": "../escape.md"},
                name="escape", root=tmp_path)


def test_unknown_status_cannot_be_called_a_validated_model(tmp_path):
    with pytest.raises(AuditRefusal, match="UNKNOWN_CONFIG_STATUS"):
        _status({"status": "BEATS_MARKET"}, name="invented", root=tmp_path)
