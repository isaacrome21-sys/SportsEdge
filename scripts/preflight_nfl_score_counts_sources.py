#!/usr/bin/env python3
"""Verify NFL_SCORE_COUNTS_G1 frozen bytes and raw schema without consuming an attempt."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

FORBIDDEN_TOKENS = (
    "odds", "price", "sportsbook", "market", "spread_line", "total_line",
    "closing", "opening", "implied", "vig", "handle", "tickets",
)
PBP_REQUIRED_ANY = (("game_id", "nflverse_game_id"),)
PBP_REQUIRED = ("posteam", "defteam")
DEPTH_REQUIRED = ("season", "week")
SCHEDULE_REQUIRED = ("season", "week", "home_team", "away_team")
SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_G1_SOURCE_PREFLIGHT_V1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_exact(uri: str, target: Path, expected: str, retries: int = 4) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".partial")
    tmp.unlink(missing_ok=True)
    last = None
    for attempt in range(retries):
        try:
            req = Request(uri, headers={"User-Agent": "SportsEdge-score-count-preflight/1"})
            with urlopen(req, timeout=90) as response, tmp.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            got = sha256_file(tmp)
            if got != expected:
                raise ValueError(f"SHA256_MISMATCH:{target.name}:expected={expected}:got={got}")
            os.replace(tmp, target)
            return
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            tmp.unlink(missing_ok=True)
            if attempt + 1 < retries:
                time.sleep(2)
    raise RuntimeError(f"DOWNLOAD_FAILED:{uri}:{last}")


def csv_header(path: Path) -> list[str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as f:
        row = next(csv.reader(f), None)
    if not row:
        raise ValueError(f"EMPTY_CSV:{path}")
    return [str(x).strip() for x in row]


def forbidden_columns(columns: list[str]) -> list[str]:
    return sorted(c for c in columns if any(t in c.lower() for t in FORBIDDEN_TOKENS))


def assert_required(columns: list[str], required: tuple[str, ...], label: str) -> None:
    missing = [x for x in required if x not in columns]
    if missing:
        raise ValueError(f"REQUIRED_COLUMNS_MISSING:{label}:{','.join(missing)}")


def inspect_contract(contract: dict, root: Path) -> dict:
    rows = []
    schedule = contract["schedule"]
    schedule_path = root / "games.csv"
    download_exact(schedule["fetch_uri"], schedule_path, schedule["expected_sha256"])
    schedule_cols = csv_header(schedule_path)
    assert_required(schedule_cols, SCHEDULE_REQUIRED, "schedule")
    rows.append({
        "name": "schedule", "sha256": sha256_file(schedule_path),
        "columns": schedule_cols, "forbidden_columns": forbidden_columns(schedule_cols),
        "raw_parser_policy": "SCHEDULE_EXTRAS_IGNORED_BY_FEATURE_BUILDER",
    })

    for family, ext in (("pbp", ".csv.gz"), ("depth", ".csv")):
        for season in range(2018, 2026):
            spec = contract[family][str(season)]
            path = root / family / f"{family}_{season}{ext}"
            download_exact(spec["fetch_uri"], path, spec["expected_sha256"])
            cols = csv_header(path)
            if family == "pbp":
                if not all(any(x in cols for x in group) for group in PBP_REQUIRED_ANY):
                    raise ValueError(f"REQUIRED_COLUMNS_MISSING:pbp_{season}:game_id")
                assert_required(cols, PBP_REQUIRED, f"pbp_{season}")
            else:
                assert_required(cols, DEPTH_REQUIRED, f"depth_{season}")
            rows.append({
                "name": f"{family}_{season}", "sha256": sha256_file(path),
                "columns": cols, "forbidden_columns": forbidden_columns(cols),
            })

    pbp_bad = sorted({c for row in rows if row["name"].startswith("pbp_") for c in row["forbidden_columns"]})
    depth_bad = sorted({c for row in rows if row["name"].startswith("depth_") for c in row["forbidden_columns"]})
    return {
        "schema": SCHEMA,
        "candidate_family": "NFL_SCORE_COUNTS_G1",
        "status": "PASS" if not pbp_bad and not depth_bad else "RAW_SCHEMA_REQUIRES_EXPLICIT_PROJECTION",
        "verified_exact_sources": len(rows),
        "pbp_forbidden_raw_columns": pbp_bad,
        "depth_forbidden_raw_columns": depth_bad,
        "raw_rows_directly_compatible_with_current_market_blind_guard": not (pbp_bad or depth_bad),
        "attempt_consumed": False,
        "historical_scoring_performed": False,
        "model_fit_performed": False,
        "authority": {
            "research_only": True, "creates_model_p": False, "pricing": False,
            "promotion": False, "staking": False, "official": False, "backfill": False,
        },
        "sources": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", type=Path, default=Path("config/research/nfl_score_counts_g1_source_contract_v1.json"))
    ap.add_argument("--root", type=Path, default=Path("artifacts/football/score_counts/source_preflight"))
    ap.add_argument("--out", type=Path, default=Path("artifacts/football/score_counts/source_preflight.json"))
    args = ap.parse_args()
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    if contract.get("schema") != "SPORTSEDGE_NFL_SCORE_COUNTS_G1_SOURCE_CONTRACT_V1":
        raise SystemExit("SOURCE_CONTRACT_SCHEMA_INVALID")
    result = inspect_contract(contract, args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "pbp_forbidden_raw_columns": result["pbp_forbidden_raw_columns"],
        "depth_forbidden_raw_columns": result["depth_forbidden_raw_columns"],
        "attempt_consumed": False,
    }, sort_keys=True))
    if result["status"] != "PASS":
        raise SystemExit("NFL_SCORE_COUNTS_SOURCE_SCHEMA_NOT_DIRECTLY_PARSER_COMPATIBLE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
