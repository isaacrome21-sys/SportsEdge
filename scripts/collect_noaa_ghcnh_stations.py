#!/usr/bin/env python3
"""Archive NOAA GHCN-hourly station metadata; no weather or betting admission.

NOAA's GHCNh supersedes the retired ISD direct service. The station catalog
alone is not an observation, pregame forecast, stadium roof state or feature.
Nothing is fetched or written without explicit --live.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SOURCE_URL = (
    "https://www.ncei.noaa.gov/oa/global-historical-climatology-network/"
    "hourly/doc/ghcnh-station-list.txt"
)
MAX_STATIONS_BYTES = 32_000_000
MIN_STATION_LINES = 50


def inspect_station_list(data: bytes) -> dict[str, object]:
    """Inspect encoding and gross shape only. Station schema remains unverified."""
    if not data or len(data) > MAX_STATIONS_BYTES:
        raise ValueError("STATION_LIST_MISSING_OR_TOO_LARGE")
    if data.startswith((b"%PDF", b"PK", b"<!DOCTYPE", b"<html")) or b"\x00" in data:
        raise ValueError("NOT_STATION_TEXT")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("STATION_TEXT_ENCODING_UNVERIFIED") from exc
    if text.lstrip().lower().startswith(("<!doctype", "<html", "<?xml")):
        raise ValueError("NOT_STATION_TEXT")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < MIN_STATION_LINES:
        raise ValueError("STATION_LIST_TOO_SHORT")
    if any(len(line) > 4000 for line in lines):
        raise ValueError("STATION_LINE_TOO_LONG")
    # Do not infer station IDs, coordinates, UTC offsets or QC fields until
    # the published GHCNh schema is independently inspected and pinned.
    return {"nonempty_line_count": len(lines), "parsed_station_count": None}


def archive_station_list(
    output_dir: Path, raw: bytes, received_at_utc: str
) -> dict[str, object]:
    stats = inspect_station_list(raw)
    observation = datetime.fromisoformat(received_at_utc)
    if observation.tzinfo is None:
        raise ValueError("RECEIPT_TIMESTAMP_MISSING_OFFSET")
    if observation.utcoffset() != timedelta(0):
        raise ValueError("RECEIPT_TIMESTAMP_NOT_UTC")
    digest = hashlib.sha256(raw).hexdigest()
    output_dir.mkdir(parents=True, exist_ok=True)
    archive_path = output_dir / f"ghcnh-stations_{digest}.txt"
    if archive_path.exists():
        if hashlib.sha256(archive_path.read_bytes()).hexdigest() != digest:
            raise ValueError("EXISTING_STATION_ARCHIVE_CONFLICT")
    else:
        with archive_path.open("xb") as dest:
            dest.write(raw)

    receipt: dict[str, object] = {
        "schema": "NOAA_GHCNH_STATION_CATALOG_RECEIPT_V1",
        "provider": "NOAA_NCEI_GHCNH",
        "source_url": SOURCE_URL,
        "received_at_utc": received_at_utc,
        "raw_sha256": digest,
        "raw_bytes": len(raw),
        "raw_path": str(archive_path),
        "nonempty_line_count": stats["nonempty_line_count"],
        "parsed_station_count": None,
        "dataset_type": "STATION_METADATA_NOT_WEATHER_OBSERVATIONS",
        "data_rights": "NOAA_OPEN_DATA_REQUEST_ATTRIBUTION_NO_ENDORSEMENT",
        "historic_forecast_vintage_proven": False,
        "stadium_roof_proven": False,
        "station_venue_binding_proven": False,
        "weather_observation_proven": False,
        "pit_available": False,
        "model_p": None,
        "pricing_input": False,
        "play_eligible": False,
        "research_only": True,
        "reason": "STATION_SCHEMA_AND_WEATHER_OBSERVATIONS_NOT_ADMITTED",
    }
    timestamp = observation.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    manifest_path = output_dir / f"ghcnh-stations_{timestamp}_{digest[:12]}.json"
    with manifest_path.open("x", encoding="utf-8") as dest:
        json.dump(receipt, dest, indent=2, sort_keys=True)
        dest.write("\n")
    return receipt


def _fetch_official() -> tuple[bytes, str]:
    request = Request(
        SOURCE_URL, headers={"User-Agent": "SportsEdge-research-archive/1.0"}
    )
    with urlopen(request, timeout=30) as response:
        destination = urlparse(response.geturl())
        if (
            destination.scheme != "https"
            or destination.hostname != "www.ncei.noaa.gov"
            or destination.path != urlparse(SOURCE_URL).path
            or destination.query
            or destination.fragment
            or destination.username is not None
            or destination.password is not None
            or destination.port is not None
        ):
            raise ValueError("UNVERIFIED_NCEI_REDIRECT")
        if response.status != 200:
            raise ValueError("HTTP_NOT_200")
        raw = response.read(MAX_STATIONS_BYTES + 1)
    received_at = datetime.now(timezone.utc).isoformat()
    if len(raw) > MAX_STATIONS_BYTES:
        raise ValueError("STATION_LIST_TOO_LARGE")
    return raw, received_at


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", action="store_true", help="Explicit public network opt-in")
    ap.add_argument("--output-dir", type=Path, help="Local append-only archive")
    args = ap.parse_args(argv)
    if not args.live:
        print(json.dumps({"status": "DISABLED_REQUIRES_LIVE", "pricing_input": False}))
        return 0
    if args.output_dir is None:
        ap.error("--output-dir required with --live")
    try:
        raw, observed = _fetch_official()
        manifest = archive_station_list(args.output_dir, raw, observed)
    except (HTTPError, URLError, OSError, ValueError) as exc:
        print(f"NOAA_GHCNH_STATIONS_BLOCKED: {type(exc).__name__}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
