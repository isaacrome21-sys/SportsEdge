"""Offline guards for the hoopR MBB schedule successor-manifest packet.

These tests never touch the network. They pin the admission invariants:
DESIGN-only status, full pin tuples for every season 2015-2023 in both
pinned formats (rolling release tags pin nothing by themselves), the
pull-timestamp attestation scope, the College Basketball Reference leg
recorded as refused (HTTP 403) and NOT pinned, the design-screen
precondition accounting (b satisfied, (c)'s CBR leg outstanding), the
crosswalk still OPEN, and the non-admission of KenPom.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "cbb_hoopr_mbb_schedule_successor_20261028"
MANIFEST = json.loads((PACKET / "successor_manifest.json").read_text(encoding="utf-8"))
RECORD = (PACKET / "ADMISSION_RECORD.md").read_text(encoding="utf-8")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEASONS = list(range(2015, 2024))


def test_manifest_is_design_only():
    assert MANIFEST["design_only"] is True
    assert MANIFEST["validation_credit"] is False
    assert MANIFEST["forward_clock_credit"] is False
    assert MANIFEST["play_eligible"] is False
    assert MANIFEST["sport"] == "CBB"


def test_every_design_season_is_pinned_in_both_formats():
    names = {s["asset_name"] for s in MANIFEST["samples"]}
    expected = {f"mbb_schedule_{y}.{fmt}" for y in SEASONS for fmt in ("csv", "parquet")}
    assert names == expected
    assert len(MANIFEST["samples"]) == 18


def test_every_sample_carries_a_full_pin_tuple():
    for sample in MANIFEST["samples"]:
        assert isinstance(sample["asset_id"], int)
        assert isinstance(sample["release_id"], int)
        assert sample["release_id"] == 97399224
        assert sample["release_tag"] == "espn_mens_college_basketball_schedules"
        assert SHA256_RE.match(sample["sha256"])
        assert sample["bytes"] > 0
        assert sample["release_tag"] in sample["url"]
        assert sample["asset_name"] in sample["url"]
        assert sample["asset_updated_at"]
        assert sample["season"] in SEASONS


def test_pin_attests_bytes_at_pull_timestamp_only():
    assert MANIFEST["retrieved_at_utc"]
    pin_rule = MANIFEST["pin_rule"]
    assert "ROLLING" in pin_rule
    assert "retrieved_at_utc" in pin_rule
    assert "does NOT attest" in pin_rule
    assert "SOURCE_CHANGED_AFTER_SNAPSHOT" in pin_rule


def test_csv_content_checks_carry_sane_coverage():
    csvs = [s for s in MANIFEST["samples"] if s["asset_name"].endswith(".csv")]
    assert len(csvs) == 9
    for sample in csvs:
        # Sane band for a Division I season (2021 is the COVID-shortened
        # season at 4,285; full seasons run ~5,700-6,300).
        assert 4000 <= sample["rows"] <= 6500
        assert sample["game_date_min"] < sample["game_date_max"]
        assert "both team scores populated" in sample["content_check"]
        assert "ESPN identifiers present" in sample["content_check"]
    by_season = {s["season"]: s for s in csvs}
    assert by_season[2020]["game_date_max"] == "2020-03-11"
    assert by_season[2021]["rows"] == 4285
    assert by_season[2023]["rows"] == 6261


def test_cbr_leg_is_recorded_refused_and_unpinned():
    leg = MANIFEST["cbr_leg"]
    assert leg["status"] == "REFUSED_HTTP_403_NOT_PINNED"
    assert len(leg["entries"]) == 9
    assert not any(e.get("pin_status") == "PINNED" for e in leg["entries"])
    first = leg["entries"][0]
    assert first["pin_status"] == "REFUSED_HTTP"
    assert first["http_status"] == 403
    assert "three-way" in leg["consequence"]


def test_precondition_accounting_is_explicit():
    sat = MANIFEST["satisfies"]
    assert sat["pr_2866_precondition_b"].startswith("YES")
    assert sat["pr_2866_precondition_c_cbr_leg"].startswith("NO")


def test_crosswalk_remains_open_and_not_admitted():
    assert MANIFEST["crosswalk_status"] == "OPEN_NOT_ADMITTED"
    lowered = RECORD.lower()
    assert "open — not admitted" in lowered
    assert "name-only joins are refused" in lowered


def test_record_states_the_binding_rules():
    lowered = RECORD.lower()
    assert "rolling" in lowered
    assert "as pulled at that timestamp" in lowered
    assert "source_changed_after_snapshot" in lowered
    assert "illinois college" in lowered
    assert "kenpom is not admitted" in lowered
    assert "design only" in lowered
    assert "not_executable" in lowered
    assert "satisfied by this" in lowered
    assert "http 403" in lowered
    assert "does not run the screen" in lowered


def test_verification_script_compiles_and_uses_manifest():
    script = (PACKET / "pull_hoopr_mbb_schedules.py").read_text(encoding="utf-8")
    assert "successor_manifest.json" in script
    assert "SOURCE_CHANGED_AFTER_SNAPSHOT" in script
    assert "REFUSED_HTTP_403_NOT_PINNED" in script
    compile(script, "pull_hoopr_mbb_schedules.py", "exec")
