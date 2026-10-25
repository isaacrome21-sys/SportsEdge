#!/usr/bin/env python3
"""Research-only, explicit live capture of Retrosheet's official gameinfo ZIP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SOURCE_URL = "https://retrosheet.org/downloads/gameinfo.zip"
MAX_ZIP_BYTES = 40_000_000
MAX_CSV_BYTES = 250_000_000
REQUIRED_CREDIT = (
    "The information used here was obtained free of charge from and is copyrighted "
    "by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., "
    "Newark, DE 19711."
)


def inspect_zip(data: bytes) -> dict[str, object]:
    """Inspect a ZIP and its single gameinfo.csv member, without extracting it."""
    if not data.startswith(b"PK"):
        raise ValueError("INVALID_ZIP_SIGNATURE")
    if len(data) > MAX_ZIP_BYTES:
        raise ValueError("ZIP_TOO_LARGE")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            candidates = [
                entry for entry in archive.infolist()
                if Path(entry.filename).name.lower() == "gameinfo.csv"
                and not entry.is_dir()
            ]
            if len(candidates) != 1:
                raise ValueError("GAMEINFO_MEMBER_MISSING_OR_AMBIGUOUS")
            member = candidates[0]
            if sum(entry.file_size for entry in archive.infolist()) > MAX_CSV_BYTES:
                raise ValueError("ARCHIVE_EXPANSION_TOO_LARGE")
            if member.file_size > MAX_CSV_BYTES:
                raise ValueError("CSV_TOO_LARGE")
            if archive.testzip() is not None:
                raise ValueError("ZIP_CRC_FAILURE")
            with archive.open(member) as infile:
                with io.TextIOWrapper(infile, encoding="utf-8-sig", newline="") as stream:
                    rows = csv.reader(stream)
                    columns = next(rows, [])
                    if len(columns) < 3 or any(not col for col in columns):
                        raise ValueError("MISSING_CSV_HEADER")
                    if len(set(columns)) != len(columns):
                        raise ValueError("DUPLICATE_CSV_HEADER")
                    count = 0
                    for row in rows:
                        if not row:
                            continue
                        if len(row) != len(columns):
                            raise ValueError("INCONSISTENT_CSV_ROW_WIDTH")
                        count += 1
                    if count == 0:
                        raise ValueError("EMPTY_CSV")
    except (zipfile.BadZipFile, EOFError, UnicodeError, csv.Error, RuntimeError) as exc:
        raise ValueError("INVALID_ZIP_OR_CSV") from exc
    return {"member": member.filename, "columns": columns, "row_count": count}


def archive_zip(
    output_dir: Path, data: bytes, received_at_utc: str
) -> dict[str, object]:
    stats = inspect_zip(data)
    observed = datetime.fromisoformat(received_at_utc)
    if observed.tzinfo is None:
        raise ValueError("RECEIPT_TIMESTAMP_MISSING_OFFSET")
    digest = hashlib.sha256(data).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"gameinfo_{digest}.zip"
    if zip_path.exists():
        if hashlib.sha256(zip_path.read_bytes()).hexdigest() != digest:
            raise ValueError("EXISTING_ARCHIVE_BYTES_CONFLICT")
    else:
        with zip_path.open("xb") as dest:
            dest.write(data)

    receipt: dict[str, object] = {
        "schema": "RETROSHEET_GAMEINFO_ARCHIVE_RECEIPT_V1",
        "provider": "RETROSHEET",
        "source_url": SOURCE_URL,
        "received_at_utc": received_at_utc,
        "archive_sha256": digest,
        "archive_bytes": len(data),
        "archive_path": str(zip_path),
        "csv_member": stats["member"],
        "csv_columns": stats["columns"],
        "csv_row_count": stats["row_count"],
        "attribution_required": REQUIRED_CREDIT,
        "data_vintage": "ARCHIVAL_NOT_PREGAME",
        "event_identity_validated": False,
        "pit_available": False,
        "model_p": None,
        "pricing_input": False,
        "play_eligible": False,
        "research_only": True,
        "reason": "EVENT_IDS_AND_PIT_ODDS_NOT_PAIRED",
    }
    stamp = observed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = output_dir / f"gameinfo_{stamp}_{digest[:12]}.json"
    with path.open("x", encoding="utf-8") as dest:
        json.dump(receipt, dest, indent=2, sort_keys=True)
        dest.write("\n")
    return receipt


def _fetch_official_zip() -> tuple[bytes, str]:
    req = Request(SOURCE_URL, headers={"User-Agent": "SportsEdge-research-archive/1.0"})
    with urlopen(req, timeout=30) as response:
        final = urlparse(response.geturl())
        if (
            final.scheme != "https"
            or final.hostname not in {"retrosheet.org", "www.retrosheet.org"}
            or final.path != "/downloads/gameinfo.zip"
            or final.username is not None
            or final.password is not None
            or final.port is not None
        ):
            raise ValueError("NON_OFFICIAL_REDIRECT")
        if response.status != 200:
            raise ValueError("HTTP_NOT_200")
        data = response.read(MAX_ZIP_BYTES + 1)
    received_at = datetime.now(timezone.utc).isoformat()
    if len(data) > MAX_ZIP_BYTES:
        raise ValueError("ZIP_TOO_LARGE")
    return data, received_at


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow public network read and archive")
    parser.add_argument("--output-dir", type=Path, help="Local append-only archive directory")
    args = parser.parse_args(argv)
    if not args.live:
        print(json.dumps({"status": "DISABLED_REQUIRES_LIVE", "pricing_input": False}))
        return 0
    if args.output_dir is None:
        parser.error("--output-dir required with --live")
    try:
        data, received_at = _fetch_official_zip()
        receipt = archive_zip(args.output_dir, data, received_at)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        print(f"RETROSHEET_ARCHIVE_BLOCKED: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
