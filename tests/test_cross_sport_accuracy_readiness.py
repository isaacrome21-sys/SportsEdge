"""Evidence inventory cannot confuse test registration with model accuracy."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts.audit_cross_sport_accuracy_readiness import (
    ROOT, AuditRefusal, _status, accuracy_readiness,
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


def test_v2_configs_register_as_frozen_no_verdict():
    report = accuracy_readiness()
    states = report["forward_config_states"]["NBA"]
    assert states.get("FINAL_CANDIDATE_NOT_FROZEN", 0) == 0
    rows = [r for r in report["forward_family_configs"]
            if r["file"].endswith("_v2.json")]
    assert len(rows) == 4
    assert all(r["state"] == "FROZEN_NO_VERDICT_ATTACHED" for r in rows)
    # recognition in this inventory confers nothing: no family becomes
    # validated and no registered config grants play authority
    assert report["validated_families_conferred"] == 0
    assert all(r["play_authority_from_config"] is False for r in rows)


def _synthetic_root(tmp_path, configs):
    config_dir = tmp_path / "sportsedge" / "forward_validation" / "configs"
    config_dir.mkdir(parents=True)
    for name, doc in configs.items():
        (config_dir / name).write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def _v2_config():
    path = (ROOT / "sportsedge" / "forward_validation" / "configs"
            / "nba_player_points_v2.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _with_v2_prereg(root):
    doc = (ROOT / "research" / "nba_props_forward_20261020"
           / "PREREG_NBA_PROPS_FORWARD_V2.md").read_bytes()
    target = (root / "research" / "nba_props_forward_20261020"
              / "PREREG_NBA_PROPS_FORWARD_V2.md")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(doc)


def test_unregistered_status_refused_at_inventory_level(tmp_path):
    doc = {"sport": "NBA", "family": "player_points",
           "markets": ["player_points"], "status": "PREPARED — TRUST ME"}
    root = _synthetic_root(tmp_path, {"synthetic_v9.json": doc})
    with pytest.raises(AuditRefusal,
                       match="UNKNOWN_CONFIG_STATUS:synthetic_v9.json"):
        accuracy_readiness(root=root)


def test_same_state_duplicate_market_still_refused(tmp_path):
    # Versioned coexistence (a frozen test beside a pinned candidate for
    # the same market) registers; two configs in the SAME state claiming
    # one market remain an ambiguous registration and refuse.
    doc = {"sport": "MLB", "family": "game_lines",
           "markets": ["game_total"], "status": "DRAFT — NOT FROZEN",
           "prereg_draft": "draft.md"}
    root = _synthetic_root(tmp_path, {"a.json": doc, "b.json": dict(doc)})
    (root / "draft.md").write_text("draft prereg", encoding="utf-8")
    with pytest.raises(AuditRefusal, match="DUPLICATE_FORWARD_MARKET_CONFIG"):
        accuracy_readiness(root=root)


def test_frozen_registration_is_exact(tmp_path):
    config = _v2_config()
    # intact frozen config: the real V2 config and its pinned
    # document register under their true state — frozen, no verdict
    root = _synthetic_root(tmp_path / "intact",
                           {"nba_player_points_v2.json": config})
    _with_v2_prereg(root)
    report = accuracy_readiness(root=root)
    (row,) = report["forward_family_configs"]
    assert row["state"] == "FROZEN_NO_VERDICT_ATTACHED"

    # registration entry removed (the document pin): fails closed
    unpinned = dict(config)
    del unpinned["prereg_sha256"]
    root = _synthetic_root(tmp_path / "unpinned",
                           {"nba_player_points_v2.json": unpinned})
    _with_v2_prereg(root)
    with pytest.raises(AuditRefusal, match="FROZEN_PREREG_SHA_MISSING"):
        accuracy_readiness(root=root)

    # a pin that does not match the document: fails closed
    wrong = dict(config, prereg_sha256="0" * 64)
    root = _synthetic_root(tmp_path / "wrongpin",
                           {"nba_player_points_v2.json": wrong})
    _with_v2_prereg(root)
    with pytest.raises(AuditRefusal, match="PREREG_SHA_MISMATCH"):
        accuracy_readiness(root=root)

    # the FINAL-CANDIDATE label without the NOT FROZEN declaration is
    # not a registered status at all
    relabeled = dict(config, status="FINAL-CANDIDATE — READY WHEN WE ARE")
    root = _synthetic_root(tmp_path / "relabeled",
                           {"nba_player_points_v2.json": relabeled})
    _with_v2_prereg(root)
    with pytest.raises(AuditRefusal, match="UNKNOWN_CONFIG_STATUS"):
        accuracy_readiness(root=root)
