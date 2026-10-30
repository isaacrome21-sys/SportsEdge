import csv
import json

import pytest

from scripts.pull_nba_results import OUT_COLS
from sportsedge.research.nba_early_season_input_audit_v1 import (
    REQUIRED_FIELDS,
    audit_columns,
    audit_csv,
    main,
)


def test_repository_results_pull_is_truthfully_blocked_by_missing_chronology():
    report = audit_columns(OUT_COLS)
    assert report["status"] == "INPUT_CONTRACT_INCOMPLETE"
    assert report["historical_screen_can_run"] is False
    assert report["missing_fields"] == [
        "game_date", "tipoff", "observed_at", "source_ref", "event_state",
        "result_state", "finalized_at", "role_source_ref", "role_observed_at", "position"
    ]
    assert report["play_authority"] is False


def test_complete_header_is_only_structurally_ready_not_authenticated():
    report = audit_columns(REQUIRED_FIELDS)
    assert report["status"] == "INPUT_CONTRACT_STRUCTURALLY_READY"
    assert report["historical_screen_can_run"] is True
    assert report["source_authentication"] == "NOT_ESTABLISHED_BY_COLUMN_NAMES"
    assert report["market_validation"] == "NONE"
    assert report["play_authority"] is False


def test_duplicate_casefolded_columns_fail_closed():
    with pytest.raises(ValueError, match="HEADER_DUPLICATE"):
        audit_columns([*REQUIRED_FIELDS, "PLAYER_ID"])


def test_empty_csv_fails_closed_with_named_header_error(tmp_path):
    source = tmp_path / "empty.csv"
    source.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="HEADER_MISSING"):
        audit_csv(source)


def test_cli_writes_machine_readable_blocker_and_digest(tmp_path):
    source = tmp_path / "nba_player_games_2025-26.csv"
    output = tmp_path / "audit.json"
    with source.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_COLS)
        writer.writeheader()
        writer.writerow({name: "x" for name in OUT_COLS})
    assert main(["--csv", str(source), "--output", str(output)]) == 2
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["input_name"] == source.name
    assert len(report["input_sha256"]) == 64
    assert report["missing_fields"] == [
        "game_date", "tipoff", "observed_at", "source_ref", "event_state",
        "result_state", "finalized_at", "role_source_ref", "role_observed_at", "position"
    ]
    assert report["timestamp_policy"].startswith("NEVER_INFER")


def test_preflight_requires_engine_final_and_role_witnesses():
    witnesses = {"event_state", "result_state", "finalized_at",
                 "role_source_ref", "role_observed_at"}
    for missing in witnesses:
        report = audit_columns([f for f in REQUIRED_FIELDS if f != missing])
        assert report["historical_screen_can_run"] is False
        assert missing in report["missing_fields"]
