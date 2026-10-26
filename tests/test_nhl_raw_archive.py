"""Synthetic raw-byte archive tests: not real NHL capture evidence."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pytest

from sportsedge.sports.nhl.raw_archive import archive_pair, verify_archive


@dataclass(frozen=True)
class Receipt:
    source_version: str
    source_raw_sha256: str
    landing_raw_sha256: str | None


def receipt(box: bytes = b'{"boxscore":1}', landing: bytes = b'{"landing":2}'):
    return Receipt("nhl-web-api-v1-live2", sha256(box).hexdigest(), sha256(landing).hexdigest())


def test_raw_archive_preserves_exact_distinct_bodies_and_is_idempotent(tmp_path: Path):
    box, landing = b'{ "id":1 }\n', b'{"id":1,"summary":[]}'
    r = receipt(box, landing)
    archive_pair(tmp_path, r, box, landing)
    assert (tmp_path / "sha256" / f"{r.source_raw_sha256}.json").read_bytes() == box
    assert (tmp_path / "sha256" / f"{r.landing_raw_sha256}.json").read_bytes() == landing
    archive_pair(tmp_path, r, box, landing)
    verify_archive(tmp_path, r)


def test_wrong_second_hash_writes_neither_source(tmp_path: Path):
    r = receipt()
    with pytest.raises(ValueError, match="NHL_RAW_RESPONSE_HASH_MISMATCH:landing"):
        archive_pair(tmp_path, r, b'{"boxscore":1}', b'changed')
    assert not (tmp_path / "sha256").exists()


def test_missing_archive_fails_closed(tmp_path: Path):
    with pytest.raises(ValueError, match="NHL_RAW_ARCHIVE_MISSING"):
        verify_archive(tmp_path, receipt())


def test_tampered_archive_fails_closed_and_is_never_overwritten(tmp_path: Path):
    box, landing = b'{"boxscore":1}', b'{"landing":2}'
    r = receipt(box, landing)
    archive_pair(tmp_path, r, box, landing)
    p = tmp_path / "sha256" / f"{r.source_raw_sha256}.json"
    p.write_bytes(b'corrupt')
    with pytest.raises(ValueError, match="NHL_RAW_ARCHIVE_HASH_MISMATCH"):
        verify_archive(tmp_path, r)
    with pytest.raises(ValueError, match="NHL_RAW_ARCHIVE_HASH_MISMATCH"):
        archive_pair(tmp_path, r, box, landing)
    assert p.read_bytes() == b'corrupt'


def test_legacy_receipt_cannot_be_reclassified_as_archived(tmp_path: Path):
    r = Receipt("nhl-web-api-v1", sha256(b'a').hexdigest(), None)
    with pytest.raises(ValueError, match="NHL_RAW_ARCHIVE_REQUIRES_DUAL_SOURCE_LIVE_RECEIPT"):
        verify_archive(tmp_path, r)


def test_collector_archives_both_exact_live_responses(tmp_path: Path):
    import json
    from scripts.collect_nhl_official_boxscores import collect_completed_games
    fixtures = Path(__file__).parent / "fixtures"
    box_raw = (fixtures / "nhl_gamecenter_2026020168_boxscore.json").read_bytes()
    landing_raw = (fixtures / "nhl_gamecenter_2026020168_landing.json").read_bytes()
    box, landing = json.loads(box_raw), json.loads(landing_raw)

    def fetcher(url):
        if url.endswith("/boxscore"):
            return box, box_raw, "2026-10-26T15:00:00Z"
        if url.endswith("/landing"):
            return landing, landing_raw, "2026-10-26T15:00:01Z"
        raise AssertionError(url)

    games, failures = collect_completed_games(("2026020168",), fetcher=fetcher,
                                              sleep_seconds=0, raw_archive_dir=tmp_path)
    assert not failures and len(games) == 1
    assert games[0].source_raw_sha256 == sha256(box_raw).hexdigest()
    assert games[0].landing_raw_sha256 == sha256(landing_raw).hexdigest()
    verify_archive(tmp_path, games[0])


def test_collector_quarantines_failed_archive_without_receipt(tmp_path: Path, monkeypatch):
    import json
    from scripts import collect_nhl_official_boxscores as collector
    fixtures = Path(__file__).parent / "fixtures"
    box_raw = (fixtures / "nhl_gamecenter_2026020168_boxscore.json").read_bytes()
    landing_raw = (fixtures / "nhl_gamecenter_2026020168_landing.json").read_bytes()
    box, landing = json.loads(box_raw), json.loads(landing_raw)

    def fetcher(url):
        if url.endswith("/boxscore"):
            return box, box_raw, "2026-10-26T15:00:00Z"
        return landing, landing_raw, "2026-10-26T15:00:01Z"

    def refused(*_args):
        raise OSError("archive unavailable")

    monkeypatch.setattr(collector, "archive_pair", refused)
    games, failures = collector.collect_completed_games(("2026020168",), fetcher=fetcher,
                                                        sleep_seconds=0, raw_archive_dir=tmp_path)
    assert games == [] and len(failures) == 1
    assert "archive unavailable" in failures[0][1]
