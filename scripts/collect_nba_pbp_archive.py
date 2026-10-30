"""Archive shufinskiy/nba_data season files as a historical NBA PBP source.

HISTORICAL / RESEARCH ONLY. This admits the shufinskiy/nba_data GitHub
archive (per-season tar.xz files) as a historical play-by-play and
possession research source. It is NOT an in-season NBA props pricing
source and changes nothing about props sourcing: the props-source
question (ESPN Candidate B) remains a separate owner decision, and the
frozen NBA props construction reads its own store.

Relationship to the admitted {nbadatar} source: {nbadatar} is the R
loader at github.com/ramirobentes/nbadatar with its data companion repo
github.com/ramirobentes/nba_data (Parquet releases), admitted 2026-10-21
as a cross-check / reference source (admission record:
nbadatar_snapshot_20261021/ADMISSION_CHECK.md in the records workspace;
the GitHub-only repos carry no CRAN/PyPI listing, which is why package
indexes do not surface them). This collector admits a SECOND, independent
historical archive; the two pipelines cross-check each other.

Admission evidence (Rocky, 2026-10-24, live probe of the archive):
  - Families present in datasets/: nbastats PBP 1996+, nbastatsv3 PBP
    1996+, pbpstats possessions 2000+, shotdetail 1996+, datanba 2016+,
    cdnnba 2020+, matchups 2017+ (regular season + playoffs each).
  - nbastatsv3_2025 (2025-26): 621,887 PBP rows; nbastatsv3_2024:
    606,538 rows; pbpstats_2024: 483,126 possession rows.
  - Cross-check: finals derived from nbastatsv3_2024 score columns for
    ATL @ BOS 2024-11-12 (gameId 22400001) = ATL 117, BOS 116 — exact
    match to independent records (Basketball-Reference / AP); the same
    game carries 378 possession-segment rows in pbpstats_2024.

Writes (under --out-dir): the extracted season CSVs plus manifest.json
(per-file sha256 of the downloaded tar and the extracted CSV, row and
game counts, scope labels).

Exit codes: 0 = archived, 2 = failed closed (bad tar / unexpected CSV
header / empty season file).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import tarfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/shufinskiy/nba_data/main/datasets"
FAMILIES = {
    "nbastats": "gameId",
    "nbastatsv3": "gameId",
    "pbpstats": "GAMEID",
    "shotdetail": "GAME_ID",
    "datanba": "GAME_ID",
    "cdnnba": "GAME_ID",
    "matchups": "GAME_ID",
}
LABELS = {
    "role": "historical/research NBA play-by-play and possession archive",
    "pricing_input": False,
    "in_season_props_source": False,
    "scope_note": (
        "NOT an in-season NBA props pricing source; props sourcing "
        "(ESPN Candidate B) is a separate owner decision"
    ),
}


def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "SportsEdge/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read()


def dataset_filename(family: str, season: int, playoffs: bool) -> str:
    suffix = "_po" if playoffs else ""
    return f"{family}{suffix}_{season}.tar.xz"


def extract_season_csv(payload: bytes, family: str) -> tuple[str, bytes]:
    """Return (csv_name, csv_bytes) from a season tar.xz payload."""
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:xz") as tar:
        members = [m for m in tar.getmembers() if m.isfile()]
        if len(members) != 1 or not members[0].name.endswith(".csv"):
            raise ValueError(
                f"expected exactly one CSV in tar, found {[m.name for m in members]}"
            )
        fh = tar.extractfile(members[0])
        if fh is None:
            raise ValueError("could not extract CSV member")
        return members[0].name, fh.read()


def inspect_csv(csv_bytes: bytes, family: str) -> dict:
    text = io.StringIO(csv_bytes.decode("utf-8-sig"))
    reader = csv.DictReader(text)
    key_col = FAMILIES[family]
    if not reader.fieldnames or key_col not in reader.fieldnames:
        raise ValueError(
            f"{family} CSV missing expected key column {key_col!r}; "
            f"header starts {reader.fieldnames[:6] if reader.fieldnames else None}"
        )
    games: set[str] = set()
    rows = 0
    for row in reader:
        rows += 1
        games.add(row[key_col])
    if rows == 0:
        raise ValueError(f"{family} CSV is empty")
    return {"rows": rows, "games": len(games), "key_column": key_col}


def archive_file(
    payload: bytes, family: str, season: int, playoffs: bool, out_dir: Path
) -> dict:
    csv_name, csv_bytes = extract_season_csv(payload, family)
    info = inspect_csv(csv_bytes, family)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / csv_name).write_bytes(csv_bytes)
    return {
        "dataset_file": dataset_filename(family, season, playoffs),
        "family": family,
        "season": season,
        "playoffs": playoffs,
        "tar_sha256": hashlib.sha256(payload).hexdigest(),
        "csv_file": csv_name,
        "csv_sha256": hashlib.sha256(csv_bytes).hexdigest(),
        **info,
    }


def parse_dataset(spec: str) -> tuple[str, int, bool]:
    """Parse a 'family:season[:po]' dataset spec."""
    parts = spec.split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"bad dataset spec {spec!r}; want family:season[:po]")
    family = parts[0]
    if family not in FAMILIES:
        raise ValueError(f"unknown family {family!r}; choose from {sorted(FAMILIES)}")
    playoffs = len(parts) == 3 and parts[2] == "po"
    if len(parts) == 3 and not playoffs:
        raise ValueError(f"bad dataset spec {spec!r}; third field must be 'po'")
    return family, int(parts[1]), playoffs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument(
        "--dataset",
        action="append",
        required=True,
        metavar="FAMILY:SEASON[:po]",
        help="dataset to archive; repeatable",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=None,
        help="read already-downloaded tar.xz files from this directory",
    )
    args = parser.parse_args(argv)
    entries = []
    try:
        for spec in args.dataset:
            family, season, playoffs = parse_dataset(spec)
            name = dataset_filename(family, season, playoffs)
            url = f"{BASE_URL}/{name}"
            payload = (
                (args.source_dir / name).read_bytes()
                if args.source_dir
                else fetch_bytes(url)
            )
            entry = archive_file(payload, family, season, playoffs, args.out_dir)
            entry["source_url"] = url
            entries.append(entry)
            print(f"archived {name}: {entry['rows']} rows, {entry['games']} games")
    except Exception as exc:  # fail closed
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    manifest = {
        "source": "shufinskiy/nba_data (GitHub datasets/)",
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "files": entries,
        "labels": LABELS,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=1) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
