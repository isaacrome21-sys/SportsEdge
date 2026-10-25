"""Synthetic/offline tests for Retrosheet archive, not market admission."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from scripts.collect_retrosheet_gameinfo import (
    REQUIRED_CREDIT,
    archive_zip,
    inspect_zip,
    main,
)


def _sample_zip(member: str = "gameinfo.csv", content: str = "gid,date,home\n1,2025-04-01,CHN\n") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        zipped.writestr(member, content)
    return buf.getvalue()


def test_accepts_single_usable_member_without_extraction() -> None:
    info = inspect_zip(_sample_zip())
    assert info["member"] == "gameinfo.csv"
    assert info["row_count"] == 1
    assert info["columns"] == ["gid", "date", "home"]


def test_rejects_missing_or_ambiguous_members() -> None:
    with pytest.raises(ValueError, match="GAMEINFO_MEMBER_MISSING_OR_AMBIGUOUS"):
        inspect_zip(_sample_zip(member="other.csv"))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zipped:
        zipped.writestr("a/gameinfo.csv", "gid,date,home\n1,2025-04-01,CHN\n")
        zipped.writestr("b/gameinfo.csv", "gid,date,home\n2,2025-04-02,CHN\n")
    with pytest.raises(ValueError, match="GAMEINFO_MEMBER_MISSING_OR_AMBIGUOUS"):
        inspect_zip(buf.getvalue())


@pytest.mark.parametrize("csv_data,reason", [
    ("bad\n1\n", "MISSING_CSV_HEADER"),
    ("id,id,home\n1,2,CHN\n", "DUPLICATE_CSV_HEADER"),
    ("gid,date,home\n1,2025-04-01\n", "INCONSISTENT_CSV_ROW_WIDTH"),
    ("gid,date,home\n", "EMPTY_CSV"),
])
def test_invalid_csv_fails_closed(csv_data: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        inspect_zip(_sample_zip(content=csv_data))


def test_rejects_non_zip_and_corrupt_archive() -> None:
    with pytest.raises(ValueError, match="INVALID_ZIP_SIGNATURE"):
        inspect_zip(b"not a zip")
    with pytest.raises(ValueError):
        inspect_zip(b"PKbad zip")


def test_preserves_bytes_credit_and_distinct_receipts(tmp_path: Path) -> None:
    data = _sample_zip()
    first = archive_zip(tmp_path, data, "2026-10-25T03:00:01+00:00")
    second = archive_zip(tmp_path, data, "2026-10-25T03:05:01+00:00")
    assert first["archive_sha256"] == hashlib.sha256(data).hexdigest()
    assert first["attribution_required"] == REQUIRED_CREDIT
    assert "Retrosheet" in first["attribution_required"]
    assert first["pricing_input"] is False
    assert first["play_eligible"] is False
    assert first["pit_available"] is False
    assert first["model_p"] is None
    assert second["archive_sha256"] == first["archive_sha256"]
    assert len(list(tmp_path.glob("*.zip"))) == 1
    receipts = [json.loads(p.read_text()) for p in tmp_path.glob("*.json")]
    assert len(receipts) == 2
    assert {r["received_at_utc"] for r in receipts} == {
        "2026-10-25T03:00:01+00:00",
        "2026-10-25T03:05:01+00:00",
    }


def test_rejects_existing_archive_tampering(tmp_path: Path) -> None:
    data = _sample_zip()
    digest = hashlib.sha256(data).hexdigest()
    target = tmp_path / f"gameinfo_{digest}.zip"
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="EXISTING_ARCHIVE_BYTES_CONFLICT"):
        archive_zip(tmp_path, data, "2026-10-25T03:00:01+00:00")
    assert target.read_bytes() == b"tampered"
    assert not list(tmp_path.glob("*.json"))


def test_default_invocation_has_no_network_or_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def forbidden() -> None:
        raise AssertionError("offline default should never fetch")

    monkeypatch.setattr("scripts.collect_retrosheet_gameinfo._fetch_official_zip", forbidden)
    assert main(["--output-dir", str(tmp_path)]) == 0
    assert "DISABLED_REQUIRES_LIVE" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())
