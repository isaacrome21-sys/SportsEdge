"""Offline guards for the BartTorvik T-Rank LIVE-route CBB admission packet.

These tests never touch the network. They pin the admission invariants:
DESIGN-only status, hash-pinned samples on the live barttorvik.com route,
the re-pull stability pair and the disclosed inter-pull drift, the
morning-of rule and the Illinois college exclusion recorded in the doc,
and the non-admission of KenPom and of the unreachable api.cbbstat route.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "cbb_barttorvik_live_route_20261028"
MANIFEST = json.loads((PACKET / "sample_manifest.json").read_text(encoding="utf-8"))
RECORD = (PACKET / "ADMISSION_RECORD.md").read_text(encoding="utf-8")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def test_manifest_is_design_only():
    assert MANIFEST["design_only"] is True
    assert MANIFEST["validation_credit"] is False
    assert MANIFEST["forward_clock_credit"] is False
    assert MANIFEST["play_eligible"] is False
    assert MANIFEST["sport"] == "CBB"
    assert MANIFEST["source_id"] == "BARTTORVIK_TRANK_LIVE"


def test_samples_are_hash_pinned_on_the_live_route():
    assert len(MANIFEST["samples"]) >= 2
    for sample in MANIFEST["samples"]:
        assert SHA256_RE.match(sample["sha256"])
        assert sample["bytes"] > 0
        assert sample["team_rows"] > 300
        assert sample["url"] == "https://barttorvik.com/2027_team_results.csv"
        assert sample["season_year"] == 2027
        assert sample["evidence_state"] == "verified-by-pull"


def test_repull_stability_pair_and_drift_are_recorded():
    hashes = [s["sha256"] for s in MANIFEST["samples"]]
    # At least one identical re-pull pair (short-window stability) ...
    assert len(hashes) != len(set(hashes))
    # ... and at least one distinct vintage, with the drift quantified.
    assert len(set(hashes)) >= 2
    drift = MANIFEST["drift_summary"]
    assert drift["teams_compared"] == 365
    assert drift["rank_changes"] > 0
    assert "NOT byte-stable" in drift["finding"]


def test_record_states_the_binding_rules():
    lowered = RECORD.lower()
    assert "morning" in lowered
    assert "no same-day post-game data may price" in lowered
    assert "illinois college" in lowered
    assert "kenpom is not admitted" in lowered
    assert "design only" in lowered
    assert "no forward-clock credit" in lowered


def test_unreachable_and_paid_routes_are_not_admitted():
    names = [r["name"] for r in MANIFEST["routes_not_admitted"]]
    assert any("api.cbbstat.com" in n for n in names)
    assert any("KenPom" in n for n in names)


def test_all_five_routes_were_examined():
    verdicts = [r["name"] for r in MANIFEST["routes_examined"]]
    assert len(verdicts) == 5
    assert any("Route 3" in v and "barttorvik.com" in v for v in verdicts)
    assert any("Route 5" in v for v in verdicts)


def test_retrieval_script_targets_the_live_file_and_compiles():
    script = (PACKET / "pull_bart_live.py").read_text(encoding="utf-8")
    assert "barttorvik.com/{year}_team_results.csv" in script
    assert "SOURCE_CHANGED_AFTER_SNAPSHOT" in script
    compile(script, "pull_bart_live.py", "exec")
