"""CBB (men's college basketball) research data sources.

REGISTERED RESEARCH ONLY -- NOT_VALIDATED, zero pricing impact.

This module registers the free CBB data layer behind NO engine: no CBB
engine exists in this program yet, and nothing in any pricing path imports
this module. It only downloads season files from three free sources into a
local research archive, each with a sha256 manifest carrying provenance
(source id, canonical URL, retrieval time, row count, schema header).

Sources (all live-probed 2026-10-24; see
``docs/cbb_data_feed_research_20261024.md`` for the full evidence):

  * ``espn_mbb_pbp`` -- hoopR ``load_mbb_pbp``'s underlying release:
    SportsDataverse ``sportsdataverse-data`` GitHub release tag
    ``espn_mens_college_basketball_pbp``, one ``play_by_play_{season}.csv``
    per season, 2006-2026 (season = ending year; 2026 is the completed
    2025-26 season). ESPN-sourced play-by-play, 63 columns including
    running scores and the closing spread fields ESPN publishes.
  * ``ncaa_mbb_pbp`` -- hoopR ``load_ncaa_mbb_pbp``'s underlying release:
    tag ``ncaa_mbb_pbp``, one ``ncaa_mbb_pbp_{season}.csv.gz`` per season,
    2010-2026. stats.ncaa.org-derived play-by-play (87 columns) with
    reconstructed possessions, full 5-man lineups for both teams, a
    garbage-time flag, and ESPN team/game id crosswalk columns. Shot
    coordinates are NOT in this file -- they live in the sibling
    ``ncaa_mbb_shots`` release (2019+) and are not collected here.
  * ``torvik_team_ratings`` -- BartTorvik T-Rank season table, served as
    ``https://barttorvik.com/{season}_team_results.csv``. Free, no key.
    Verified live for seasons 2010-2027: the 2027 file (2026-27
    preseason, all records 0-0) was already published on 2026-10-24, so
    the underlying CSV is current even though the human-facing
    ``trank.php`` page sits behind a browser-verification wall and the
    toRvik/hoopR wrapper docs date to 2022.

SCOPE NOTE (program rule, recorded -- not a filter): Illinois COLLEGE
teams are out of scope for CBB pricing in this program. These collectors
are research archives and deliberately do NOT filter any team out of the
archive; the exclusion binds any future pricing use, not the archive.

Fail-closed rules:
  * a season outside a source's probed range raises CBBDataSourceError
    before any network call;
  * an existing season file or manifest is immutable; repeated collection
    refuses without making another request;
  * transport failure, an empty body, or a body whose first row is not a
    plausible CSV header raises CBBDataSourceError -- no manifest is
    written and only the new temporary download is removed;
  * every archived file carries both the as-downloaded sha256 and the
    stored-bytes sha256 in its manifest, so archive integrity is
    re-verifiable offline.

Format notes: hoopR's own loaders read ``.rds``; this collector is
stdlib-only (no R, no pyarrow), so it archives the published CSV /
CSV.GZ forms of the same releases instead. Full-season ESPN CSVs are
large (123 MB - 1.35 GB); they are stored gzip-compressed via streaming,
never loaded into memory.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from urllib.request import Request, urlopen

SCHEMA_VERSION = "cbb_data_sources_v1"
USER_AGENT = "SportsEdge-CBB-Data/1.0 (research-only; no pricing use)"

SDV_RELEASES = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
)

ILLINOIS_COLLEGE_SCOPE_NOTE = (
    "Illinois college teams are out of scope for CBB pricing in this "
    "program; this research archive intentionally retains all teams."
)

# Probed season ranges (inclusive) -- see the registration doc. A season
# outside the range is refused, never guessed at.
SOURCES: Mapping[str, Mapping[str, Any]] = {
    "espn_mbb_pbp": {
        "label": "ESPN MBB play-by-play (SportsDataverse release)",
        "url_template": (
            SDV_RELEASES
            + "/espn_mens_college_basketball_pbp/play_by_play_{season}.csv"
        ),
        "min_season": 2006,
        "max_season": 2026,
        "download_gzipped": False,
        "stored_extension": "csv.gz",
    },
    "ncaa_mbb_pbp": {
        "label": "NCAA MBB play-by-play (SportsDataverse release)",
        "url_template": SDV_RELEASES + "/ncaa_mbb_pbp/ncaa_mbb_pbp_{season}.csv.gz",
        "min_season": 2010,
        "max_season": 2026,
        "download_gzipped": True,
        "stored_extension": "csv.gz",
    },
    "torvik_team_ratings": {
        "label": "BartTorvik T-Rank team ratings (season CSV)",
        "url_template": "https://barttorvik.com/{season}_team_results.csv",
        "min_season": 2010,
        "max_season": 2027,
        "download_gzipped": False,
        "stored_extension": "csv",
    },
}

_CHUNK = 1 << 18


class CBBDataSourceError(RuntimeError):
    """A CBB research source could not be collected; nothing fabricated."""


def source_url(source_id: str, season: int) -> str:
    """Canonical download URL for one source/season, range-checked."""
    spec = SOURCES.get(source_id)
    if spec is None:
        raise CBBDataSourceError(f"unknown CBB source: {source_id!r}")
    if not (spec["min_season"] <= season <= spec["max_season"]):
        raise CBBDataSourceError(
            f"season {season} outside probed range "
            f"{spec['min_season']}-{spec['max_season']} for {source_id}"
        )
    return spec["url_template"].format(season=season)


def _default_transport(url: str) -> Iterable[bytes]:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=300) as resp:
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            yield chunk


def _count_rows_and_header(stored: Path, stored_extension: str) -> tuple[int, list[str]]:
    """Stream the stored file once: return (data row count, header row)."""
    opener = gzip.open if stored_extension.endswith("gz") else open
    rows = 0
    header: list[str] = []
    with opener(stored, "rt", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        for i, row in enumerate(reader):
            if i == 0:
                header = row
            else:
                rows += 1
    return rows, header


def collect(
    source_id: str,
    season: int,
    archive_dir: Path,
    *,
    transport: Optional[Callable[[str], Iterable[bytes]]] = None,
    retrieved_at: Optional[datetime] = None,
) -> dict[str, Any]:
    """Download one season file into the research archive; return its manifest.

    The manifest is also written beside the stored file as
    ``{season}.manifest.json``. On any failure CBBDataSourceError is
    raised and no manifest or partial file is left behind.
    """
    spec = SOURCES.get(source_id)
    if spec is None:
        raise CBBDataSourceError(f"unknown CBB source: {source_id!r}")
    url = source_url(source_id, season)
    when = retrieved_at or datetime.now(timezone.utc)
    dest_dir = Path(archive_dir) / source_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored = dest_dir / f"{season}.{spec['stored_extension']}"
    manifest_path = dest_dir / f"{season}.manifest.json"
    # Prior evidence may have an independently published manifest, or a
    # surviving data file from an interrupted publication. Neither may be
    # silently replaced by a retry, even if the new provider bytes differ.
    if stored.exists() or manifest_path.exists():
        raise CBBDataSourceError(
            f"ARCHIVE_ALREADY_EXISTS: {source_id}/{season}"
        )
    fetch = transport or _default_transport

    downloaded_sha = hashlib.sha256()
    stored_sha = hashlib.sha256()
    downloaded_bytes = 0
    compress = spec["stored_extension"].endswith("gz") and not spec["download_gzipped"]
    temp_stored: Optional[Path] = None
    temp_manifest: Optional[Path] = None
    published_stored = False
    try:
        # Write and validate privately before publishing either canonical
        # path. The temporary file lives on the same filesystem so hard-link
        # publication is atomic and refuses to overwrite a racing writer.
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=dest_dir, prefix=f".{season}.", suffix=".part",
            delete=False,
        ) as raw_out:
            temp_stored = Path(raw_out.name)
            gz_out = (
                gzip.GzipFile(filename="", mode="wb", fileobj=raw_out, mtime=0)
                if compress
                else None
            )
            sink = gz_out if gz_out is not None else raw_out
            try:
                for chunk in fetch(url):
                    if not chunk:
                        continue
                    downloaded_sha.update(chunk)
                    downloaded_bytes += len(chunk)
                    sink.write(chunk)
            finally:
                if gz_out is not None:
                    gz_out.close()

        if downloaded_bytes == 0:
            raise CBBDataSourceError(f"empty body from {url}")

        # Hash and inspect the unpublished download. For compressed sources
        # this hash differs from the original provider payload by design.
        with temp_stored.open("rb") as fh:
            for block in iter(lambda: fh.read(_CHUNK), b""):
                stored_sha.update(block)
        try:
            rows, header = _count_rows_and_header(
                temp_stored, spec["stored_extension"]
            )
        except Exception as exc:
            raise CBBDataSourceError(
                f"stored file is not readable CSV: {exc}"
            ) from exc
        if rows == 0 or len(header) < 3:
            raise CBBDataSourceError(
                f"body from {url} does not look like a season CSV "
                f"(rows={rows}, header_cols={len(header)})"
            )

        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "research_only": True,
            "validation_status": "NOT_VALIDATED",
            "pricing_impact": "NONE",
            "staking_allowed": False,
            "source": source_id,
            "source_label": spec["label"],
            "season": season,
            "source_url": url,
            "retrieved_at": when.isoformat(),
            "rows": rows,
            "schema_columns": header,
            "downloaded_bytes": downloaded_bytes,
            "downloaded_sha256": downloaded_sha.hexdigest(),
            "stored_file": stored.name,
            "stored_bytes": temp_stored.stat().st_size,
            "stored_sha256": stored_sha.hexdigest(),
            "scope_note": ILLINOIS_COLLEGE_SCOPE_NOTE,
        }
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=dest_dir,
            prefix=f".{season}.", suffix=".manifest.part", delete=False,
        ) as manifest_out:
            temp_manifest = Path(manifest_out.name)
            manifest_out.write(json.dumps(manifest, indent=1) + "\n")

        # os.link is create-if-absent (EEXIST if a concurrent retry won).
        # Unlike replace/rename, it never destroys a previously archived
        # season. Publish the manifest only after data publication succeeds.
        os.link(temp_stored, stored)
        published_stored = True
        os.link(temp_manifest, manifest_path)
        return manifest
    except CBBDataSourceError:
        if published_stored:
            stored.unlink(missing_ok=True)
        raise
    except FileExistsError as exc:
        if published_stored:
            stored.unlink(missing_ok=True)
        raise CBBDataSourceError(
            f"ARCHIVE_ALREADY_EXISTS: {source_id}/{season}"
        ) from exc
    except Exception as exc:  # transport / IO failure: fail closed
        if published_stored:
            stored.unlink(missing_ok=True)
        raise CBBDataSourceError(f"collection failed for {url}: {exc}") from exc
    finally:
        if temp_stored is not None:
            temp_stored.unlink(missing_ok=True)
        if temp_manifest is not None:
            temp_manifest.unlink(missing_ok=True)


def verify_manifest(archive_dir: Path, source_id: str, season: int) -> bool:
    """Re-hash a stored archive file against its manifest (offline check)."""
    manifest_path = Path(archive_dir) / source_id / f"{season}.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stored = manifest_path.parent / manifest["stored_file"]
    digest = hashlib.sha256()
    with open(stored, "rb") as fh:
        for block in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(block)
    return digest.hexdigest() == manifest["stored_sha256"]


__all__ = [
    "CBBDataSourceError",
    "ILLINOIS_COLLEGE_SCOPE_NOTE",
    "SCHEMA_VERSION",
    "SOURCES",
    "collect",
    "source_url",
    "verify_manifest",
]
