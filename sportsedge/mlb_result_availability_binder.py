"""Strict point-in-time result availability attestation binder.

Attestations are explicit source records, not timestamps inferred from game
starts, archive download times or file modification times. This module checks
internal integrity only; it cannot independently authenticate a publisher.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from sportsedge.mlb_period_counts_empirical import _instant


def bind_result_availability(export_path, attestation_path, output_path) -> dict:
    source = Path(export_path)
    attest = Path(attestation_path)
    destination = Path(output_path)
    if destination.exists():
        raise FileExistsError("OUTPUT_ALREADY_EXISTS")
    if destination.resolve() in (source.resolve(), attest.resolve()):
        raise ValueError("OUTPUT_OVERLAPS_INPUT")
    raw = source.read_bytes()
    evidence = json.loads(attest.read_text(encoding="utf-8"))
    if not isinstance(evidence, dict) or evidence.get("schema") != "MLB_RESULT_AVAILABILITY_ATTESTATIONS_V1":
        raise ValueError("INVALID_ATTESTATION_SCHEMA")
    if evidence.get("export_sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("EXPORT_HASH_MISMATCH")
    rows = evidence.get("results")
    if not isinstance(rows, list) or not rows:
        raise ValueError("EMPTY_ATTESTATIONS")
    keyed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("INVALID_ATTESTATION")
        game_id = row.get("game_id")
        timestamp = row.get("result_available_at")
        url = row.get("source_url")
        digest = row.get("source_sha256")
        if (not isinstance(game_id, str) or not game_id or game_id in keyed
                or not isinstance(timestamp, str)
                or not isinstance(url, str) or not url.startswith("https://")
                or not isinstance(digest, str) or len(digest) != 64
                or any(ch not in "0123456789abcdef" for ch in digest)):
            raise ValueError("INVALID_OR_DUPLICATE_ATTESTATION")
        _instant(timestamp)
        keyed[game_id] = row
    payload = json.loads(raw)
    if payload.get("schema") != "MLB_HISTORICAL_INNING_EXPORT_V1":
        raise ValueError("INVALID_EXPORT_SCHEMA")
    games = payload.get("games")
    if not isinstance(games, list) or not games or any(not isinstance(g, dict) for g in games):
        raise ValueError("INVALID_EXPORT_GAMES")
    if any(not isinstance(g.get("game_id"), (str, int)) or isinstance(g.get("game_id"), bool)
           or not str(g.get("game_id")) for g in games):
        raise ValueError("INVALID_EXPORT_GAME_ID")
    game_ids = [str(g["game_id"]) for g in games]
    if len(set(game_ids)) != len(game_ids):
        raise ValueError("DUPLICATE_EXPORT_GAME")
    if set(game_ids) != set(keyed):
        raise ValueError("ATTESTATION_GAME_SET_MISMATCH")
    observed = _instant(payload.get("observed_at"))
    for game in games:
        a = keyed[str(game["game_id"])]
        if not (_instant(game["start_time"]) < _instant(a["result_available_at"]) <= observed):
            raise ValueError("INVALID_RESULT_AVAILABILITY")
        game["result_available_at"] = a["result_available_at"]
    # Require local source snapshots to match claimed hashes. A bare digest
    # string is not evidence that any underlying record was supplied.
    source_root = attest.resolve().parent
    for a in keyed.values():
        relative = a.get("source_path")
        if not isinstance(relative, str) or not relative:
            raise ValueError("MISSING_ATTESTATION_SOURCE_SNAPSHOT")
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("UNSAFE_ATTESTATION_SOURCE_PATH")
        snapshot = (source_root / rel).resolve()
        if not snapshot.is_relative_to(source_root) or not snapshot.is_file() or (source_root / rel).is_symlink():
            raise ValueError("MISSING_ATTESTATION_SOURCE_SNAPSHOT")
        if hashlib.sha256(snapshot.read_bytes()).hexdigest() != a["source_sha256"]:
            raise ValueError("ATTESTATION_SOURCE_HASH_MISMATCH")
    payload["availability_attestation_sha256"] = hashlib.sha256(attest.read_bytes()).hexdigest()
    payload["availability_attestation_authenticity_verified"] = False
    payload["play_authorized"] = False
    with destination.open("x", encoding="utf-8") as out:
        json.dump(payload, out, indent=2, sort_keys=True)
        out.write("\n")
    return payload
