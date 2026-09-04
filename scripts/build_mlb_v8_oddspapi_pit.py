#!/usr/bin/env python3
"""Normalize OddsPapi histories into hash-bound MLB V8 PIT quote pairs.

This is an evidence normalizer, not a model backtest. It admits only genuine
provider timestamps and synchronized complementary prices. It never infers a
missing side, resurrects a deactivated quote, changes a line, or treats a
post-first-pitch quote as pregame.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path("artifacts/mlb_v8_replay_sources/ODDSPAPI_HISTORICAL")
DEFAULT_OUT = Path("artifacts/mlb_v8_replay_archive/oddspapi_pit")
DECISION_MINUTES = 30
CANONICAL_TOLERANCE_SECONDS = 6 * 60
REPLAY_QUOTE_MAX_AGE_SECONDS = 180
PAIR_MAX_SKEW_SECONDS = 30


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _parse_ts(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _verify_raw(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    meta_path = path.with_name(path.stem + ".meta.json")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("source") != "ODDSPAPI_HISTORICAL":
        raise RuntimeError(f"ODDSPAPI_SOURCE_MISMATCH:{path}")
    if str(meta.get("payload_sha256") or "") != _sha(raw):
        raise RuntimeError(f"ODDSPAPI_RAW_SHA_MISMATCH:{path}")
    return raw, meta


def _load_catalog(root: Path) -> tuple[dict[str, dict[str, Any]], str]:
    path = root / "catalog" / "markets.json"
    raw = path.read_bytes()
    meta = json.loads((root / "catalog" / "markets.meta.json").read_text(encoding="utf-8"))
    if str(meta.get("payload_sha256") or "") != _sha(raw):
        raise RuntimeError("ODDSPAPI_MARKET_CATALOG_SHA_MISMATCH")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, list):
        raise RuntimeError("ODDSPAPI_MARKET_CATALOG_INVALID")
    return {
        str(x.get("marketId")): dict(x)
        for x in payload if isinstance(x, dict) and x.get("marketId") is not None
    }, _sha(raw)


def _catalog_outcomes(info: dict[str, Any]) -> dict[str, str]:
    return {
        str(x.get("outcomeId")): str(x.get("outcomeName") or "")
        for x in info.get("outcomes", [])
        if isinstance(x, dict) and x.get("outcomeId") is not None
    }


def _timeline(outcome: dict[str, Any], player_id: str) -> list[dict[str, Any]]:
    rows = ((outcome.get("players") or {}).get(player_id)) or []
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ts = _parse_ts(row.get("createdAt"))
        except Exception:
            continue
        price = None
        try:
            if row.get("price") is not None:
                price = float(row.get("price"))
        except (TypeError, ValueError):
            price = None
        out.append({**row, "_ts": ts, "_price": price, "_active": row.get("active") is True})
    out.sort(key=lambda x: x["_ts"])
    return out


def _state_at(timeline: list[dict[str, Any]], cutoff: datetime) -> dict[str, Any] | None:
    eligible = [x for x in timeline if x["_ts"] <= cutoff]
    if not eligible:
        return None
    state = eligible[-1]
    # A later active=false record explicitly means the quote was no longer
    # executable. Never skip backward to resurrect an earlier active quote.
    if state.get("_active") is not True:
        return None
    price = state.get("_price")
    if price is None or price <= 1.0:
        return None
    return state


def _state_pair(
    left: list[dict[str, Any]], right: list[dict[str, Any]], *, cutoff: datetime,
    max_age_seconds: float | None,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    a = _state_at(left, cutoff)
    b = _state_at(right, cutoff)
    if a is None or b is None:
        return None
    age_a = (cutoff - a["_ts"]).total_seconds()
    age_b = (cutoff - b["_ts"]).total_seconds()
    if age_a < 0 or age_b < 0:
        return None
    if max_age_seconds is not None and (age_a > max_age_seconds or age_b > max_age_seconds):
        return None
    if abs((a["_ts"] - b["_ts"]).total_seconds()) > PAIR_MAX_SKEW_SECONDS:
        return None
    return a, b


def _player_ids(outcomes: list[dict[str, Any]]) -> list[str]:
    if len(outcomes) != 2:
        return []
    left = set(str(x) for x in (outcomes[0].get("players") or {}).keys())
    right = set(str(x) for x in (outcomes[1].get("players") or {}).keys())
    return sorted(left & right)


def _pair_row(
    *, fixture: dict[str, Any], history_path: Path, history_sha: str,
    book: str, market_id: str, info: dict[str, Any], outcome_ids: tuple[str, str],
    player_id: str, decision: tuple[dict[str, Any], dict[str, Any]],
    close: tuple[dict[str, Any], dict[str, Any]] | None, catalog_sha: str,
) -> dict[str, Any]:
    first_pitch = _parse_ts(fixture["startTime"])
    target = first_pitch - timedelta(minutes=DECISION_MINUTES)
    a, b = decision
    names = _catalog_outcomes(info)
    age_a = (target - a["_ts"]).total_seconds()
    age_b = (target - b["_ts"]).total_seconds()
    skew = abs((a["_ts"] - b["_ts"]).total_seconds())
    row = {
        "schema": "MLB_V8_ODDSPAPI_PIT_PAIR_V1",
        "source": "ODDSPAPI_HISTORICAL",
        "fixture_id": str(fixture.get("fixtureId")),
        "slate_date_utc": first_pitch.date().isoformat(),
        "participant1_name": fixture.get("participant1Name"),
        "participant2_name": fixture.get("participant2Name"),
        "first_pitch_utc": first_pitch.isoformat(),
        "decision_target_utc": target.isoformat(),
        "decision_target_minutes_before_first_pitch": DECISION_MINUTES,
        "bookmaker": book,
        "market_id": market_id,
        "market_name": info.get("marketName"),
        "market_type": info.get("marketType"),
        "period": info.get("period"),
        "handicap": info.get("handicap"),
        "player_prop": info.get("playerProp"),
        "player_id": player_id,
        "outcome_a_id": outcome_ids[0],
        "outcome_a_name": names.get(outcome_ids[0]),
        "outcome_a_decimal": a["_price"],
        "outcome_a_quote_utc": a["_ts"].isoformat(),
        "outcome_b_id": outcome_ids[1],
        "outcome_b_name": names.get(outcome_ids[1]),
        "outcome_b_decimal": b["_price"],
        "outcome_b_quote_utc": b["_ts"].isoformat(),
        "decision_pair_skew_seconds": round(skew, 3),
        "decision_outcome_a_age_seconds": round(age_a, 3),
        "decision_outcome_b_age_seconds": round(age_b, 3),
        "canonical_t30_within_6m": max(age_a, age_b) <= CANONICAL_TOLERANCE_SECONDS,
        "replay_quote_fresh_180s": max(age_a, age_b) <= REPLAY_QUOTE_MAX_AGE_SECONDS,
        "history_path": history_path.as_posix(),
        "history_sha256": history_sha,
        "market_catalog_sha256": catalog_sha,
    }
    if close is not None:
        close_a, close_b = close
        row.update({
            "close_available": True,
            "close_outcome_a_decimal": close_a["_price"],
            "close_outcome_a_quote_utc": close_a["_ts"].isoformat(),
            "close_outcome_b_decimal": close_b["_price"],
            "close_outcome_b_quote_utc": close_b["_ts"].isoformat(),
            "close_pair_skew_seconds": round(abs((close_a["_ts"] - close_b["_ts"]).total_seconds()), 3),
            "close_after_decision": min(close_a["_ts"], close_b["_ts"]) > max(a["_ts"], b["_ts"]),
        })
    else:
        row["close_available"] = False
    return row


def build(root: Path, out: Path) -> dict[str, Any]:
    catalog, catalog_sha = _load_catalog(root)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    counts = Counter()

    for fixture_path in sorted(root.glob("????-??-??/*/fixture.normalized.json")):
        try:
            fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
            first_pitch = _parse_ts(fixture["startTime"])
        except Exception as exc:
            failures.append({"path": fixture_path.as_posix(), "reason": f"FIXTURE_INVALID:{type(exc).__name__}:{exc}"})
            continue
        target = first_pitch - timedelta(minutes=DECISION_MINUTES)
        for history_path in sorted(fixture_path.parent.glob("history_*.json")):
            if history_path.name.endswith(".meta.json"):
                continue
            try:
                raw, _ = _verify_raw(history_path)
                payload = json.loads(raw.decode("utf-8"))
                if str(payload.get("fixtureId") or "") != str(fixture.get("fixtureId") or ""):
                    raise RuntimeError("FIXTURE_ID_MISMATCH")
                history_sha = _sha(raw)
            except Exception as exc:
                failures.append({"path": history_path.as_posix(), "reason": f"HISTORY_INVALID:{type(exc).__name__}:{exc}"})
                continue

            for book, book_row in sorted((payload.get("bookmakers") or {}).items()):
                if not isinstance(book_row, dict):
                    continue
                for market_id, market in sorted((book_row.get("markets") or {}).items()):
                    info = catalog.get(str(market_id))
                    if not info:
                        counts["market_catalog_missing"] += 1
                        continue
                    outcomes_map = market.get("outcomes") or {}
                    if not isinstance(outcomes_map, dict) or len(outcomes_map) != 2:
                        counts["non_binary_or_ambiguous_market"] += 1
                        continue
                    outcome_ids = tuple(sorted(str(x) for x in outcomes_map.keys()))
                    outcome_rows = [outcomes_map[outcome_ids[0]], outcomes_map[outcome_ids[1]]]
                    for player_id in _player_ids(outcome_rows):
                        left = _timeline(outcome_rows[0], player_id)
                        right = _timeline(outcome_rows[1], player_id)
                        decision = _state_pair(
                            left, right, cutoff=target,
                            max_age_seconds=CANONICAL_TOLERANCE_SECONDS,
                        )
                        if decision is None:
                            counts["no_canonical_t30_pair"] += 1
                            continue
                        close = _state_pair(
                            left, right,
                            cutoff=first_pitch - timedelta(microseconds=1),
                            max_age_seconds=None,
                        )
                        if close is not None and min(close[0]["_ts"], close[1]["_ts"]) <= max(decision[0]["_ts"], decision[1]["_ts"]):
                            close = None
                        row = _pair_row(
                            fixture=fixture,
                            history_path=history_path,
                            history_sha=history_sha,
                            book=str(book),
                            market_id=str(market_id),
                            info=info,
                            outcome_ids=(outcome_ids[0], outcome_ids[1]),
                            player_id=player_id,
                            decision=decision,
                            close=close,
                            catalog_sha=catalog_sha,
                        )
                        rows.append(row)
                        counts["canonical_t30_pairs"] += 1
                        if row["replay_quote_fresh_180s"]:
                            counts["strict_replay_fresh_pairs"] += 1
                        if close is not None:
                            counts["paired_closes"] += 1

    out.mkdir(parents=True, exist_ok=True)
    with (out / "pit_pairs.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    summary = {
        "schema": "MLB_V8_ODDSPAPI_PIT_ARCHIVE_V1",
        "source": "ODDSPAPI_HISTORICAL",
        "decision_target_minutes": DECISION_MINUTES,
        "canonical_tolerance_seconds": CANONICAL_TOLERANCE_SECONDS,
        "strict_replay_quote_max_age_seconds": REPLAY_QUOTE_MAX_AGE_SECONDS,
        "pair_max_timestamp_skew_seconds": PAIR_MAX_SKEW_SECONDS,
        "market_catalog_sha256": catalog_sha,
        "counts": dict(counts),
        "rows": len(rows),
        "failures": failures,
        "promotion_eligible": False,
        "promotion_reason": "PIT_COLLECTION_ALONE_DOES_NOT_SATISFY_MODEL_REPLAY_OR_UNTOUCHED_FORWARD_HOLDOUT",
    }
    _write_json(out / "summary.json", summary)
    return summary


def self_test() -> int:
    cutoff = _parse_ts("2026-06-05T22:35:00Z")
    left = _timeline({"players": {"0": [
        {"createdAt": "2026-06-05T22:34:20Z", "price": 1.80, "active": True},
        {"createdAt": "2026-06-05T22:34:50Z", "price": 1.82, "active": True},
    ]}}, "0")
    right = _timeline({"players": {"0": [
        {"createdAt": "2026-06-05T22:34:28Z", "price": 2.05, "active": True},
        {"createdAt": "2026-06-05T22:34:55Z", "price": 2.02, "active": True},
    ]}}, "0")
    pair = _state_pair(left, right, cutoff=cutoff, max_age_seconds=CANONICAL_TOLERANCE_SECONDS)
    assert pair is not None
    assert pair[0]["_ts"] == _parse_ts("2026-06-05T22:34:50Z")
    assert pair[1]["_ts"] == _parse_ts("2026-06-05T22:34:55Z")

    deactivated = _timeline({"players": {"0": [
        {"createdAt": "2026-06-05T22:34:20Z", "price": 1.80, "active": True},
        {"createdAt": "2026-06-05T22:34:58Z", "price": 1.80, "active": False},
    ]}}, "0")
    assert _state_at(deactivated, cutoff) is None
    assert _state_pair(deactivated, right, cutoff=cutoff, max_age_seconds=CANONICAL_TOLERANCE_SECONDS) is None

    stale = _timeline({"players": {"0": [
        {"createdAt": "2026-06-05T22:20:00Z", "price": 1.80, "active": True},
    ]}}, "0")
    assert _state_pair(stale, right, cutoff=cutoff, max_age_seconds=CANONICAL_TOLERANCE_SECONDS) is None

    skewed = _timeline({"players": {"0": [
        {"createdAt": "2026-06-05T22:34:10Z", "price": 1.80, "active": True},
    ]}}, "0")
    assert _state_pair(skewed, right, cutoff=cutoff, max_age_seconds=CANONICAL_TOLERANCE_SECONDS) is None
    assert _player_ids([
        {"players": {"0": [], "44": []}},
        {"players": {"0": [], "44": [], "55": []}},
    ]) == ["0", "44"]
    print(json.dumps({
        "status": "SELF_TEST_OK",
        "latest_state_only": "PASS",
        "deactivation_guard": "PASS",
        "early_only_t30": "PASS",
        "paired_side_skew_30s": "PASS",
        "no_single_side_inference": "PASS",
        "player_identity_pairing": "PASS",
    }))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(build(args.root, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
