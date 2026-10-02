"""Fail-closed CFB prospective decision/close + weather evidence admission.

Raw observations remain non-authoritative. This validator only says whether
future append-only bytes are suitable to bind into a later PIT training bundle.
It never creates Model_P, Truth-Gate, staking, promotion, or OFFICIAL authority.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

UTC = timezone.utc
CONTRACT = "SPORTSEDGE_CFB_FORWARD_MARKET_WEATHER_EVIDENCE_V1"
SPORT_KEY = "americanfootball_ncaaf"
DECISION_TARGET_MINUTES = 60.0
CLOSE_TARGET_MINUTES = 5.0
WEATHER_TARGET_MINUTES = 15.0
TARGET_DIRECTION = "EARLY_ONLY_AT_OR_BEFORE_TARGET"


class CFBForwardEvidenceError(RuntimeError):
    pass


def _time(value: Any, label: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise CFBForwardEvidenceError(f"{label}_MISSING")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBForwardEvidenceError(f"{label}_INVALID") from exc
    if out.tzinfo is None:
        raise CFBForwardEvidenceError(f"{label}_TIMEZONE_MISSING")
    return out.astimezone(UTC)


def _is_sha(value: Any) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _norm_team(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _pair(row: Mapping[str, Any]) -> tuple[str, str]:
    return tuple(sorted((_norm_team(row.get("home_team")), _norm_team(row.get("away_team")))))


def _verify_raw(root: Path, rel_value: Any, expected_value: Any) -> str | None:
    expected = str(expected_value or "").lower()
    if not _is_sha(expected):
        return "RAW_SHA256_INVALID"
    if not isinstance(rel_value, str) or not rel_value.strip():
        return "RAW_PATH_INVALID"
    rel = Path(rel_value)
    if rel.is_absolute() or ".." in rel.parts:
        return "RAW_PATH_INVALID"
    path = root / rel
    try:
        if not path.resolve().is_relative_to(root.resolve()):
            return "RAW_PATH_INVALID"
    except OSError:
        return "RAW_PATH_INVALID"
    if not path.is_file():
        return "RAW_FILE_MISSING"
    try:
        raw = path.read_bytes()
    except OSError:
        return "RAW_FILE_UNREADABLE"
    if sha256(raw).hexdigest() != expected:
        return "RAW_SHA256_MISMATCH"
    try:
        json.loads(raw)
    except Exception:
        return "RAW_JSON_INVALID"
    return None


def _nearest_early(rows: list[dict[str, Any]], target: float) -> dict[str, Any] | None:
    """Choose the closest observation at or before a frozen target, never after it.

    lead_minutes is measured backward from kickoff, so values greater than or equal
    to the target are on-time/early. Smaller values are post-target and ineligible.
    """
    eligible = [row for row in rows if float(row["lead_minutes"]) >= target]
    if not eligible:
        return None
    return min(
        eligible,
        key=lambda row: (
            float(row["lead_minutes"]) - target,
            str(row["captured_at"]),
            str(row.get("capture_id") or row.get("observation_id") or ""),
        ),
    )


def audit_cfb_forward_market_weather_evidence(
    market_rows: Iterable[Mapping[str, Any]],
    weather_rows: Iterable[Mapping[str, Any]],
    *,
    data_root: Path,
) -> dict[str, Any]:
    market_errors: list[str] = []
    weather_errors: list[str] = []
    raw_groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)

    for index, source in enumerate(market_rows):
        row = dict(source)
        label = f"MARKET_{index}"
        if row.get("sport_key") != SPORT_KEY:
            market_errors.append(f"{label}:SPORT_KEY_MISMATCH"); continue
        if row.get("evidence_class") != "NOT_EVIDENCE" or row.get("promotion_authority") is not False:
            market_errors.append(f"{label}:RAW_ARCHIVE_AUTHORITY_INVALID"); continue
        window = str(row.get("window") or "")
        if window not in {"decision", "close", "t0_prestart"}:
            market_errors.append(f"{label}:WINDOW_INVALID"); continue
        if row.get("raw_payload_preserved") is not True:
            market_errors.append(f"{label}:RAW_PAYLOAD_NOT_PRESERVED"); continue
        fetch_sha = str(row.get("fetch_sha256") or "").lower()
        if fetch_sha != str(row.get("fetch_payload_sha256") or "").lower():
            market_errors.append(f"{label}:FETCH_SHA_BINDING_MISMATCH"); continue
        raw_error = _verify_raw(data_root, row.get("fetch_payload_path"), fetch_sha)
        if raw_error:
            market_errors.append(f"{label}:{raw_error}"); continue
        try:
            captured = _time(row.get("captured_at"), "CAPTURED_AT")
            commence = _time(row.get("commence_time"), "COMMENCE_TIME")
        except CFBForwardEvidenceError as exc:
            market_errors.append(f"{label}:{exc}"); continue
        if captured >= commence:
            market_errors.append(f"{label}:NOT_PREKICKOFF"); continue
        if int(row.get("sides_in_market") or 0) < 2:
            market_errors.append(f"{label}:ONE_SIDED_MARKET"); continue
        identity = tuple(str(row.get(k) or "").strip().lower() for k in ("event_id", "book", "market"))
        capture_id = str(row.get("capture_id") or "").strip()
        if not all(identity) or not capture_id:
            market_errors.append(f"{label}:IDENTITY_MISSING"); continue
        row["_captured"] = captured
        row["_commence"] = commence
        raw_groups[(*identity, window, capture_id)].append(row)

    groups: list[dict[str, Any]] = []
    for key, rows in raw_groups.items():
        event_id, book, market, window, capture_id = key
        outcomes = {str(r.get("outcome") or "").strip() for r in rows if str(r.get("outcome") or "").strip()}
        captures = {r["_captured"] for r in rows}
        commences = {r["_commence"] for r in rows}
        raw_paths = {str(r.get("fetch_payload_path") or "") for r in rows}
        raw_shas = {str(r.get("fetch_sha256") or "").lower() for r in rows}
        pairs = {_pair(r) for r in rows}
        if len(outcomes) < 2:
            market_errors.append(f"GROUP:{event_id}:{book}:{market}:{window}:{capture_id}:OUTCOME_PAIR_MISSING"); continue
        if any(len(values) != 1 for values in (captures, commences, raw_paths, raw_shas, pairs)):
            market_errors.append(f"GROUP:{event_id}:{book}:{market}:{window}:{capture_id}:GROUP_BINDING_DRIFT"); continue
        captured, commence = next(iter(captures)), next(iter(commences))
        groups.append({
            "event_id": event_id, "book": book, "market": market,
            "window": window, "capture_id": capture_id,
            "captured_at": captured, "commence_time": commence,
            "lead_minutes": (commence - captured).total_seconds() / 60.0,
            "team_pair": next(iter(pairs)), "raw_path": next(iter(raw_paths)),
            "raw_sha256": next(iter(raw_shas)), "outcome_count": len(outcomes),
        })

    weather_valid: list[dict[str, Any]] = []
    for index, source in enumerate(weather_rows):
        row = dict(source); label = f"WEATHER_{index}"
        if row.get("schema_version") != "CFB_PIT_WEATHER_OBSERVATION_V1" or str(row.get("sport") or "").upper() != "CFB":
            weather_errors.append(f"{label}:SCHEMA_OR_SPORT_INVALID"); continue
        if row.get("promotion_authority") is not False or row.get("model_p_created") is not False:
            weather_errors.append(f"{label}:AUTHORITY_INVALID"); continue
        if str(row.get("status_state") or "").lower() != "pre":
            weather_errors.append(f"{label}:PRESTART_ATTESTATION_MISSING"); continue
        if not isinstance(row.get("weather"), dict) or not row.get("weather"):
            weather_errors.append(f"{label}:WEATHER_PAYLOAD_MISSING"); continue
        raw_error = _verify_raw(data_root, row.get("raw_relative_path"), row.get("raw_sha256"))
        if raw_error:
            weather_errors.append(f"{label}:{raw_error}"); continue
        try:
            captured = _time(row.get("captured_at_utc"), "WEATHER_CAPTURED_AT")
            commence = _time(row.get("commence_time"), "WEATHER_COMMENCE_TIME")
        except CFBForwardEvidenceError as exc:
            weather_errors.append(f"{label}:{exc}"); continue
        if captured >= commence or not all(_pair(row)):
            weather_errors.append(f"{label}:WEATHER_TIMING_OR_IDENTITY_INVALID"); continue
        weather_valid.append({
            "observation_id": str(row.get("observation_id") or ""),
            "captured_at": captured, "commence_time": commence,
            "lead_minutes": (commence - captured).total_seconds() / 60.0,
            "team_pair": _pair(row), "raw_path": str(row.get("raw_relative_path") or ""),
            "raw_sha256": str(row.get("raw_sha256") or "").lower(), "source": str(row.get("source") or ""),
        })

    by_identity: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        by_identity[(group["event_id"], group["book"], group["market"])].append(group)

    units: list[dict[str, Any]] = []
    for identity, candidate_groups in sorted(by_identity.items()):
        event_id, book, market = identity
        decision_candidates = [g for g in candidate_groups if g["window"] == "decision"]
        close_candidates = [g for g in candidate_groups if g["window"] in {"close", "t0_prestart"}]
        decision = _nearest_early(decision_candidates, DECISION_TARGET_MINUTES)
        close = _nearest_early(close_candidates, CLOSE_TARGET_MINUTES)
        if decision is None:
            if decision_candidates:
                market_errors.append(f"PAIR:{event_id}:{book}:{market}:DECISION_TARGET_LATE_ONLY")
            continue
        if close is None:
            if close_candidates:
                market_errors.append(f"PAIR:{event_id}:{book}:{market}:CLOSE_TARGET_LATE_ONLY")
            continue
        if decision["captured_at"] >= close["captured_at"] or decision["team_pair"] != close["team_pair"]:
            market_errors.append(f"PAIR:{event_id}:{book}:{market}:PAIR_BINDING_INVALID"); continue
        weather_candidates = [
            w for w in weather_valid
            if w["team_pair"] == close["team_pair"]
            and abs((w["commence_time"] - close["commence_time"]).total_seconds()) <= 900
        ]
        weather = _nearest_early(weather_candidates, WEATHER_TARGET_MINUTES)
        if weather is None:
            if weather_candidates:
                weather_errors.append(f"PAIR:{event_id}:{book}:{market}:WEATHER_TARGET_LATE_ONLY")
            continue
        units.append({
            "event_id": event_id, "book": book, "market": market,
            "team_pair": list(close["team_pair"]),
            "commence_time": close["commence_time"].isoformat().replace("+00:00", "Z"),
            "selection_policy": {
                "decision_target_minutes": DECISION_TARGET_MINUTES,
                "close_target_minutes": CLOSE_TARGET_MINUTES,
                "weather_target_minutes": WEATHER_TARGET_MINUTES,
                "target_direction": TARGET_DIRECTION,
                "tie_break": "closest_early_then_captured_at_then_identity_ascending",
            },
            "decision": {"capture_id": decision["capture_id"], "lead_minutes": decision["lead_minutes"], "raw_sha256": decision["raw_sha256"], "raw_path": decision["raw_path"]},
            "close": {"capture_id": close["capture_id"], "lead_minutes": close["lead_minutes"], "raw_sha256": close["raw_sha256"], "raw_path": close["raw_path"]},
            "weather": {"observation_id": weather["observation_id"], "lead_minutes": weather["lead_minutes"], "raw_sha256": weather["raw_sha256"], "raw_path": weather["raw_path"], "source": weather["source"]},
        })

    paired_exists = any(
        any(g["window"] == "decision" for g in gs) and any(g["window"] in {"close", "t0_prestart"} for g in gs)
        for gs in by_identity.values()
    )
    blockers: list[str] = []
    if not paired_exists: blockers.append("PAIRED_MARKET_EVIDENCE_MISSING")
    if not weather_valid: blockers.append("PREKICKOFF_WEATHER_EVIDENCE_MISSING")
    if not units and paired_exists and weather_valid: blockers.append("MARKET_WEATHER_IDENTITY_JOIN_MISSING")
    if market_errors: blockers.append("MARKET_EVIDENCE_BINDING_ERRORS")
    if weather_errors: blockers.append("WEATHER_EVIDENCE_BINDING_ERRORS")
    ready = bool(units)
    return {
        "contract": CONTRACT,
        "target_direction": TARGET_DIRECTION,
        "status": "READY_FOR_FUTURE_PIT_BUNDLE_BINDING" if ready else "BLOCKED_PROSPECTIVE_EVIDENCE_INCOMPLETE",
        "market_weather_evidence_ready": ready,
        "paired_market_identity_count": len(by_identity),
        "admitted_unit_count": len(units),
        "units": units,
        "market_errors": sorted(set(market_errors)),
        "weather_errors": sorted(set(weather_errors)),
        "blockers": sorted(set(blockers)),
        "retroactive_evidence_allowed": False,
        "training_bundle_ready": False,
        "truth_gate_ready": False,
        "model_p_created": False,
        "promotion_authority": False,
        "staking_authority": False,
        "official_authority": False,
    }
