#!/usr/bin/env python3
"""Price-only market-maker lead/lag and stale-soft-book radar.

This is a zero-authority SportsEdge Layer B diagnostic. It consumes only
append-only sportsbook price observations and never emits Model_P, Truth Gate,
promotion, staking, OFFICIAL, or eligibility authority.

The implementation is intentionally provider-agnostic. It borrows the public
MIT-licensed design pattern of stateful previous->current quote comparison used
by SportsGameOdds/live-odds-tracker and the lag-analysis framing used by
AntonioKaram/kalshi-kit, while keeping SportsEdge's own schema, governance and
fail-closed rules.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

UTC = timezone.utc
DEFAULT_POLICY = "config/market_maker_radar_v1.json"


class RadarError(RuntimeError):
    """Fail-closed contract error."""


def _parse_ts(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise RadarError("MARKET_RADAR_TIMESTAMP_MISSING")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RadarError("MARKET_RADAR_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None:
        raise RadarError("MARKET_RADAR_TIMESTAMP_NAIVE")
    return parsed.astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def american_implied_probability(price: Any) -> float:
    """Raw break-even probability from American odds; vig is not removed."""
    odds = _number(price)
    if odds is None or odds == 0:
        raise RadarError("MARKET_RADAR_AMERICAN_PRICE_INVALID")
    if odds < 0:
        return (-odds) / ((-odds) + 100.0)
    return 100.0 / (odds + 100.0)


def load_policy(path: str | Path = DEFAULT_POLICY) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("policy_id") != "MARKET_MAKER_RADAR_V1":
        raise RadarError("MARKET_RADAR_POLICY_ID_MISMATCH")
    authority = payload.get("authority") or {}
    forbidden_true = (
        "model_p_authority",
        "predictive_model_input",
        "truth_gate_input",
        "promotion_authority",
        "eligibility_authority",
        "staking_authority",
        "official_authority",
    )
    if any(authority.get(key) is not False for key in forbidden_true):
        raise RadarError("MARKET_RADAR_AUTHORITY_INVALID")
    if payload.get("evidence_class") != "LAYER_B_HARD_MARKET_DIAGNOSTIC":
        raise RadarError("MARKET_RADAR_EVIDENCE_CLASS_INVALID")
    books = payload.get("books") or {}
    if not books.get("market_makers") or not books.get("soft_books"):
        raise RadarError("MARKET_RADAR_BOOK_ROLE_MISSING")
    return payload


def _effective_time(row: Mapping[str, Any]) -> tuple[datetime, str]:
    value = row.get("book_last_update")
    if value:
        try:
            return _parse_ts(value), "book_last_update"
        except RadarError:
            pass
    return _parse_ts(row.get("captured_at")), "captured_at"


def _point_key(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return round(number, 8)


def dedupe_archive_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Remove overlapping-window labels and exact archive replays.

    `window` is deliberately excluded from the identity because overlapping
    close/t0 labels can refer to one physical paid fetch.
    """
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        key = (
            row.get("capture_id"),
            row.get("sport_key"),
            row.get("event_id"),
            str(row.get("book") or "").lower(),
            str(row.get("market") or "").lower(),
            str(row.get("outcome") or ""),
            _point_key(row.get("point")),
            _number(row.get("price_american")),
            row.get("book_last_update"),
            row.get("captured_at"),
        )
        if key in seen:
            continue
        seen.add(key)
        row["book"] = str(row.get("book") or "").lower()
        row["market"] = str(row.get("market") or "").lower()
        out.append(row)
    return out


