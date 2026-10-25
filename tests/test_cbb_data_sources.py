"""Tests for sportsedge.cbb_data_sources (recorded fixture transports only).

No network: every transport is a fake yielding small recorded CSV bytes
in the shape of the real sources probed on 2026-10-24.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from datetime import datetime, timezone

import pytest

from sportsedge.cbb_data_sources import (
    CBBDataSourceError,
    ILLINOIS_COLLEGE_SCOPE_NOTE,
    SOURCES,
    collect,
    source_url,
    verify_manifest,
)

WHEN = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)

ESPN_CSV = (
    b"game_play_number,type_text,away_score,home_score,game_id,game_date\n"
    b"1,Jumpball,0,0,401804830,2025-12-21\n"
    b"2,Jump Shot,0,2,401804830,2025-12-21\n"
)
NCAA_CSV_GZ = gzip.compress(
    b"game_date,home,away,period,home_score,away_score,poss_num,espn_game_id\n"
    b"11/03/2025,Buffalo,Southern Miss.,1,0,0,1,401823425\n"
    b"11/03/2025,Buffalo,Southern Miss.,2,85,79,98,401823425\n"
)
TORVIK_CSV = (
    b"rank,team,conf,record,adjoe,adjde,barthag\n"
    b"1,Duke,ACC,0-0,120.4,91.0,0.9616\n"
    b"2,Houston,B12,0-0,118.9,92.2,0.9580\n"
)


def fake_transport(payload: bytes, chunk: int = 7):
    def fetch(url: str):
        for i in range(0, len(payload), chunk):
            yield payload[i : i + chunk]

    return fetch


def test_source_url_templates_and_ranges():
    assert source_url("espn_mbb_pbp", 2026).endswith(
        "/espn_mens_college_basketball_pbp/play_by_play_2026.csv"
    )
    assert source_url("ncaa_mbb_pbp", 2010).endswith(
        "/ncaa_mbb_pbp/ncaa_mbb_pbp_2010.csv.gz"
    )
    assert source_url("torvik_team_ratings", 2027) == (
        "https://barttorvik.com/2027_team_results.csv"
    )
    # Probed ranges only: refused before any network call.
    for source, bad in (
        ("espn_mbb_pbp", 2005),
        ("espn_mbb_pbp", 2027),  # 2026-27 in-season file not yet published
        ("ncaa_mbb_pbp", 2009),
        ("torvik_team_ratings", 2009),
        ("torvik_team_ratings", 2028),
    ):
        with pytest.raises(CBBDataSourceError):
            source_url(source, bad)
    with pytest.raises(CBBDataSourceError):
        source_url("kenpom", 2026)


def test_collect_espn_csv_is_gzipped_and_manifested(tmp_path):
    manifest = collect(
        "espn_mbb_pbp", 2026, tmp_path,
        transport=fake_transport(ESPN_CSV), retrieved_at=WHEN,
    )
    assert manifest["rows"] == 2
    assert manifest["schema_columns"][0] == "game_play_number"
    assert manifest["downloaded_sha256"] == hashlib.sha256(ESPN_CSV).hexdigest()
    assert manifest["downloaded_bytes"] == len(ESPN_CSV)
    assert manifest["stored_file"] == "2026.csv.gz"
    assert manifest["research_only"] is True
    assert manifest["pricing_impact"] == "NONE"
    assert manifest["staking_allowed"] is False
    assert manifest["scope_note"] == ILLINOIS_COLLEGE_SCOPE_NOTE
    assert "Illinois" in manifest["scope_note"]
    # Stored bytes are a gzip of the payload and re-verify offline.
    stored = tmp_path / "espn_mbb_pbp" / "2026.csv.gz"
    assert gzip.decompress(stored.read_bytes()) == ESPN_CSV
    assert manifest["stored_sha256"] == hashlib.sha256(stored.read_bytes()).hexdigest()
    on_disk = json.loads((tmp_path / "espn_mbb_pbp" / "2026.manifest.json").read_text())
    assert on_disk == manifest
    assert verify_manifest(tmp_path, "espn_mbb_pbp", 2026) is True


def test_collect_ncaa_gz_passthrough_keeps_download_hash(tmp_path):
    manifest = collect(
        "ncaa_mbb_pbp", 2026, tmp_path,
        transport=fake_transport(NCAA_CSV_GZ), retrieved_at=WHEN,
    )
    assert manifest["rows"] == 2
    assert manifest["schema_columns"][:3] == ["game_date", "home", "away"]
    # Passthrough: downloaded and stored representations are identical.
    assert manifest["downloaded_sha256"] == manifest["stored_sha256"]
    stored = tmp_path / "ncaa_mbb_pbp" / "2026.csv.gz"
    assert stored.read_bytes() == NCAA_CSV_GZ
    assert verify_manifest(tmp_path, "ncaa_mbb_pbp", 2026) is True


def test_collect_torvik_plain_csv(tmp_path):
    manifest = collect(
        "torvik_team_ratings", 2027, tmp_path,
        transport=fake_transport(TORVIK_CSV), retrieved_at=WHEN,
    )
    assert manifest["rows"] == 2
    assert manifest["stored_file"] == "2027.csv"
    assert manifest["source_url"] == "https://barttorvik.com/2027_team_results.csv"
    assert verify_manifest(tmp_path, "torvik_team_ratings", 2027) is True


def test_transport_failure_leaves_nothing_behind(tmp_path):
    def boom(url: str):
        raise ConnectionError("network down")
        yield  # pragma: no cover

    with pytest.raises(CBBDataSourceError):
        collect("torvik_team_ratings", 2027, tmp_path, transport=boom)
    assert not (tmp_path / "torvik_team_ratings" / "2027.csv").exists()
    assert not (tmp_path / "torvik_team_ratings" / "2027.manifest.json").exists()


def test_empty_and_garbage_bodies_are_refused(tmp_path):
    with pytest.raises(CBBDataSourceError):
        collect(
            "torvik_team_ratings", 2027, tmp_path,
            transport=fake_transport(b""), retrieved_at=WHEN,
        )
    with pytest.raises(CBBDataSourceError):
        collect(
            "torvik_team_ratings", 2027, tmp_path,
            transport=fake_transport(b"Verifying Browser...\nplease wait\n"),
            retrieved_at=WHEN,
        )
    assert not (tmp_path / "torvik_team_ratings" / "2027.manifest.json").exists()


def test_registry_covers_the_three_probed_sources():
    assert set(SOURCES) == {"espn_mbb_pbp", "ncaa_mbb_pbp", "torvik_team_ratings"}
