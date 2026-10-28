"""Offline guards for the hoopR MBB play-by-play admission packet.

These tests never touch the network. They pin the admission invariants:
DESIGN-only status scoped to the CBB first-half design screen, full pin
tuples for the play-by-play CSV assets of every season 2015-2023
(rolling release tags pin nothing by themselves), the pull-timestamp
attestation scope, the schema verification over the five core field
roles a first-half derivation consumes, the coverage/integrity readings
against the admitted schedule substrate, the sample halftime checks
against ESPN's published linescores (named as a same-provider check),
the .parquet/.rds twins recorded as present-but-NOT-pinned, the
crosswalk still OPEN, and the non-admission of KenPom.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKET = ROOT / "research" / "cbb_hoopr_pbp_admission_20261028"
MANIFEST = json.loads((PACKET / "pbp_manifest.json").read_text(encoding="utf-8"))
RECORD = (PACKET / "ADMISSION_RECORD.md").read_text(encoding="utf-8")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SEASONS = list(range(2015, 2024))
CORE_FIELDS = ["game_id", "period_number", "period_display_value",
               "clock_display_value", "scoring_play", "score_value", "team_id",
               "home_team_id", "away_team_id", "away_score", "home_score", "season"]


def test_manifest_is_design_only_and_scoped_to_first_half():
    assert MANIFEST["design_only"] is True
    assert MANIFEST["validation_credit"] is False
    assert MANIFEST["forward_clock_credit"] is False
    assert MANIFEST["play_eligible"] is False
    assert MANIFEST["sport"] == "CBB"
    assert "first-half" in MANIFEST["screen_scope"]


def test_every_design_season_csv_is_pinned():
    names = {s["asset_name"] for s in MANIFEST["samples"]}
    expected = {f"play_by_play_{y}.csv" for y in SEASONS}
    assert names == expected
    assert len(MANIFEST["samples"]) == 9


def test_every_sample_carries_a_full_pin_tuple():
    for sample in MANIFEST["samples"]:
        assert isinstance(sample["asset_id"], int)
        assert isinstance(sample["release_id"], int)
        assert sample["release_id"] == 97399228
        assert sample["release_tag"] == "espn_mens_college_basketball_pbp"
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


def test_schema_verification_covers_core_fields_every_season():
    schema = MANIFEST["schema_verification"]
    assert schema["core_fields"] == CORE_FIELDS
    for y in SEASONS:
        present = schema["per_season"][str(y)]["core_fields_present"]
        assert all(present[c] for c in CORE_FIELDS), f"season {y} missing a core field"


def test_coverage_and_integrity_are_recorded_per_season():
    coverage = MANIFEST["coverage"]
    for y in SEASONS:
        cov = coverage[str(y)]
        # The admitted schedule universe per season (PR #2867 manifest).
        assert cov["schedule_games"] in range(4000, 6500)
        # PBP games are a strict subset of the schedule universe on
        # ESPN game IDs: nothing joined from outside it.
        assert cov["pbp_extra_vs_schedule"] == 0
        assert cov["games_in_both"] == cov["pbp_games"]
        assert 0.0 <= cov["missing_rate_vs_schedule"] < 0.25
        # Method A (running score) finals reproduce the admitted
        # schedule finals on at least 98% of joined games per season;
        # the residual is the named PBP-defect class the record's
        # final-agreement gate excludes.
        both = cov["games_in_both"]
        assert cov["final_agreement_running_score"] >= 0.98 * both
        # Method B (scoring-play sums) is recorded as measured - and
        # refused in the schema verification, never presented as valid.
        assert cov["final_agreement_scoring_sum"] < cov["final_agreement_running_score"]


def test_method_b_is_recorded_refused():
    schema = MANIFEST["schema_verification"]
    assert "REFUSED" in schema["derivation"]["method_b_scoring_sum_status"]
    assert "Method A" in RECORD or "Method A" in json.dumps(schema)


def test_sample_halftime_checks_agree_with_espn_linescores():
    checks = MANIFEST["sample_checks"]
    games = checks["games"]
    assert len(games) >= 10
    # Method A halftime agrees with ESPN's published linescores on
    # every sample game present in the PBP.
    assert checks["halftime_agreements"] == checks["halftime_checked"]
    assert checks["halftime_checked"] >= 10
    # The absent sample games are named, not dropped silently.
    missing_ids = {g["game_id"] for g in checks["games_not_in_pbp"]}
    assert missing_ids == {"400809216", "401082362", "401269640"}
    assert "same provider" in checks["check_source_disclosure"]


def test_twin_formats_are_recorded_not_pinned():
    twins = MANIFEST["unpinned_twin_formats"]
    assert len(twins) == 18
    assert all(t["pin_status"] == "NOT_PINNED" for t in twins)
    formats = {t["asset_name"].rsplit(".", 1)[1] for t in twins}
    assert formats == {"parquet", "rds"}


def test_prerequisite_accounting_is_explicit():
    sat = MANIFEST["satisfies"]
    assert sat["cbb_team_totals_1h_design_prerequisite"].startswith("YES")
    assert "PBP_PREREQUISITE_MISSING" in RECORD
    assert MANIFEST["crosswalk_status"] == "NOT_ADMITTED_BY_THIS_RECORD"


def test_record_states_the_binding_rules():
    lowered = re.sub(r"\s+", " ", RECORD.lower())
    assert "rolling" in lowered
    assert "as pulled at that timestamp" in lowered
    assert "source_changed_after_snapshot" in lowered
    assert "illinois-college" in lowered
    assert "kenpom is not admitted" in lowered
    assert "design only" in lowered
    assert "not_executable" in lowered
    assert "does **not** run the cbb first-half design screen" in lowered
    assert "final scores only" in lowered
    # The final-agreement gate is stated as binding on consumers.
    assert "derived final equals the admitted schedule final" in lowered
    assert "method b is refused" in lowered or "method b is therefore refused" in lowered


def test_verification_script_compiles_and_uses_manifest():
    script = (PACKET / "pull_hoopr_pbp.py").read_text(encoding="utf-8")
    assert "pbp_manifest.json" in script
    assert "SOURCE_CHANGED_AFTER_SNAPSHOT" in script
    compile(script, "pull_hoopr_pbp.py", "exec")
