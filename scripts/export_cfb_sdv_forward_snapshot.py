#!/usr/bin/env python3
"""Export immutable-input, pregame CFB side/total forecast observations.

Only the contemporaneously captured SportsDataverse native-score card can
produce a snapshot. This records model forecasts, NOT certified odds, positive
EV, or an accepted prediction track record. A later GitHub Actions audit must
independently attest the source run and settle games without backfill.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

SCHEMA = "CFB_SDV_FORWARD_SCORE_SNAPSHOT_V1"
SOURCE_CONTRACT = "CFB_SDV_PUBLIC_PROSPECTIVE_2026_V1"


def _utc(value, field):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("offset required")
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("CFB_FORWARD_TIMESTAMP_INVALID:" + field) from exc


def _number(value, field):
    if isinstance(value, bool):
        raise ValueError("CFB_FORWARD_NUMERIC_INVALID:" + field)
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CFB_FORWARD_NUMERIC_INVALID:" + field) from exc
    if not isfinite(v):
        raise ValueError("CFB_FORWARD_NUMERIC_INVALID:" + field)
    return v


def export_snapshot(card: dict, *, original_card_sha256: str):
    if not isinstance(card, dict) or card.get("schema") != "CFB_SDV_CARD_V2":
        raise ValueError("CFB_FORWARD_CARD_SCHEMA_INVALID")
    if (not isinstance(original_card_sha256, str) or len(original_card_sha256) != 64 or
            any(c not in "0123456789abcdef" for c in original_card_sha256)):
        raise ValueError("CFB_FORWARD_CARD_HASH_INVALID")
    rows = card.get("results")
    if not isinstance(rows, list):
        raise ValueError("CFB_FORWARD_ROWS_INVALID")

    base = {
        "schema": SCHEMA,
        "source_card_sha256": original_card_sha256,
        "source_card_schema": card["schema"],
        "source_model_status": card.get("model_status"),
        "evidence_role": "PROSPECTIVE_RESEARCH_MODEL_FORECAST_NOT_VALIDATED",
        "source_run_independently_attested": False,
        "sportsbook_price_receipt_verified": False,
        "closing_lines_joined": False,
        "settled_outcomes_joined": False,
        "positive_ev_proven": False,
        "bets_enabled": False,
        "staking_authority": False,
        "games": [],
    }
    # Market-only fallbacks are not model predictions; do not create forecasts
    # from sportsbook implied scores.
    if card.get("model_status") != "MODEL_SDV_PUBLIC_LIVE_UNVALIDATED":
        base["status"] = "NO_MODEL_PREGAME_FORECASTS"
        return base

    provenance = card.get("live_source_provenance")
    if not isinstance(provenance, dict) or provenance.get("source_contract") != SOURCE_CONTRACT:
        raise ValueError("CFB_FORWARD_NATIVE_SOURCE_REQUIRED")
    sources = provenance.get("file_sha256")
    if not isinstance(sources, dict) or len(sources) != 8:
        raise ValueError("CFB_FORWARD_SOURCE_RECEIPTS_REQUIRED")
    for filename, digest in sources.items():
        if (not isinstance(filename, str) or not filename or
                not isinstance(digest, str) or len(digest) != 64 or
                any(c not in "0123456789abcdef" for c in digest)):
            raise ValueError("CFB_FORWARD_SOURCE_HASH_INVALID")
    source_time = _utc(provenance.get("capture_time"), "source_capture")
    score_time = _utc(card.get("scored_at_utc"), "scored_at_utc")
    if score_time < source_time:
        raise ValueError("CFB_FORWARD_SCORED_BEFORE_SOURCE")
    if int(card.get("bets", 0)) != 0 or card.get("validated_markets"):
        raise ValueError("CFB_FORWARD_ZERO_BET_AUTHORITY_REQUIRED")

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("CFB_FORWARD_ROW_INVALID")
        if row.get("market") not in {"MONEYLINE", "SPREAD", "TOTAL"}:
            continue
        key = str(row.get("game_id") or "")
        if not key:
            raise ValueError("CFB_FORWARD_GAME_ID_REQUIRED")
        grouped.setdefault(key, []).append(row)

    games = []
    for game_id, selections in sorted(grouped.items()):
        seen = set()
        for row in selections:
            signature = (row["market"], row.get("side"), row.get("line"))
            if signature in seen:
                raise ValueError("CFB_FORWARD_DUPLICATE_MARKET_SIDE:" + game_id)
            seen.add(signature)
        ref = selections[0]
        home = _number(ref.get("home_mean"), "home_mean")
        away = _number(ref.get("away_mean"), "away_mean")
        if not 0 <= home <= 75 or not 0 <= away <= 75:
            raise ValueError("CFB_FORWARD_SCORE_OUT_OF_BOUNDS:" + game_id)
        matchup = str(ref.get("matchup") or "")
        if not matchup:
            raise ValueError("CFB_FORWARD_MATCHUP_REQUIRED:" + game_id)
        kickoff = _utc(ref.get("start_ts"), "start_ts")
        for row in selections[1:]:
            if (str(row.get("matchup")) != matchup or
                    _utc(row.get("start_ts"), "start_ts") != kickoff or
                    abs(_number(row.get("home_mean"), "home_mean") - home) > 0.02 or
                    abs(_number(row.get("away_mean"), "away_mean") - away) > 0.02):
                raise ValueError("CFB_FORWARD_SELECTION_SCORE_MISMATCH:" + game_id)
        # A prediction timestamp at/after kickoff is a missed observation,
        # never retrofit its forecast as if captured pregame.
        if score_time >= kickoff:
            continue
        games.append({
            "game_id": game_id,
            "matchup": matchup,
            "kickoff_at": kickoff.isoformat(),
            "home_mean": home,
            "away_mean": away,
            "model_margin": round(home - away, 4),
            "model_total": round(home + away, 4),
            "source_capture_at": source_time.isoformat(),
            "scored_at": score_time.isoformat(),
            "source_contract": SOURCE_CONTRACT,
        })
    base.update({
        "status": "PREGAME_MODEL_SNAPSHOTS_UNVALIDATED" if games else "NO_PREGAME_MODEL_ROWS",
        "source_file_sha256": sources,
        "source_capture_at": source_time.isoformat(),
        "scored_at": score_time.isoformat(),
        "games": games,
    })
    return base


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--card", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args(argv)
    raw = args.card.read_bytes()
    snapshot = export_snapshot(json.loads(raw), original_card_sha256=hashlib.sha256(raw).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print("CFB_FORWARD_SNAPSHOT status=%s games=%d zero_bet_authority=1" %
          (snapshot["status"], len(snapshot["games"])))


if __name__ == "__main__":
    main()
