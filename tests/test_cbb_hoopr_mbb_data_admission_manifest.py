"""Offline guards for the hoopR MBB substrate CBB admission packet.

These tests never touch the network. They pin the admission invariants:
DESIGN-only status, full pin tuples (rolling release tags pin nothing by
themselves), the crosswalk recorded as an OPEN, unadmitted item, the
Illinois college exclusion, and the non-admission of KenPom.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "cbb_hoopr_mbb_data_admission_20261027"
MANIFEST = json.loads((PACKET / "sample_manifest.json").read_text(encoding="utf-8"))
RECORD = (PACKET / "ADMISSION_RECORD.md").read_text(encoding="utf-8")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def test_manifest_is_design_only():
    assert MANIFEST["design_only"] is True
    assert MANIFEST["validation_credit"] is False
    assert MANIFEST["forward_clock_credit"] is False
    assert MANIFEST["play_eligible"] is False
    assert MANIFEST["sport"] == "CBB"


def test_every_sample_carries_a_full_pin_tuple():
    assert len(MANIFEST["samples"]) >= 4
    for sample in MANIFEST["samples"]:
        assert isinstance(sample["asset_id"], int)
        assert isinstance(sample["release_id"], int)
        assert SHA256_RE.match(sample["sha256"])
        assert sample["bytes"] > 0
        assert sample["release_tag"] in sample["url"]
        assert sample["asset_name"] in sample["url"]
        assert sample["asset_updated_at"]


def test_schedule_content_check_is_recorded():
    sched = [s for s in MANIFEST["samples"] if s["asset_name"] == "mbb_schedule_2027.csv"]
    assert len(sched) == 1
    assert "1,629 rows" in sched[0]["content_check"]
    assert "2026-11-01 = 0" in sched[0]["content_check"]


def test_crosswalk_is_open_and_not_admitted():
    assert MANIFEST["crosswalk_status"] == "OPEN_NOT_ADMITTED"
    lowered = RECORD.lower()
    assert "open item" in lowered
    assert "no mappings are invented" in lowered
    assert "name-only joins are refused" in lowered


def test_record_states_the_binding_rules():
    lowered = RECORD.lower()
    assert "rolling" in lowered
    assert "source_changed_after_snapshot" in lowered
    assert "illinois college" in lowered
    assert "kenpom is not admitted" in lowered
    assert "design only" in lowered
    assert "not an admitted slate" in lowered


def test_verification_script_compiles_and_uses_manifest():
    script = (PACKET / "pull_hoopr_mbb_samples.py").read_text(encoding="utf-8")
    assert "sample_manifest.json" in script
    assert "SOURCE_CHANGED_AFTER_SNAPSHOT" in script
    compile(script, "pull_hoopr_mbb_samples.py", "exec")
