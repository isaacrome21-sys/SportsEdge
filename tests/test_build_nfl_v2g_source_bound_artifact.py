import csv
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts.build_nfl_v2g_source_bound_artifact import (
    SCHEDULE_TO_PBP_TEAM_ALIAS,
    TEAM_ALIAS_POLICY,
    _identity_scoped_pbp,
    _normalize_schedule_team_aliases,
    _team_identity_mismatches,
    build,
)
from sportsedge.sports.nfl.source_manifest import build_nfl_source_manifest


def _sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _fixture(tmp_path: Path):
    schedule = tmp_path / "games.csv"
    _write_csv(schedule, [
        {"game_id": "2016_01_A_B", "season": 2016, "week": 1, "game_type": "REG", "home_team": "A", "away_team": "B"},
        {"game_id": "2016_02_B_A", "season": 2016, "week": 2, "game_type": "REG", "home_team": "B", "away_team": "A"},
    ])
    pbp_dir = tmp_path / "pbp"
    pbp = pbp_dir / "play_by_play_2016.csv"
    _write_csv(pbp, [
        {"game_id": "2016_01_A_B", "posteam": "A", "drive": 1, "touchdown": 1, "td_team": "A", "play_type": "run", "field_goal_result": ""},
        {"game_id": "2016_01_A_B", "posteam": "A", "drive": 2, "touchdown": 0, "td_team": "", "play_type": "punt", "field_goal_result": ""},
        {"game_id": "2016_01_A_B", "posteam": "B", "drive": 1, "touchdown": 0, "td_team": "", "play_type": "field_goal", "field_goal_result": "made"},
        {"game_id": "2016_01_A_B", "posteam": "B", "drive": 2, "touchdown": 0, "td_team": "", "play_type": "punt", "field_goal_result": ""},
        {"game_id": "2016_02_B_A", "posteam": "B", "drive": 1, "touchdown": 1, "td_team": "B", "play_type": "pass", "field_goal_result": ""},
        {"game_id": "2016_02_B_A", "posteam": "B", "drive": 2, "touchdown": 0, "td_team": "A", "play_type": "interception", "field_goal_result": ""},
        {"game_id": "2016_02_B_A", "posteam": "A", "drive": 1, "touchdown": 0, "td_team": "", "play_type": "field_goal", "field_goal_result": "made"},
        {"game_id": "2016_02_B_A", "posteam": "A", "drive": 2, "touchdown": 0, "td_team": "", "play_type": "punt", "field_goal_result": ""},
    ])
    manifest = build_nfl_source_manifest([
        {"name": "schedule", "uri": "file://games.csv", "sha256": _sha(schedule)},
        {"name": "pbp_2016", "uri": "file://play_by_play_2016.csv", "sha256": _sha(pbp)},
    ], schedule_anchor_sha256=_sha(schedule))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    return schedule, pbp_dir, manifest_path


def test_source_bound_builder_produces_deterministic_non_promotional_artifact(tmp_path):
    schedule, pbp_dir, manifest = _fixture(tmp_path)
    first_artifact, first_report = build(
        schedule_file=schedule, pbp_dir=pbp_dir, source_manifest=manifest,
        start_season=2016, end_season=2016,
    )
    second_artifact, second_report = build(
        schedule_file=schedule, pbp_dir=pbp_dir, source_manifest=manifest,
        start_season=2016, end_season=2016,
    )
    assert first_artifact == second_artifact
    assert first_report["artifact_sha256"] == second_report["artifact_sha256"]
    assert first_report["byte_determinism"] == "PASS"
    assert first_report["event_row_count"] == 2
    assert first_report["ignored_unscoped_pbp_row_count"] == 0
    assert first_report["team_alias_policy"] == TEAM_ALIAS_POLICY
    assert first_report["team_alias_application_count"] == 0
    assert first_report["promotion_authority"] is False
    assert first_report["may_create_model_p"] is False
    assert first_artifact["promotion_authority"] is False
    assert first_artifact["official_status_granted"] is False


def test_source_bound_builder_rejects_tampered_pbp(tmp_path):
    schedule, pbp_dir, manifest = _fixture(tmp_path)
    pbp = pbp_dir / "play_by_play_2016.csv"
    pbp.write_text(pbp.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="NFL_V2G_SOURCE_SHA256_MISMATCH:pbp_2016"):
        build(
            schedule_file=schedule, pbp_dir=pbp_dir, source_manifest=manifest,
            start_season=2016, end_season=2016,
        )


def test_unscoped_non_possession_rows_are_dropped_but_counted():
    rows = [
        {"game_id": "g", "posteam": "A", "drive": "", "touchdown": "0", "td_team": "", "play_type": "kickoff", "field_goal_result": ""},
        {"game_id": "g", "posteam": "A", "drive": "1", "touchdown": "0", "td_team": "", "play_type": "run", "field_goal_result": ""},
    ]
    kept, dropped = _identity_scoped_pbp(rows)
    assert dropped == 1
    assert len(kept) == 1
    assert kept[0]["drive"] == "1"


def test_unscoped_made_field_goal_fails_closed():
    rows = [{
        "game_id": "g", "posteam": "A", "drive": "", "touchdown": "0", "td_team": "",
        "play_type": "field_goal", "field_goal_result": "made",
    }]
    with pytest.raises(ValueError, match="NFL_V2G_SCORING_EVENT_IDENTITY_MISSING:g:FIELD_GOAL"):
        _identity_scoped_pbp(rows)


def test_unscoped_kick_return_touchdown_is_not_offensive_possession():
    rows = [{
        "game_id": "g", "posteam": "A", "drive": "", "touchdown": "1", "td_team": "A",
        "play_type": "kickoff", "field_goal_result": "",
    }]
    kept, dropped = _identity_scoped_pbp(rows)
    assert kept == []
    assert dropped == 1


def test_historical_schedule_aliases_are_explicit_and_minimal():
    assert SCHEDULE_TO_PBP_TEAM_ALIAS == {"OAK": "LV", "SD": "LAC"}
    rows, applications = _normalize_schedule_team_aliases([
        {"game_id": "2016_05_SD_OAK", "game_type": "REG", "home_team": "OAK", "away_team": "SD"},
        {"game_id": "2016_06_KC_OAK", "game_type": "REG", "home_team": "OAK", "away_team": "KC"},
    ])
    assert rows[0]["home_team"] == "LV"
    assert rows[0]["away_team"] == "LAC"
    assert rows[1]["home_team"] == "LV"
    assert rows[1]["away_team"] == "KC"
    assert applications == [
        {"game_id": "2016_05_SD_OAK", "field": "away_team", "from": "SD", "to": "LAC"},
        {"game_id": "2016_05_SD_OAK", "field": "home_team", "from": "OAK", "to": "LV"},
        {"game_id": "2016_06_KC_OAK", "field": "home_team", "from": "OAK", "to": "LV"},
    ]


def test_team_identity_preflight_accepts_only_after_frozen_alias_normalization():
    raw_schedule = [{
        "game_id": "2016_05_SD_OAK", "game_type": "REG", "home_team": "OAK", "away_team": "SD",
    }]
    pbp = [
        {"game_id": "2016_05_SD_OAK", "posteam": "LV", "drive": "1"},
        {"game_id": "2016_05_SD_OAK", "posteam": "LAC", "drive": "1"},
    ]
    assert _team_identity_mismatches(raw_schedule, pbp)
    normalized, _ = _normalize_schedule_team_aliases(raw_schedule)
    assert _team_identity_mismatches(normalized, pbp) == []