def _move_id(payload: Mapping[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _movement_axis(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any] | None:
    old_point = _number(old.get("point"))
    new_point = _number(new.get("point"))
    if old_point is not None and new_point is not None and not math.isclose(old_point, new_point):
        delta = new_point - old_point
        return {
            "kind": "line",
            "direction": 1 if delta > 0 else -1,
            "point_delta": round(delta, 8),
            "implied_probability_delta_pp": None,
        }
    try:
        old_p = american_implied_probability(old.get("price_american"))
        new_p = american_implied_probability(new.get("price_american"))
    except RadarError:
        return None
    delta_pp = (new_p - old_p) * 100.0
    if math.isclose(delta_pp, 0.0, abs_tol=1e-12):
        return None
    return {
        "kind": "price_probability",
        "direction": 1 if delta_pp > 0 else -1,
        "point_delta": None,
        "implied_probability_delta_pp": round(delta_pp, 8),
    }


def detect_movements(rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    allowed_markets = set(policy.get("markets") or [])
    allowed_books = set(policy["books"]["market_makers"]) | set(policy["books"]["soft_books"])
    for raw in rows:
        book = str(raw.get("book") or "").lower()
        market = str(raw.get("market") or "").lower()
        if book not in allowed_books or market not in allowed_markets:
            continue
        try:
            ts, source = _effective_time(raw)
        except RadarError:
            continue
        row = dict(raw)
        row["_effective_ts"] = ts
        row["_effective_time_source"] = source
        groups[
            (
                str(row.get("sport_key") or ""),
                str(row.get("event_id") or ""),
                market,
                str(row.get("outcome") or ""),
                book,
            )
        ].append(row)

    movements: list[dict[str, Any]] = []
    min_line = float(policy["alerts"]["minimum_spread_or_total_line_gap"])
    min_prob_pp = float(policy["alerts"]["minimum_price_implied_probability_move_pp"])

    for key, observations in groups.items():
        observations.sort(
            key=lambda row: (
                row["_effective_ts"],
                str(row.get("captured_at") or ""),
                str(row.get("capture_id") or ""),
            )
        )
        previous: dict[str, Any] | None = None
        for current in observations:
            if previous is None:
                previous = current
                continue
            same_state = (
                _point_key(previous.get("point")) == _point_key(current.get("point"))
                and _number(previous.get("price_american")) == _number(current.get("price_american"))
            )
            if same_state:
                previous = current
                continue
            axis = _movement_axis(previous, current)
            if axis is None:
                previous = current
                continue
            magnitude_ok = (
                abs(float(axis["point_delta"])) >= min_line
                if axis["kind"] == "line"
                else abs(float(axis["implied_probability_delta_pp"])) >= min_prob_pp
            )
            base = {
                "sport_key": key[0],
                "event_id": key[1],
                "market": key[2],
                "outcome": key[3],
                "book": key[4],
                "from_point": _point_key(previous.get("point")),
                "to_point": _point_key(current.get("point")),
                "from_price_american": _number(previous.get("price_american")),
                "to_price_american": _number(current.get("price_american")),
                "from_capture_id": previous.get("capture_id"),
                "capture_id": current.get("capture_id"),
                "effective_at": _iso(current["_effective_ts"]),
                "effective_time_source": current["_effective_time_source"],
                "commence_time": current.get("commence_time"),
                "threshold_eligible": bool(magnitude_ok),
                **axis,
            }
            base["move_id"] = _move_id(base)
            movements.append(base)
            previous = current
    movements.sort(key=lambda move: (move["effective_at"], move["move_id"]))
    return movements


def _movement_key(move: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(move.get("sport_key") or ""),
        str(move.get("event_id") or ""),
        str(move.get("market") or ""),
        str(move.get("outcome") or ""),
    )


def _compatible_move(leader: Mapping[str, Any], follower: Mapping[str, Any]) -> bool:
    return (
        leader.get("kind") == follower.get("kind")
        and leader.get("direction") == follower.get("direction")
        and bool(follower.get("threshold_eligible"))
    )


def build_lead_lag_signals(
    movements: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    market_makers = set(policy["books"]["market_makers"])
    soft_books = set(policy["books"]["soft_books"])
    window = float(policy["timing"]["lead_follow_window_seconds"])
    family_ids = policy["grading"].get("source_family_ids") or {}

    by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for move in movements:
        if move.get("threshold_eligible"):
            by_key[_movement_key(move)].append(dict(move))

    signals: list[dict[str, Any]] = []
    synchronous: list[dict[str, Any]] = []
    for key, key_moves in by_key.items():
        leaders = [m for m in key_moves if m["book"] in market_makers]
        followers = [m for m in key_moves if m["book"] in soft_books]
        for leader in leaders:
            leader_ts = _parse_ts(leader["effective_at"])
            for soft_book in sorted(soft_books):
                candidates = [
                    m for m in followers if m["book"] == soft_book and _compatible_move(leader, m)
                ]
                candidates.sort(key=lambda m: m["effective_at"])
                chosen: dict[str, Any] | None = None
                sync: dict[str, Any] | None = None
                for follower in candidates:
                    follower_ts = _parse_ts(follower["effective_at"])
                    lag = (follower_ts - leader_ts).total_seconds()
                    if lag < 0:
                        continue
                    same_capture = bool(leader.get("capture_id")) and (
                        leader.get("capture_id") == follower.get("capture_id")
                    )
                    distinct_source_times = (
                        leader.get("effective_time_source") == "book_last_update"
                        and follower.get("effective_time_source") == "book_last_update"
                        and lag != 0
                    )
                    if lag == 0 or (same_capture and not distinct_source_times):
                        sync = follower
                        break
                    if 0 < lag <= window:
                        chosen = follower
                        break
                    if lag > window:
                        break
                if chosen is not None:
                    lag_seconds = int(
                        (_parse_ts(chosen["effective_at"]) - leader_ts).total_seconds()
                    )
                    family_key = f"{leader['book']}_to_{chosen['book']}"
                    source_family_id = family_ids.get(family_key)
                    row = {
                        "signal_class": "MARKET_MAKER_LEAD",
                        "evidence_class": policy["evidence_class"],
                        "source_family_id": source_family_id,
                        "sport_key": key[0],
                        "event_id": key[1],
                        "market": key[2],
                        "outcome": key[3],
                        "leader_book": leader["book"],
                        "follower_book": chosen["book"],
                        "leader_move_id": leader["move_id"],
                        "follower_move_id": chosen["move_id"],
                        "leader_at": leader["effective_at"],
                        "follower_at": chosen["effective_at"],
                        "lag_seconds": lag_seconds,
                        "movement_kind": leader["kind"],
                        "direction": leader["direction"],
                        "model_p_authority": False,
                        "promotion_authority": False,
                        "staking_authority": False,
                        "official_authority": False,
                    }
                    row["signal_id"] = _move_id(row)
                    signals.append(row)
                elif sync is not None:
                    row = {
                        "classification": "SYNCHRONOUS_NOT_LEADER",
                        "sport_key": key[0],
                        "event_id": key[1],
                        "market": key[2],
                        "outcome": key[3],
                        "market_maker_book": leader["book"],
                        "soft_book": sync["book"],
                        "market_maker_move_id": leader["move_id"],
                        "soft_move_id": sync["move_id"],
                        "effective_at": leader["effective_at"],
                    }
                    row["pair_id"] = _move_id(row)
                    synchronous.append(row)
    signals.sort(key=lambda row: (row["leader_at"], row["signal_id"]))
    synchronous.sort(key=lambda row: (row["effective_at"], row["pair_id"]))
    return signals, synchronous


def _snapshot_groups(rows: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in rows:
        capture_id = str(raw.get("capture_id") or "")
        if not capture_id:
            continue
        groups[
            (
                capture_id,
                str(raw.get("event_id") or ""),
                str(raw.get("market") or "").lower(),
                str(raw.get("book") or "").lower(),
            )
        ].append(dict(raw))
    return groups


def _favorable_line_gap(market: str, outcome: str, pin_point: float, soft_point: float) -> float | None:
    if market == "spreads":
        return soft_point - pin_point
    if market == "totals":
        name = outcome.strip().lower()
        if name == "over":
            return pin_point - soft_point
        if name == "under":
            return soft_point - pin_point
    return None


def build_stale_soft_signals(
    rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    market_makers = list(policy["books"]["market_makers"])
    soft_books = list(policy["books"]["soft_books"])
    if "pinnacle" not in market_makers:
        return [], []
    groups = _snapshot_groups(rows)
    prob_threshold = float(policy["alerts"]["stale_offer_fair_probability_gap_pp"])
    line_threshold = float(policy["alerts"]["minimum_spread_or_total_line_gap"])

    stale_price: list[dict[str, Any]] = []
    line_gap: list[dict[str, Any]] = []

    capture_event_market = sorted({(c, e, m) for c, e, m, _ in groups})
    for capture_id, event_id, market in capture_event_market:
        pin_rows = groups.get((capture_id, event_id, market, "pinnacle"), [])
        if len(pin_rows) < 2:
            continue
        # Standard game markets here are two-sided. Refuse to invent a devig
        # if duplicate or malformed outcome rows make the side set ambiguous.
        by_outcome: dict[str, dict[str, Any]] = {}
        malformed = False
        for row in pin_rows:
            outcome = str(row.get("outcome") or "")
            if not outcome or outcome in by_outcome:
                malformed = True
                break
            by_outcome[outcome] = row
        if malformed or len(by_outcome) < 2:
            continue
        raw_probs: dict[str, float] = {}
        try:
            for outcome, row in by_outcome.items():
                raw_probs[outcome] = american_implied_probability(row.get("price_american"))
        except RadarError:
            continue
        denom = sum(raw_probs.values())
        if denom <= 0:
            continue
        fair_probs = {outcome: raw / denom for outcome, raw in raw_probs.items()}

        for soft_book in soft_books:
            soft_rows = groups.get((capture_id, event_id, market, soft_book), [])
            soft_by_outcome = {str(row.get("outcome") or ""): row for row in soft_rows}
            for outcome, pin_row in by_outcome.items():
                soft_row = soft_by_outcome.get(outcome)
                if soft_row is None:
                    continue
                pin_point = _number(pin_row.get("point"))
                soft_point = _number(soft_row.get("point"))
                same_point = (
                    pin_point is None and soft_point is None
                ) or (
                    pin_point is not None
                    and soft_point is not None
                    and math.isclose(pin_point, soft_point, abs_tol=1e-9)
                )
                if same_point:
                    try:
                        soft_break_even = american_implied_probability(soft_row.get("price_american"))
                    except RadarError:
                        continue
                    gap_pp = (fair_probs[outcome] - soft_break_even) * 100.0
                    if gap_pp >= prob_threshold:
                        record = {
                            "signal_class": "STALE_SOFT_PRICE",
                            "evidence_class": policy["evidence_class"],
                            "capture_id": capture_id,
                            "event_id": event_id,
                            "sport_key": str(pin_row.get("sport_key") or ""),
                            "market": market,
                            "outcome": outcome,
                            "market_maker_book": "pinnacle",
                            "soft_book": soft_book,
                            "point": _point_key(pin_point),
                            "pinnacle_fair_probability": round(fair_probs[outcome], 8),
                            "soft_break_even_probability": round(soft_break_even, 8),
                            "fair_probability_gap_pp": round(gap_pp, 8),
                            "pinnacle_price_american": _number(pin_row.get("price_american")),
                            "soft_price_american": _number(soft_row.get("price_american")),
                            "captured_at": soft_row.get("captured_at"),
                            "threshold_status": policy["alerts"]["threshold_status"],
                            "model_p_authority": False,
                            "promotion_authority": False,
                            "staking_authority": False,
                            "official_authority": False,
                        }
                        record["signal_id"] = _move_id(record)
                        stale_price.append(record)
                elif pin_point is not None and soft_point is not None:
                    favorable = _favorable_line_gap(market, outcome, pin_point, soft_point)
                    if favorable is not None and favorable >= line_threshold:
                        record = {
                            "signal_class": "LINE_ADVANTAGE_CANDIDATE",
                            "evidence_class": policy["evidence_class"],
                            "capture_id": capture_id,
                            "event_id": event_id,
                            "sport_key": str(pin_row.get("sport_key") or ""),
                            "market": market,
                            "outcome": outcome,
                            "market_maker_book": "pinnacle",
                            "soft_book": soft_book,
                            "pinnacle_point": _point_key(pin_point),
                            "soft_point": _point_key(soft_point),
                            "favorable_line_gap": round(favorable, 8),
                            "price_normalized": False,
                            "reason": "DIFFERENT_LINE_CANNOT_BE_CONVERTED_TO_EV_WITHOUT_A_MODEL",
                            "captured_at": soft_row.get("captured_at"),
                            "model_p_authority": False,
                            "promotion_authority": False,
                            "staking_authority": False,
                            "official_authority": False,
                        }
                        record["signal_id"] = _move_id(record)
                        line_gap.append(record)
    stale_price.sort(key=lambda row: (str(row.get("captured_at") or ""), row["signal_id"]))
    line_gap.sort(key=lambda row: (str(row.get("captured_at") or ""), row["signal_id"]))
    return stale_price, line_gap


def build_steam_clusters(
    movements: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]
) -> list[dict[str, Any]]:
    eligible = [dict(move) for move in movements if move.get("threshold_eligible")]
    window = float(policy["timing"]["steam_window_seconds"])
    min_books = int(policy["alerts"]["steam_min_books"])
    groups: dict[tuple[str, str, str, str, str, int], list[dict[str, Any]]] = defaultdict(list)
    for move in eligible:
        groups[
            (
                str(move.get("sport_key") or ""),
                str(move.get("event_id") or ""),
                str(move.get("market") or ""),
                str(move.get("outcome") or ""),
                str(move.get("kind") or ""),
                int(move.get("direction") or 0),
            )
        ].append(move)

    clusters: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for key, moves in groups.items():
        moves.sort(key=lambda move: move["effective_at"])
        for idx, first in enumerate(moves):
            start = _parse_ts(first["effective_at"])
            bucket = [first]
            for candidate in moves[idx + 1 :]:
                delta = (_parse_ts(candidate["effective_at"]) - start).total_seconds()
                if delta > window:
                    break
                bucket.append(candidate)
            books = sorted({move["book"] for move in bucket})
            if len(books) < min_books:
                continue
            end = max(_parse_ts(move["effective_at"]) for move in bucket)
            identity = (*key, tuple(books), _iso(start), _iso(end))
            if identity in seen:
                continue
            seen.add(identity)
            record = {
                "signal_class": "MULTI_BOOK_STEAM",
                "evidence_class": policy["evidence_class"],
                "sport_key": key[0],
                "event_id": key[1],
                "market": key[2],
                "outcome": key[3],
                "movement_kind": key[4],
                "direction": key[5],
                "books": books,
                "book_count": len(books),
                "window_start": _iso(start),
                "window_end": _iso(end),
                "duration_seconds": int((end - start).total_seconds()),
                "market_maker_included": any(
                    book in set(policy["books"]["market_makers"]) for book in books
                ),
                "interpretation": "SECONDARY_PRICE_ONLY_NOT_PROOF_OF_SHARP_ACTION",
                "model_p_authority": False,
                "promotion_authority": False,
            }
            record["signal_id"] = _move_id(record)
            clusters.append(record)
    clusters.sort(key=lambda row: (row["window_start"], row["signal_id"]))
    return clusters


def summarize_lead_lag(signals: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    by_family: dict[str, list[float]] = defaultdict(list)
    for signal in signals:
        family = str(signal.get("source_family_id") or "UNMAPPED")
        by_family[family].append(float(signal["lag_seconds"]))
    minimum_n = int(policy["grading"]["minimum_n_for_claim"])
    result: dict[str, Any] = {}
    for family, lags in sorted(by_family.items()):
        ordered = sorted(lags)
        p90_index = max(0, math.ceil(0.90 * len(ordered)) - 1)
        result[family] = {
            "n": len(lags),
            "mean_lag_seconds": round(statistics.fmean(lags), 3),
            "median_lag_seconds": round(statistics.median(lags), 3),
            "p90_lag_seconds": round(ordered[p90_index], 3),
            "validation_status": (
                policy["grading"]["status_before_minimum_n"]
                if len(lags) < minimum_n
                else "CLV_GRADING_REQUIRED_BEFORE_ANY_EDGE_CLAIM"
            ),
            "clv": None,
            "hit_rate": None,
            "flat_1u_roi": None,
        }
    return result


def analyze(rows: Sequence[Mapping[str, Any]], policy: Mapping[str, Any]) -> dict[str, Any]:
    deduped = dedupe_archive_rows(rows)
    market_makers = set(policy["books"]["market_makers"])
    soft_books = set(policy["books"]["soft_books"])
    counts: dict[str, int] = defaultdict(int)
    for row in deduped:
        counts[str(row.get("book") or "").lower()] += 1

    if not deduped:
        state = "BLOCKED_NO_ROWS"
    elif not any(counts.get(book, 0) for book in market_makers):
        state = "BLOCKED_NO_MARKET_MAKER_DATA"
    elif not any(counts.get(book, 0) for book in soft_books):
        state = "BLOCKED_NO_SOFT_BOOK_DATA"
    else:
        state = "ACTIVE"

    movements = detect_movements(deduped, policy)
    lead_lag, synchronous = build_lead_lag_signals(movements, policy)
    stale_price, line_gap = build_stale_soft_signals(deduped, policy)
    steam = build_steam_clusters(movements, policy)

    return {
        "policy_id": policy["policy_id"],
        "policy_version": policy["version"],
        "state": state,
        "evidence_class": policy["evidence_class"],
        "model_free": True,
        "model_p_authority": False,
        "truth_gate_input": False,
        "promotion_authority": False,
        "eligibility_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "rows_loaded": len(rows),
        "rows_after_observation_dedupe": len(deduped),
        "book_row_counts": dict(sorted(counts.items())),
        "provider_required_not_captured": list(policy["books"].get("provider_required") or []),
        "movement_count": len(movements),
        "lead_lag_signal_count": len(lead_lag),
        "synchronous_pair_count": len(synchronous),
        "stale_soft_price_count": len(stale_price),
        "line_advantage_candidate_count": len(line_gap),
        "steam_cluster_count": len(steam),
        "lead_lag_signals": lead_lag,
        "synchronous_moves": synchronous,
        "stale_soft_prices": stale_price,
        "line_advantage_candidates": line_gap,
        "steam_clusters": steam,
        "lead_lag_summary": summarize_lead_lag(lead_lag, policy),
        "public_split_role": "ANNOTATION_ONLY_NOT_SIGNAL",
        "rlm_role": "ANNOTATION_ONLY_REQUIRES_NEWS_ATTRIBUTION",
        "caveats": [
            "Observed bookmaker update timestamps are not proof of bettor identity or intent.",
            "Simultaneous moves are not assigned a leader.",
            "Different spread/total lines are not converted to EV without a genuine model.",
            "Research alert thresholds are not validated edge floors.",
            "CLV grading is required before any source-family performance claim.",
        ],
    }


def _candidate_files(root: Path, cutoff: datetime | None) -> list[Path]:
    files = sorted(root.rglob("*.ndjson"))
    if cutoff is None:
        return files
    kept: list[Path] = []
    for path in files:
        stem = path.stem
        try:
            date = datetime.strptime(stem, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            kept.append(path)
            continue
        if date + timedelta(days=1) >= cutoff:
            kept.append(path)
    return kept


def read_ndjson(paths: Sequence[Path], cutoff: datetime | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RadarError(f"MARKET_RADAR_NDJSON_INVALID:{path}:{lineno}") from exc
            if cutoff is not None:
                try:
                    captured = _parse_ts(row.get("captured_at"))
                except RadarError:
                    continue
                if captured < cutoff:
                    continue
            rows.append(row)
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--input", action="append", default=[])
    parser.add_argument("--input-root", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument("--since-hours", type=float, default=24.0)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    now = _parse_ts(args.now) if args.now else datetime.now(UTC)
    cutoff = None if args.since_hours < 0 else now - timedelta(hours=args.since_hours)

    paths = [Path(item) for item in args.input]
    if args.input_root:
        paths.extend(_candidate_files(Path(args.input_root), cutoff))
    # deterministic path de-duplication
    unique_paths = sorted({path.resolve() for path in paths})
    rows = read_ndjson(unique_paths, cutoff=cutoff)
    report = analyze(rows, policy)
    report["ran_at"] = _iso(now)
    report["cutoff"] = _iso(cutoff) if cutoff is not None else None
    report["input_files"] = [str(path) for path in unique_paths]

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
