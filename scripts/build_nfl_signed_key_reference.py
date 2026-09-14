#!/usr/bin/env python3
"""Build the frozen NFL signed key-number reference from final scores only.

This is structural outcome reference data, never Model_P and never market evidence.
The source is pinned nflverse/nfldata games.csv. The table uses final scores
(including overtime when played), regular-season games only, and the source's
home designation even for neutral-site games. Signed margin = home_score-away_score.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import urllib.request
from pathlib import Path

SOURCE_REPO = "nflverse/nfldata"
SOURCE_COMMIT = "12e738870227f0f629e0bd16d27a1ffe026369e9"
SOURCE_PATH = "data/games.csv"
SOURCE_GIT_BLOB_SHA1 = "942af628c3af2e418e0ee302e5a85c3c0168a4ad"
SOURCE_SIZE_BYTES = 2177521
SOURCE_URL = f"https://raw.githubusercontent.com/{SOURCE_REPO}/{SOURCE_COMMIT}/{SOURCE_PATH}"
SEASON_MIN = 2002
SEASON_MAX = 2025
KEYS = (-7, -3, 3, 7)


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def wilson95(k: int, n: int) -> list[float]:
    if n <= 0:
        raise ValueError("NFL_KEY_REFERENCE_EMPTY")
    z = 1.959963984540054
    p = k / n
    den = 1 + z*z/n
    center = (p + z*z/(2*n))/den
    half = z*math.sqrt((p*(1-p)+z*z/(4*n))/n)/den
    return [round(max(0.0, center-half), 8), round(min(1.0, center+half), 8)]


def build(data: bytes) -> dict:
    if len(data) != SOURCE_SIZE_BYTES:
        raise ValueError("NFL_KEY_REFERENCE_SOURCE_SIZE_MISMATCH")
    if git_blob_sha1(data) != SOURCE_GIT_BLOB_SHA1:
        raise ValueError("NFL_KEY_REFERENCE_SOURCE_BLOB_MISMATCH")
    text = io.StringIO(data.decode("utf-8"), newline="")
    reader = csv.DictReader(text)
    required = {"season", "game_type", "home_score", "away_score"}
    if not required.issubset(set(reader.fieldnames or [])):
        raise ValueError("NFL_KEY_REFERENCE_SOURCE_SCHEMA_MISMATCH")
    margins: list[int] = []
    overtime_games = 0
    neutral_games = 0
    for row in reader:
        try:
            season = int(row["season"])
        except (TypeError, ValueError):
            continue
        if not SEASON_MIN <= season <= SEASON_MAX or row.get("game_type") != "REG":
            continue
        try:
            hs = int(float(row["home_score"]))
            aw = int(float(row["away_score"]))
        except (TypeError, ValueError):
            continue
        margins.append(hs-aw)
        if str(row.get("overtime") or "").strip().lower() in {"1", "true", "t", "yes"}:
            overtime_games += 1
        if str(row.get("location") or "").strip().lower() in {"neutral", "n"}:
            neutral_games += 1
    n = len(margins)
    if n < 1000:
        raise ValueError("NFL_KEY_REFERENCE_SAMPLE_TOO_SMALL")
    signed = {}
    for key in KEYS:
        count = sum(m == key for m in margins)
        signed[str(key)] = {
            "count": count,
            "probability": round(count/n, 8),
            "wilson95": wilson95(count, n),
        }
    abs3 = sum(abs(m) == 3 for m in margins)
    abs7 = sum(abs(m) == 7 for m in margins)
    return {
        "schema_version": 1,
        "reference_id": "NFL_SIGNED_KEY_NUMBER_REFERENCE_V1",
        "status": "FROZEN_STRUCTURAL_REFERENCE",
        "sport": "NFL",
        "authority": {
            "model_p_authority": False,
            "market_evidence_authority": False,
            "clv_authority": False,
            "promotion_authority": False,
            "official_bet_authority": False,
        },
        "source": {
            "repository": SOURCE_REPO,
            "commit": SOURCE_COMMIT,
            "path": SOURCE_PATH,
            "git_blob_sha1": SOURCE_GIT_BLOB_SHA1,
            "size_bytes": SOURCE_SIZE_BYTES,
            "sha256": hashlib.sha256(data).hexdigest(),
        },
        "population": {
            "season_min": SEASON_MIN,
            "season_max": SEASON_MAX,
            "game_type": "REG",
            "n": n,
            "neutral_sites": "INCLUDED_USING_SOURCE_DESIGNATED_HOME",
            "neutral_game_count": neutral_games,
            "overtime_rule": "FINAL_SCORE_INCLUDES_OVERTIME",
            "overtime_game_count_if_source_flag_available": overtime_games,
            "sign_convention": "HOME_SCORE_MINUS_AWAY_SCORE",
        },
        "signed_keys": signed,
        "absolute_key_mass": {
            "3": {"count": abs3, "probability": round(abs3/n, 8), "wilson95": wilson95(abs3, n)},
            "7": {"count": abs7, "probability": round(abs7/n, 8), "wilson95": wilson95(abs7, n)},
        },
        "candidate_gate_usage": "REFERENCE_ONLY; CANDIDATE_MUST_USE_FROZEN_TOLERANCE_POLICY_SEPARATELY",
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", default="artifacts/nfl/nfl_signed_key_reference_v1.json")
    args = p.parse_args()
    req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "SportsEdge-NFL-Key-Reference/1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    result = build(data)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
