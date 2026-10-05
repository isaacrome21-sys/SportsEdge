import hashlib
from pathlib import Path

import pytest

from sportsedge.sports.nfl.score_counts_forward_bundle import (
    RECEIPT_SCHEMA,
    ScoreCountForwardError,
    build_forward_bundle,
    verify_forward_receipts,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _payload(tmp_path: Path, *, retrieved="2026-10-08T12:00:00+00:00"):
    sources = []
    schedule = tmp_path / "games.csv"
    schedule.write_text("game_id\n", encoding="utf-8")
    sources.append({
        "name": "schedule",
        "role": "schedule",
        "path": str(schedule),
        "source_identifier": "capture://games",
        "retrieved_at_utc": retrieved,
        "season_scope": list(range(2018, 2027)),
        "byte_sha256": _sha(schedule),
        "parser_code_sha256": "a" * 64,
    })
    for role, suffix in (("pbp", ".csv.gz"), ("depth", ".csv")):
        for season in range(2018, 2027):
            p = tmp_path / f"{role}_{season}{suffix}"
            p.write_bytes(f"{role}:{season}".encode())
            sources.append({
                "name": f"{role}_{season}",
                "role": role,
                "path": str(p),
                "source_identifier": f"capture://{role}/{season}",
                "retrieved_at_utc": retrieved,
                "season_scope": [season],
                "byte_sha256": _sha(p),
                "parser_code_sha256": "a" * 64,
            })
    return {"schema": RECEIPT_SCHEMA, "sources": sources}


def test_forward_receipts_verify_bound_pregame_bytes(tmp_path):
    manifest = verify_forward_receipts(
        _payload(tmp_path),
        prediction_at="2026-10-08T18:00:00+00:00",
        parser_code_sha256="a" * 64,
    )
    assert manifest["market_data_used"] is False
    assert len(manifest["manifest_sha256"]) == 64
    assert len(manifest["sources"]) == 19


def test_forward_receipts_reject_post_prediction_source(tmp_path):
    with pytest.raises(ScoreCountForwardError, match="SOURCE_NOT_PREGAME"):
        verify_forward_receipts(
            _payload(tmp_path, retrieved="2026-10-08T18:00:00+00:00"),
            prediction_at="2026-10-08T18:00:00+00:00",
            parser_code_sha256="a" * 64,
        )


def test_forward_receipts_reject_byte_mutation(tmp_path):
    payload = _payload(tmp_path)
    Path(payload["sources"][1]["path"]).write_bytes(b"changed")
    with pytest.raises(ScoreCountForwardError, match="SHA_MISMATCH"):
        verify_forward_receipts(
            payload,
            prediction_at="2026-10-08T18:00:00+00:00",
            parser_code_sha256="a" * 64,
        )


def test_forward_receipts_require_complete_2018_2026_coverage(tmp_path):
    payload = _payload(tmp_path)
    payload["sources"] = [
        row for row in payload["sources"]
        if not (row["role"] == "pbp" and row["season_scope"] == [2020])
    ]
    with pytest.raises(ScoreCountForwardError, match="SEASON_COVERAGE_REQUIRED:pbp"):
        verify_forward_receipts(
            payload,
            prediction_at="2026-10-08T18:00:00+00:00",
            parser_code_sha256="a" * 64,
        )


def test_bundle_requires_passing_fit():
    fit = {
        "status": "DEVELOPMENT_ATTEMPT_FAIL",
        "development_gate": {"pass": False},
        "artifact_sha256": "b" * 64,
        "source_manifest_sha256": "c" * 64,
    }
    with pytest.raises(ScoreCountForwardError, match="PASSING_DEVELOPMENT_FIT_REQUIRED"):
        build_forward_bundle(
            fit_artifact=fit,
            prediction={},
            forward_manifest={"manifest_sha256": "d" * 64},
            forward_rows=[],
        )
