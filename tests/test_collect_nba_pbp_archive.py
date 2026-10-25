"""Tests for scripts/collect_nba_pbp_archive.py (stdlib fixtures)."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "collect_nba_pbp_archive.py"
)
spec = importlib.util.spec_from_file_location("collect_nba_pbp_archive", SCRIPT)
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)

V3_CSV = (
    "actionNumber,clock,period,scoreHome,scoreAway,gameId\n"
    "1,PT12M00.00S,1,0,0,22400001\n"
    "2,PT11M00.00S,1,2,0,22400001\n"
    "3,PT10M00.00S,1,2,3,22400002\n"
).encode()

PBPSTATS_CSV = (
    "GAMEID,GAMEDATE,OPPONENT,PERIOD\n"
    "22400001,2024-11-12,BOS,1\n"
    "22400001,2024-11-12,BOS,2\n"
).encode()


def make_tar_xz(csv_name: str, csv_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        info = tarfile.TarInfo(csv_name)
        info.size = len(csv_bytes)
        tar.addfile(info, io.BytesIO(csv_bytes))
    return buf.getvalue()


def test_archive_nbastatsv3_file(tmp_path: Path) -> None:
    payload = make_tar_xz("nbastatsv3_2024.csv", V3_CSV)
    entry = mod.archive_file(payload, "nbastatsv3", 2024, False, tmp_path)
    assert entry["rows"] == 3
    assert entry["games"] == 2
    assert (tmp_path / "nbastatsv3_2024.csv").read_bytes() == V3_CSV


def test_archive_pbpstats_file(tmp_path: Path) -> None:
    payload = make_tar_xz("pbpstats_2024.csv", PBPSTATS_CSV)
    entry = mod.archive_file(payload, "pbpstats", 2024, False, tmp_path)
    assert entry["rows"] == 2
    assert entry["games"] == 1


def test_wrong_header_fails_closed(tmp_path: Path) -> None:
    payload = make_tar_xz("nbastatsv3_2024.csv", b"a,b,c\n1,2,3\n")
    with pytest.raises(ValueError, match="missing expected key column"):
        mod.archive_file(payload, "nbastatsv3", 2024, False, tmp_path)


def test_multi_member_tar_fails_closed(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        for name in ("a.csv", "b.csv"):
            data = b"gameId\n1\n"
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    with pytest.raises(ValueError, match="exactly one CSV"):
        mod.archive_file(buf.getvalue(), "nbastatsv3", 2024, False, tmp_path)


def test_main_with_source_dir(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "nbastatsv3_2024.tar.xz").write_bytes(
        make_tar_xz("nbastatsv3_2024.csv", V3_CSV)
    )
    out = tmp_path / "out"
    rc = mod.main(
        [
            "--out-dir",
            str(out),
            "--dataset",
            "nbastatsv3:2024",
            "--source-dir",
            str(src),
        ]
    )
    assert rc == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["labels"]["in_season_props_source"] is False
    assert manifest["files"][0]["rows"] == 3


def test_dataset_filename() -> None:
    assert mod.dataset_filename("pbpstats", 2024, False) == "pbpstats_2024.tar.xz"
    assert mod.dataset_filename("pbpstats", 2024, True) == "pbpstats_po_2024.tar.xz"


def test_parse_dataset() -> None:
    assert mod.parse_dataset("nbastatsv3:2025") == ("nbastatsv3", 2025, False)
    assert mod.parse_dataset("pbpstats:2000:po") == ("pbpstats", 2000, True)
    with pytest.raises(ValueError, match="unknown family"):
        mod.parse_dataset("nope:2024")
    with pytest.raises(ValueError, match="bad dataset spec"):
        mod.parse_dataset("nbastatsv3:2024:xx")
