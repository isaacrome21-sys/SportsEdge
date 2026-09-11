#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable


def _sha256_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _utc_timestamp(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit("CFB_PROP_SOURCE_ATTESTATION_RETRIEVAL_TIME_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise SystemExit("CFB_PROP_SOURCE_ATTESTATION_RETRIEVAL_TIME_MUST_BE_AWARE")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _open_rows(path: Path) -> Iterable[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit("CFB_PROP_SOURCE_ATTESTATION_HEADER_REQUIRED")
        yield from reader


def _team_keys(row: dict[str, str]) -> list[str]:
    keys: list[str] = []
    for id_key, name_key in (("homeTeamId", "homeTeamName"), ("awayTeamId", "awayTeamName")):
        value = str(row.get(id_key) or "").strip()
        if not value:
            value = str(row.get(name_key) or "").strip()
        if value:
            keys.append(value)
    return keys


def build_attestation(
    *, source: Path, retrieval_time_utc: str, upstream_url: str,
    upstream_sha256: str, normalized_from: str,
) -> dict:
    if not source.is_file() or source.stat().st_size <= 0:
        raise SystemExit("CFB_PROP_SOURCE_ATTESTATION_SOURCE_REQUIRED")
    upstream_hash = str(upstream_sha256 or "").strip().lower()
    if len(upstream_hash) != 64 or any(ch not in "0123456789abcdef" for ch in upstream_hash):
        raise SystemExit("CFB_PROP_SOURCE_ATTESTATION_UPSTREAM_SHA256_INVALID")
    if not str(upstream_url or "").strip():
        raise SystemExit("CFB_PROP_SOURCE_ATTESTATION_UPSTREAM_URL_REQUIRED")

    row_count = 0
    teams: set[str] = set()
    for row in _open_rows(source):
        row_count += 1
        teams.update(_team_keys(row))
    if row_count <= 0:
        raise SystemExit("CFB_PROP_SOURCE_ATTESTATION_ROWS_REQUIRED")
    if not teams:
        raise SystemExit("CFB_PROP_SOURCE_ATTESTATION_TEAMS_REQUIRED")

    payload = {
        "schema_version": "CFB_PROP_TRAINING_INPUT_ATTESTATION_V1",
        "retrieved_at_utc": _utc_timestamp(retrieval_time_utc),
        "upstream": {
            "url": str(upstream_url).strip(),
            "sha256": upstream_hash,
            "format": str(normalized_from).strip() or "UNKNOWN",
        },
        "normalized_training_input": {
            "path": source.name,
            "sha256": _sha256_file(source),
            "bytes": source.stat().st_size,
            "row_count": row_count,
            "distinct_team_count": len(teams),
        },
        "sportsbook_data_used_for_fit": False,
        "promotion_authority": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    payload["attestation_sha256"] = sha256(canonical).hexdigest()
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Attest exact CFB prop training input bytes and retrieval provenance.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--retrieved-at", required=True)
    parser.add_argument("--upstream-url", required=True)
    parser.add_argument("--upstream-sha256", required=True)
    parser.add_argument("--normalized-from", default="parquet")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_attestation(
        source=Path(args.source),
        retrieval_time_utc=args.retrieved_at,
        upstream_url=args.upstream_url,
        upstream_sha256=args.upstream_sha256,
        normalized_from=args.normalized_from,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": "ATTESTED",
        "attestation_sha256": result["attestation_sha256"],
        "row_count": result["normalized_training_input"]["row_count"],
        "distinct_team_count": result["normalized_training_input"]["distinct_team_count"],
        "output": str(output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
