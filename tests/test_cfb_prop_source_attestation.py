from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts.build_cfb_prop_source_attestation import build_attestation


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "pbp.csv"
    path.write_text(
        "game_id,homeTeamId,homeTeamName,awayTeamId,awayTeamName\n"
        "1,10,Alpha,20,Beta\n"
        "1,10,Alpha,20,Beta\n"
        "2,30,Gamma,10,Alpha\n",
        encoding="utf-8",
    )
    return path


def test_attestation_binds_bytes_retrieval_time_rows_and_teams(tmp_path: Path) -> None:
    source = _source(tmp_path)
    result = build_attestation(
        source=source,
        retrieval_time_utc="2026-09-11T12:00:00Z",
        upstream_url="https://example.invalid/play_by_play_2025.parquet",
        upstream_sha256="a" * 64,
        normalized_from="parquet",
    )
    normalized = result["normalized_training_input"]
    assert result["retrieved_at_utc"] == "2026-09-11T12:00:00Z"
    assert normalized["row_count"] == 3
    assert normalized["distinct_team_count"] == 3
    assert normalized["sha256"] == sha256(source.read_bytes()).hexdigest()
    assert result["sportsbook_data_used_for_fit"] is False
    assert result["promotion_authority"] is False

    expected = dict(result)
    digest = expected.pop("attestation_sha256")
    raw = json.dumps(expected, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    assert digest == sha256(raw).hexdigest()


def test_attestation_changes_when_training_bytes_change(tmp_path: Path) -> None:
    source = _source(tmp_path)
    first = build_attestation(
        source=source,
        retrieval_time_utc="2026-09-11T12:00:00Z",
        upstream_url="https://example.invalid/play_by_play_2025.parquet",
        upstream_sha256="b" * 64,
        normalized_from="parquet",
    )
    source.write_text(source.read_text(encoding="utf-8") + "3,40,Delta,20,Beta\n", encoding="utf-8")
    second = build_attestation(
        source=source,
        retrieval_time_utc="2026-09-11T12:00:00Z",
        upstream_url="https://example.invalid/play_by_play_2025.parquet",
        upstream_sha256="b" * 64,
        normalized_from="parquet",
    )
    assert first["attestation_sha256"] != second["attestation_sha256"]
    assert second["normalized_training_input"]["row_count"] == 4


def test_attestation_rejects_naive_retrieval_time(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="MUST_BE_AWARE"):
        build_attestation(
            source=_source(tmp_path),
            retrieval_time_utc="2026-09-11T12:00:00",
            upstream_url="https://example.invalid/play_by_play_2025.parquet",
            upstream_sha256="c" * 64,
            normalized_from="parquet",
        )
