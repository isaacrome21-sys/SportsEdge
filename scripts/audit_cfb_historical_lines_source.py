#!/usr/bin/env python3
"""Audit the pinned free CFB historical line archive for #1070.

This script is source/provenance inspection only.  It does not feed market data
into estimate_p and it cannot authorize Truth Gate, OFFICIAL, or staking.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import gzip
from hashlib import sha1, sha256
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen

DATA_REPOSITORY = "sportsdataverse/cfbfastR-data"
DATA_COMMIT = "f5a05dc815951b8dbe18961a824f34cf154dfa61"
DATA_PATH = "betting/csv/cfb_line_odds.csv.gz"
DATA_GIT_BLOB_SHA1 = "fe568cf1ef50794c80fdbbbff6a8e1061f76528e"
DATA_URL = f"https://raw.githubusercontent.com/{DATA_REPOSITORY}/{DATA_COMMIT}/{DATA_PATH}"
UPSTREAM_SCHEMA_REPOSITORY = "sportsdataverse/cfbfastR-cfb-data"
UPSTREAM_SCHEMA_COMMIT = "7ae445ba8893175161885a5643d0611737a43b1b"
UPSTREAM_SCHEMA_PATH = "python/betting/build_line_odds.py"

# A real historical quote timestamp must be distinct from the scheduled game
# start time.  These names are accepted only if physically present in the data.
QUOTE_TIMESTAMP_CANDIDATES = {
    "captured_at",
    "captured_at_utc",
    "quote_time",
    "quote_timestamp",
    "quote_timestamp_utc",
    "snapshot_time",
    "snapshot_timestamp",
    "updated_at",
    "last_updated",
    "last_update",
}


def git_blob_sha1(content: bytes) -> str:
    return sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


def _nonempty(value: object) -> bool:
    text = str(value or "").strip()
    return text not in {"", "NA", "NaN", "nan", "null", "None"}


def _fetch() -> bytes:
    req = Request(DATA_URL, headers={"User-Agent": "SportsEdge-CFB-line-source-audit/1.0"})
    with urlopen(req, timeout=120) as response:  # noqa: S310 - immutable pinned HTTPS source
        return response.read()


def audit(raw_gzip: bytes) -> dict[str, object]:
    actual_blob = git_blob_sha1(raw_gzip)
    if actual_blob != DATA_GIT_BLOB_SHA1:
        raise RuntimeError(
            f"CFB_LINE_SOURCE_GIT_BLOB_MISMATCH:expected={DATA_GIT_BLOB_SHA1}:actual={actual_blob}"
        )

    seasons: Counter[str] = Counter()
    markets: Counter[str] = Counter()
    books: Counter[str] = Counter()
    rows = 0
    game_id_rows = 0
    line_rows = 0
    opening_line_rows = 0
    odds_rows = 0
    opening_odds_rows = 0
    season_min: int | None = None
    season_max: int | None = None

    with gzip.GzipFile(fileobj=io.BytesIO(raw_gzip), mode="rb") as gz:
        text = io.TextIOWrapper(gz, encoding="utf-8-sig", newline="")
        reader = csv.DictReader(text)
        header = list(reader.fieldnames or [])
        for row in reader:
            rows += 1
            season_text = str(row.get("season") or "").strip()
            if season_text:
                try:
                    season = int(float(season_text))
                except ValueError:
                    season = None
                if season is not None:
                    seasons[str(season)] += 1
                    season_min = season if season_min is None else min(season_min, season)
                    season_max = season if season_max is None else max(season_max, season)
            market = str(row.get("market_type") or "").strip()
            if market:
                markets[market] += 1
            book = str(row.get("book") or "").strip()
            if book:
                books[book] += 1
            game_id_rows += int(_nonempty(row.get("game_id")))
            line_rows += int(_nonempty(row.get("lines")))
            opening_line_rows += int(_nonempty(row.get("opening_lines")))
            odds_rows += int(_nonempty(row.get("odds")))
            opening_odds_rows += int(_nonempty(row.get("opening_odds")))

    quote_timestamp_columns = sorted(set(header) & QUOTE_TIMESTAMP_CANDIDATES)
    required_core = {
        "game_id",
        "season",
        "date_time",
        "market_type",
        "lines",
        "opening_lines",
        "book",
    }
    missing_core = sorted(required_core - set(header))

    # Important: date_time is a scheduled game-start field in the upstream
    # builder, not a quote-capture timestamp.  Presence of date_time therefore
    # cannot establish that `lines` was captured at or before close.
    closing_semantics_verified = bool(quote_timestamp_columns) and not missing_core
    status = "CANDIDATE_ONLY_BLOCKED_NO_QUOTE_TIMESTAMP"
    if closing_semantics_verified:
        status = "CANDIDATE_TIMESTAMP_PRESENT_REQUIRES_INDEPENDENT_CLOSE_CROSSCHECK"

    return {
        "schema": "CFB_HISTORICAL_LINE_SOURCE_AUDIT_V1",
        "status": status,
        "source": {
            "repository": DATA_REPOSITORY,
            "commit_sha": DATA_COMMIT,
            "path": DATA_PATH,
            "git_blob_sha1": actual_blob,
            "gzip_sha256": sha256(raw_gzip).hexdigest(),
            "free_public_source": True,
        },
        "upstream_schema_evidence": {
            "repository": UPSTREAM_SCHEMA_REPOSITORY,
            "commit_sha": UPSTREAM_SCHEMA_COMMIT,
            "path": UPSTREAM_SCHEMA_PATH,
            "date_time_semantics": "scheduled game start/kickoff; not quote capture time",
        },
        "header": header,
        "missing_required_core_columns": missing_core,
        "quote_timestamp_columns": quote_timestamp_columns,
        "coverage": {
            "rows": rows,
            "season_min": season_min,
            "season_max": season_max,
            "rows_by_season": dict(sorted(seasons.items(), key=lambda item: int(item[0]))),
            "rows_by_market_type": dict(sorted(markets.items())),
            "rows_by_book": dict(sorted(books.items())),
            "rows_with_game_id": game_id_rows,
            "rows_with_line": line_rows,
            "rows_with_opening_line": opening_line_rows,
            "rows_with_odds": odds_rows,
            "rows_with_opening_odds": opening_odds_rows,
        },
        "closing_semantics_verified": closing_semantics_verified,
        "truth_gate_authority": False,
        "clv_authority": False,
        "estimate_p_input_allowed": False,
        "next_gate": (
            "independent stratified cross-check of archived `lines` against known pre-kickoff closing snapshots; "
            "do not unpause CFB from this archive alone"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-file", type=Path)
    parser.add_argument("--output", type=Path, default=Path("_proof/cfb_lines/source_audit_v1.json"))
    args = parser.parse_args()

    raw = args.source_file.read_bytes() if args.source_file else _fetch()
    report = audit(raw)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
