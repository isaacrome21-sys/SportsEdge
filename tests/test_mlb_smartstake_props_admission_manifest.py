"""Offline guards for the SmartStake MLB player-props admission packet.

These tests never touch the network. They pin the admission invariants:
ADMITTED at DESIGN/SCREEN scope only (no validation credit, no forward
clock credit, no play eligibility), the canonical Hugging Face dataset
pinned at one revision, all 18 parquet partitions pinned by sha256 equal
to the canonical LFS oid published at that revision, the dataset-card
schema as the pinned schema (the PR #2850 draft's "observed schema" is
NOT admitted), the six canonical markets, DraftKings present in every
partition, the hunt-pin reconciliation (1 reproduced, 3 not reproduced),
the measured result consistency (93,929 groups, 0 disagreeing), and the
census agreeing with the manifest partition by partition.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "mlb_smartstake_props_admission_20261028"
MANIFEST = json.loads((PACKET / "admission_manifest.json").read_text(encoding="utf-8"))
CENSUS = json.loads((PACKET / "census.json").read_text(encoding="utf-8"))
# Whitespace-normalized: Markdown line wraps must not break phrase checks.
VERDICT = re.sub(r"\s+", " ", (PACKET / "ADMISSION_VERDICT.md").read_text(encoding="utf-8"))
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION = "7cedfd3fe29f2de4f675039410a48160739323fc"

CARD_SCHEMA = [
    "game_id", "start_time", "player", "market", "line", "side",
    "book", "ts", "odds", "result", "won",
]
DRAFT_SCHEMA_FIELDS = [
    "snap_ts", "tick_ts", "start_ts", "close_ts", "is_close",
    "outcome_known", "segment", "over_odds", "under_odds",
]
SIX_MARKETS = {
    "player bases", "player hits", "player rbis",
    "player home runs", "player strikeouts", "player batting walks",
}


def test_verdict_is_admitted_design_screen_only():
    assert MANIFEST["verdict"] == "ADMITTED"
    assert MANIFEST["design_only"] is True
    assert MANIFEST["screen_only"] is True
    assert MANIFEST["validation_credit"] is False
    assert MANIFEST["forward_clock_credit"] is False
    assert MANIFEST["play_eligible"] is False
    assert MANIFEST["sport"] == "MLB"
    assert "Verdict: ADMITTED — DESIGN/SCREEN ONLY." in VERDICT


def test_source_is_the_canonical_repo_at_the_pinned_revision():
    source = MANIFEST["source"]
    assert source["publisher"] == "SmartStake"
    assert source["dataset_id"] == "SmartStake/mlb-player-props"
    assert source["platform"] == "Hugging Face"
    assert source["revision"] == REVISION
    assert source["license"] == "cc-by-4.0"
    assert "no payment" in source["access"]
    # Mirrors exist but are NOT admitted; the canonical repo only.
    assert set(source["mirrors_not_admitted"]) == {
        "Neonlightzz/mlb-player-props", "canesyrup/mlb-player-props",
    }


def test_all_18_partitions_pinned_by_sha256_equal_to_lfs_oid():
    partitions = MANIFEST["partitions"]
    assert len(partitions) == 18
    paths = [p["path"] for p in partitions]
    assert len(set(paths)) == 18
    assert all(p.startswith("mon=2026-0") and p.endswith(".parquet") for p in paths)
    for part in partitions:
        assert SHA256_RE.match(part["sha256"])
        assert part["sha256"] == part["hf_lfs_oid"]
        assert part["pin_status"] == "PIN_MATCH"
        assert part["bytes"] > 0
        assert part["rows"] > 0
    assert sum(p["bytes"] for p in partitions) == MANIFEST["totals"]["bytes"] == 901_411_520
    assert sum(p["rows"] for p in partitions) == MANIFEST["totals"]["rows"] == 621_391_637


def test_pinned_schema_is_the_dataset_card_schema():
    assert MANIFEST["schema_pinned"] == CARD_SCHEMA
    # The draft's "observed schema" does not exist in the canonical files
    # and must never be admitted or coded against.
    for field in DRAFT_SCHEMA_FIELDS:
        assert field not in MANIFEST["schema_pinned"]
    assert "does NOT exist in the canonical files" in MANIFEST["schema_note"]


def test_scope_markets_are_exactly_the_six_canonical_markets():
    assert set(MANIFEST["scope"]["markets"]) == SIX_MARKETS
    markets_rows = MANIFEST["totals"]["markets_rows"]
    assert set(markets_rows) == SIX_MARKETS
    assert sum(markets_rows.values()) == MANIFEST["totals"]["rows"]


def test_draftkings_present_in_every_partition():
    for part in MANIFEST["partitions"]:
        assert part["draftkings_rows"] > 0
    total = sum(p["draftkings_rows"] for p in MANIFEST["partitions"])
    assert total == MANIFEST["totals"]["draftkings_rows"] == 44_368_757
    assert MANIFEST["totals"]["books_dataset_wide"] == 75


def test_result_consistency_measured_zero_disagreements():
    consistency = MANIFEST["totals"]["result_consistency"]
    assert consistency["selection_groups_with_result"] == 93_929
    assert consistency["groups_disagreeing"] == 0


def test_hunt_pin_reconciliation_recorded():
    reconciliation = MANIFEST["hunt_pin_reconciliation"]
    assert reconciliation["reproduced"] == 1
    assert reconciliation["not_reproduced"] == 3
    reproduced = [p for p in MANIFEST["partitions"] if p.get("hunt_pin_reproduces")]
    assert len(reproduced) == 1
    assert reproduced[0]["path"] == "mon=2026-03/part-000.parquet"
    assert reproduced[0]["sha256"] == reproduced[0]["hunt_pin_sha256"]


def test_census_agrees_with_manifest_partition_by_partition():
    census_by_file = {p["file"]: p for p in CENSUS["partitions"]}
    assert CENSUS["total_rows"] == MANIFEST["totals"]["rows"]
    assert CENSUS["books_total_count"] == MANIFEST["totals"]["books_dataset_wide"]
    assert CENSUS["books_total"]["draftkings"] == MANIFEST["totals"]["draftkings_rows"]
    assert CENSUS["markets_total"] == MANIFEST["totals"]["markets_rows"]
    assert CENSUS["result_consistency"] == MANIFEST["totals"]["result_consistency"]
    for part in MANIFEST["partitions"]:
        census_part = census_by_file[part["path"]]
        assert census_part["rows"] == part["rows"]
        assert census_part["n_books"] == part["n_books"]
        # dk_rows is the count of the lowercase 'draftkings' book label,
        # independently re-measured after a case-sensitive first pass
        # recorded zeros; the census must carry the corrected counts.
        assert census_part["dk_rows"] == part["draftkings_rows"]


def test_verdict_document_records_every_bar_and_the_g1_statement():
    for bar in (
        "Provenance — PASS.",
        "Point-in-time safety / lookahead — PASS",
        "Coverage — PASS with one declared caveat.",
        "Book identity — PASS.",
        "Timestamp quality — PASS.",
    ):
        assert bar in VERDICT
    assert "G1 (historical prop closing lines) moves for exactly one family" in VERDICT
    assert "G1 remains NO_DATA for NFL" in VERDICT
