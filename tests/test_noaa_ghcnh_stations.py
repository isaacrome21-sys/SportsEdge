"""Offline NOAA GHCNh source-contract tests; weather observations not priced."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.collect_noaa_ghcnh_stations import (
    MAX_STATIONS_BYTES,
    archive_station_list,
    inspect_station_list,
    main,
)


def _station_text(count: int = 60) -> bytes:
    # Synthetic shape only; NOT a claim about actual GHCNh column schema.
    return "".join(f"station-row-{i}\n" for i in range(count)).encode("utf-8")


def test_accepts_raw_text_without_inventing_station_ids_or_weather() -> None:
    result = inspect_station_list(_station_text())
    assert result["nonempty_line_count"] == 60
    assert result["parsed_station_count"] is None


@pytest.mark.parametrize("bad,reason", [
    (b"", "STATION_LIST_MISSING_OR_TOO_LARGE"),
    (b"\x00" + _station_text(), "NOT_STATION_TEXT"),
    (b"%PDF-1.7" + _station_text(), "NOT_STATION_TEXT"),
    (b"\xff" + _station_text(), "STATION_TEXT_ENCODING_UNVERIFIED"),
    (_station_text(2), "STATION_LIST_TOO_SHORT"),
    (b"X" * (MAX_STATIONS_BYTES + 1), "STATION_LIST_MISSING_OR_TOO_LARGE"),
])
def test_missing_or_wrong_source_fails_closed(bad: bytes, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        inspect_station_list(bad)


def test_archive_immutable_and_duplicate_observations_are_distinct(tmp_path: Path) -> None:
    content = _station_text()
    first = archive_station_list(tmp_path, content, "2026-10-25T05:00:01+00:00")
    second = archive_station_list(tmp_path, content, "2026-10-25T05:02:01+00:00")
    assert first["raw_sha256"] == hashlib.sha256(content).hexdigest()
    assert first["dataset_type"] == "STATION_METADATA_NOT_WEATHER_OBSERVATIONS"
    assert first["pit_available"] is False
    assert first["weather_observation_proven"] is False
    assert first["pricing_input"] is False
    assert first["play_eligible"] is False
    assert first["model_p"] is None
    assert second["raw_sha256"] == first["raw_sha256"]
    assert len(list(tmp_path.glob("*.txt"))) == 1
    reports = [json.loads(p.read_text()) for p in tmp_path.glob("*.json")]
    assert len(reports) == 2
    assert {p["received_at_utc"] for p in reports} == {
        "2026-10-25T05:00:01+00:00", "2026-10-25T05:02:01+00:00"
    }


def test_reject_tampered_existing_archive(tmp_path: Path) -> None:
    data = _station_text()
    digest = hashlib.sha256(data).hexdigest()
    target = tmp_path / f"ghcnh-stations_{digest}.txt"
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="EXISTING_STATION_ARCHIVE_CONFLICT"):
        archive_station_list(tmp_path, data, "2026-10-25T05:00:01+00:00")
    assert target.read_bytes() == b"tampered"
    assert not list(tmp_path.glob("*.json"))


def test_invalid_capture_timestamp_rejects_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="RECEIPT_TIMESTAMP_MISSING_OFFSET"):
        archive_station_list(tmp_path, _station_text(), "2026-10-25T05:00:01")
    assert not list(tmp_path.iterdir())


def test_default_does_not_fetch_or_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden() -> None:
        raise AssertionError("network is not authorized without --live")
    monkeypatch.setattr("scripts.collect_noaa_ghcnh_stations._fetch_official", forbidden)
    assert main(["--output-dir", str(tmp_path)]) == 0
    assert "DISABLED_REQUIRES_LIVE" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


def test_non_utc_offset_rejects_before_writing(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="RECEIPT_TIMESTAMP_NOT_UTC"):
        archive_station_list(tmp_path, _station_text(), "2026-10-25T00:00:01-05:00")
    assert not list(tmp_path.iterdir())
