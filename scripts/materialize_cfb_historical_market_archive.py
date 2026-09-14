#!/usr/bin/env python3
"""Materialize and profile the pinned CFB historical market archive.

This is a research-only source boundary.  It verifies transport bytes against the
checked contract and profiles the archive, but it deliberately does not certify
per-row point-in-time capture, close timestamps, CLV, Model_P, or promotion.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


def _git_blob_sha1(data: bytes) -> str:
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data).hexdigest()


def _load_contract(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("CFB_HISTORICAL_MARKET_SCHEMA_INVALID")
    if payload.get("source_id") != "CFB_HISTORICAL_MARKET_SOURCE_V1":
        raise ValueError("CFB_HISTORICAL_MARKET_SOURCE_ID_INVALID")
    if payload.get("sport") != "cfb" or payload.get("mode") != "RESEARCH_ONLY":
        raise ValueError("CFB_HISTORICAL_MARKET_MODE_INVALID")
    authority = payload.get("authority") or {}
    for field in (
        "model_p_authority",
        "truth_gate_authority",
        "promotion_authority",
        "staking_authority",
        "official_bet_authority",
    ):
        if authority.get(field) is not False:
            raise ValueError(f"CFB_HISTORICAL_MARKET_FORBIDDEN_AUTHORITY:{field}")
    limits = payload.get("evidence_limitations") or {}
    for field in (
        "per_row_pit_certified",
        "decision_time_certified",
        "close_time_certified",
        "clv_authority",
    ):
        if limits.get(field) is not False:
            raise ValueError(f"CFB_HISTORICAL_MARKET_EVIDENCE_LIMIT_INVALID:{field}")
    return payload


def _validate_bytes(
    data: bytes, contract: dict[str, Any], *, allow_bootstrap_sha256: bool
) -> dict[str, Any]:
    upstream = contract["upstream"]
    observed = {
        "size_bytes": len(data),
        "git_blob_sha1": _git_blob_sha1(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    if observed["size_bytes"] != int(upstream["expected_size_bytes"]):
        raise ValueError("CFB_HISTORICAL_MARKET_SIZE_MISMATCH")
    if observed["git_blob_sha1"] != upstream["git_blob_sha1"]:
        raise ValueError("CFB_HISTORICAL_MARKET_GIT_BLOB_MISMATCH")
    expected_sha256 = upstream.get("expected_sha256")
    if expected_sha256 is None:
        if not allow_bootstrap_sha256:
            raise ValueError("CFB_HISTORICAL_MARKET_SHA256_UNPINNED")
    elif observed["sha256"] != expected_sha256:
        raise ValueError("CFB_HISTORICAL_MARKET_SHA256_MISMATCH")
    return observed


def _profile_archive(data: bytes, contract: dict[str, Any]) -> dict[str, Any]:
    required = list(contract["required_columns"])
    row_count = 0
    seasons: set[int] = set()
    markets: Counter[str] = Counter()
    books: Counter[str] = Counter()
    null_fields = Counter()
    tracked_nulls = (
        "game_id",
        "date_time",
        "lines",
        "odds",
        "opening_lines",
        "opening_odds",
        "book",
        "home_team_id",
        "away_team_id",
    )

    try:
        raw = gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb")
        text = io.TextIOWrapper(raw, encoding="utf-8", newline="")
        reader = csv.DictReader(text)
        header = reader.fieldnames or []
        missing = [column for column in required if column not in header]
        if missing:
            raise ValueError("CFB_HISTORICAL_MARKET_COLUMNS_MISSING:" + ",".join(missing))
        for row in reader:
            row_count += 1
            season_text = (row.get("season") or "").strip()
            if season_text:
                seasons.add(int(float(season_text)))
            market = (row.get("market_type") or "").strip()
            if market:
                markets[market] += 1
            book = (row.get("book") or "").strip()
            if book:
                books[book] += 1
            for field in tracked_nulls:
                if not (row.get(field) or "").strip():
                    null_fields[field] += 1
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError("CFB_HISTORICAL_MARKET_ARCHIVE_INVALID") from exc

    documented = contract["documented_history"]
    if row_count != int(documented["documented_row_count"]):
        raise ValueError("CFB_HISTORICAL_MARKET_ROW_COUNT_MISMATCH")
    if not seasons:
        raise ValueError("CFB_HISTORICAL_MARKET_SEASONS_MISSING")
    if min(seasons) != int(documented["season_start"]) or max(seasons) != int(
        documented["season_end"]
    ):
        raise ValueError("CFB_HISTORICAL_MARKET_SEASON_RANGE_MISMATCH")

    return {
        "row_count": row_count,
        "season_min": min(seasons),
        "season_max": max(seasons),
        "season_count": len(seasons),
        "seasons": sorted(seasons),
        "market_type_counts": dict(sorted(markets.items())),
        "book_counts": dict(sorted(books.items())),
        "book_count": len(books),
        "null_counts": {field: int(null_fields[field]) for field in tracked_nulls},
        "required_columns": required,
    }


def materialize(
    *,
    contract_path: Path,
    attestation_path: Path,
    archive_path: Path | None,
    allow_bootstrap_sha256: bool,
) -> dict[str, Any]:
    contract = _load_contract(contract_path)
    request = urllib.request.Request(
        contract["upstream"]["raw_url"],
        headers={"User-Agent": "SportsEdge-CFB-Historical-Market-Freeze/1"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = response.read()

    observed = _validate_bytes(
        data, contract, allow_bootstrap_sha256=allow_bootstrap_sha256
    )
    profile = _profile_archive(data, contract)
    expected_sha256 = contract["upstream"].get("expected_sha256")
    status = "PASS" if expected_sha256 else "BOOTSTRAP_SHA256_OBSERVED"
    attestation = {
        "schema_version": 1,
        "attestation_id": "CFB_HISTORICAL_MARKET_ATTESTATION_V1",
        "status": status,
        "source_id": contract["source_id"],
        "mode": "RESEARCH_ONLY",
        "upstream": {
            "repository": contract["upstream"]["repository"],
            "commit": contract["upstream"]["commit"],
            "path": contract["upstream"]["path"],
            "raw_url": contract["upstream"]["raw_url"],
        },
        "observed": observed,
        "profile": profile,
        "evidence_limitations": contract["evidence_limitations"],
        "authority": contract["authority"],
        "pit_certified": False,
        "clv_authority": False,
        "promotion_authority": False,
    }
    attestation_path.parent.mkdir(parents=True, exist_ok=True)
    attestation_path.write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if archive_path is not None:
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_bytes(data)
    print(json.dumps(attestation, sort_keys=True))
    return attestation


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="config/research/cfb_historical_market_source_v1.json",
    )
    parser.add_argument(
        "--attestation-out",
        default="artifacts/cfb/history/cfb_historical_market_attestation.json",
    )
    parser.add_argument("--archive-out", default=None)
    parser.add_argument("--allow-bootstrap-sha256", action="store_true")
    args = parser.parse_args()
    materialize(
        contract_path=Path(args.config),
        attestation_path=Path(args.attestation_out),
        archive_path=Path(args.archive_out) if args.archive_out else None,
        allow_bootstrap_sha256=args.allow_bootstrap_sha256,
    )


if __name__ == "__main__":
    main()
