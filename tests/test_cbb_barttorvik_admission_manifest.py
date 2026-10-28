"""Offline guards for the BartTorvik T-Rank CBB admission packet.

These tests never touch the network. They pin the admission invariants:
DESIGN-only status, hash-pinned samples on the pinned-commit route, the
morning-of rule and the Illinois college exclusion recorded in the doc,
and the non-admission of KenPom and of the unprobed api.cbbstat route.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "cbb_barttorvik_admission_20261027"
MANIFEST = json.loads((PACKET / "sample_manifest.json").read_text(encoding="utf-8"))
RECORD = (PACKET / "ADMISSION_RECORD.md").read_text(encoding="utf-8")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def test_manifest_is_design_only():
    assert MANIFEST["design_only"] is True
    assert MANIFEST["validation_credit"] is False
    assert MANIFEST["forward_clock_credit"] is False
    assert MANIFEST["play_eligible"] is False
    assert MANIFEST["sport"] == "CBB"


def test_samples_are_hash_pinned_on_the_pinned_commit():
    assert len(MANIFEST["samples"]) >= 2
    commit = MANIFEST["admitted_route"]["pinned_commit"]
    assert len(commit) == 40
    for sample in MANIFEST["samples"]:
        assert SHA256_RE.match(sample["sha256"])
        assert sample["bytes"] > 0
        assert sample["team_rows"] > 300
        assert commit in sample["url"]
        assert sample["evidence_state"] == "verified-by-pull"


def test_coverage_limitation_is_recorded():
    probes = {p["archive_date"]: p["result"] for p in MANIFEST["coverage_probes"]}
    assert probes["2024-03-01"] == "HTTP 404"
    assert probes["2025-11-03"] == "HTTP 404"


def test_record_states_the_binding_rules():
    lowered = RECORD.lower()
    assert "morning of" in lowered
    assert "no same-day post-game data may price" in lowered
    assert "illinois college" in lowered
    assert "kenpom is not admitted" in lowered
    assert "design only" in lowered
    assert "no forward-clock credit" in lowered


def test_unprobed_route_is_not_admitted():
    names = [r["name"] for r in MANIFEST["routes_not_admitted"]]
    assert any("api.cbbstat.com" in n for n in names)
    assert any("KenPom" in n for n in names)


def test_retrieval_script_is_pinned_and_compiles():
    script = (PACKET / "pull_bart_archive.py").read_text(encoding="utf-8")
    assert MANIFEST["admitted_route"]["pinned_commit"] in script
    compile(script, "pull_bart_archive.py", "exec")
