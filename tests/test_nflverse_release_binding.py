from __future__ import annotations

from hashlib import sha256

import pytest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.nflverse_release_binding import bind_nflverse_archive_asset


def _kwargs():
    raw = b"frozen pregame nflverse bytes"
    return dict(
        kickoff="2026-09-29T00:15:00Z",
        release_tag="archive-2026-09-24",
        asset_name="example_2026.parquet",
        asset_id=586633211,
        published_at="2026-09-24T19:06:19Z",
        source_uri=(
            "https://github.com/nflverse/nflverse-data-archives/releases/download/"
            "archive-2026-09-24/example_2026.parquet"
        ),
        expected_sha256=sha256(raw).hexdigest(),
        raw_bytes=raw,
        expected_size=len(raw),
    )


def test_binds_exact_raw_archive_bytes():
    out = bind_nflverse_archive_asset(**_kwargs())
    assert out["status"] == "BOUND"
    assert out["raw_sha256"] == _kwargs()["expected_sha256"]
    assert out["authority"] == "RESEARCH_ONLY"


def test_rejects_digest_mismatch():
    kw = _kwargs()
    kw["expected_sha256"] = "0" * 64
    with pytest.raises(NFLContextError, match="SHA-256 mismatch"):
        bind_nflverse_archive_asset(**kw)


def test_rejects_wrong_release_uri():
    kw = _kwargs()
    kw["source_uri"] = kw["source_uri"].replace("archive-2026-09-24", "archive-2026-09-25")
    with pytest.raises(NFLContextError, match="source_uri"):
        bind_nflverse_archive_asset(**kw)


def test_rejects_post_kickoff_release():
    kw = _kwargs()
    kw["published_at"] = kw["kickoff"]
    with pytest.raises(NFLContextError, match="published before kickoff"):
        bind_nflverse_archive_asset(**kw)


def test_rejects_size_mismatch():
    kw = _kwargs()
    kw["expected_size"] += 1
    with pytest.raises(NFLContextError, match="size mismatch"):
        bind_nflverse_archive_asset(**kw)
