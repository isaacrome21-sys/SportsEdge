"""Prospective shared NFL/CFB forward-capture primitives for Promotion Evidence V2.

This module does not create Model_P or select candidates. It accepts decisions that
already satisfy the frozen WS0 evidence-unit decision contract, enforces the
prospective decision/close windows, requires two-sided prices, and builds one
append-only same-threshold close record per decision. Legacy
NFL_FORWARD_SHADOW_EV_V1 rows are deliberately not adapted or reinterpreted here.

The committed JSON policy is the runtime authority. Constants exported below are
loaded from those exact bytes so a config change cannot silently shadow code.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from sports.common.ev_math import american_to_decimal, devig_power
from sports.common.evidence_unit import (
    EvidenceContractError,
    canonical_sha256,
    validate_close_observation,
    validate_decision_record,
)

POLICY_ID = "FOOTBALL_FORWARD_CAPTURE_V2"
POLICY_PATH = Path(__file__).resolve().parents[3] / "config/football_forward_capture_policy_v2.json"
CLOSE_SCHEMA_VERSION = "FOOTBALL_FORWARD_CLOSE_V2"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CODE_MARKETS = frozenset({"h2h", "spreads", "totals"})


class FootballForwardV2Error(ValueError):
    pass


def _policy_int(value: Any, code: str) -> int:
    if isinstance(value, bool):
        raise FootballForwardV2Error(code)
    try:
        out = int(value)
    except (TypeError, ValueError) as exc:
        raise FootballForwardV2Error(code) from exc
    return out


def load_forward_policy(path: str | Path = POLICY_PATH) -> dict[str, Any]:
    p = Path(path)
    try:
        raw = p.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_UNREADABLE") from exc
    if not isinstance(payload, Mapping):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_INVALID")
    out = dict(payload)
    if out.get("policy_id") != POLICY_ID:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_ID_MISMATCH")
    if out.get("status") != "PROSPECTIVE_UNACTIVATED":
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_ACTIVATION_REQUIRES_CODE_REVIEW")
    if out.get("promotion_authority") is not False or out.get("evidence_clock_authority") is not False:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_AUTHORITY_INVALID")
    if out.get("shared_evidence_contract") != "SPORTSEDGE_EVIDENCE_UNIT_V1":
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_SHARED_CONTRACT_MISMATCH")

    sports = out.get("sports")
    if not isinstance(sports, Mapping) or set(sports) != {"NFL", "CFB"}:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_SPORTS_INVALID")
    sport_keys: dict[str, str] = {}
    for sport in ("NFL", "CFB"):
        row = sports.get(sport)
        if not isinstance(row, Mapping):
            raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_SPORTS_INVALID")
        key = str(row.get("provider_sport_key") or "").strip()
        if not key:
            raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_SPORT_KEY_MISSING")
        sport_keys[sport] = key

    book = str(out.get("book") or "").strip().lower()
    if not book:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_BOOK_MISSING")
    markets_raw = out.get("markets")
    if not isinstance(markets_raw, list):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_MARKETS_INVALID")
    markets = frozenset(str(x).strip().lower() for x in markets_raw if str(x).strip())
    if markets != _CODE_MARKETS:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_MARKETS_UNSUPPORTED")

    decision_window = out.get("decision_window_minutes_before_start")
    close_window = out.get("close_window_minutes_before_start")
    if not isinstance(decision_window, Mapping) or not isinstance(close_window, Mapping):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_WINDOW_INVALID")
    decision_min = _policy_int(decision_window.get("min"), "FOOTBALL_FORWARD_V2_POLICY_WINDOW_INVALID")
    decision_max = _policy_int(decision_window.get("max"), "FOOTBALL_FORWARD_V2_POLICY_WINDOW_INVALID")
    close_min = _policy_int(close_window.get("min"), "FOOTBALL_FORWARD_V2_POLICY_WINDOW_INVALID")
    close_max = _policy_int(close_window.get("max"), "FOOTBALL_FORWARD_V2_POLICY_WINDOW_INVALID")
    if not (0 < decision_min <= decision_max and 0 < close_min <= close_max < decision_min):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_WINDOW_INVALID")

    close_definition_id = str(out.get("close_definition_id") or "").strip()
    if not close_definition_id:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_DEFINITION_MISSING")
    if out.get("devig_method") != "POWER_V1":
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_DEVIG_UNSUPPORTED")
    if out.get("provider_request_shape") != "SPORT_BULK_V1":
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_REQUEST_SHAPE_UNSUPPORTED")
    if out.get("same_threshold_required_for_spreads_totals") is not True:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_SAME_THRESHOLD_REQUIRED")

    persistence = out.get("persistence")
    if not isinstance(persistence, Mapping) or any(
        persistence.get(key) is not True
        for key in (
            "decisions_append_only",
            "closes_append_only",
            "one_close_per_decision",
            "missing_close_counts_in_coverage_denominator",
        )
    ):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_PERSISTENCE_POLICY_INVALID")
    if str(persistence.get("branch") or "") != "data":
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_PERSISTENCE_BRANCH_INVALID")

    candidate = out.get("candidate_contract")
    if not isinstance(candidate, Mapping) or any(
        candidate.get(key) is not expected
        for key, expected in (
            ("requires_ws0_decision_validation", True),
            ("requires_evidence_unit_id", True),
            ("requires_two_sided_decision_price", True),
            ("record_every_threshold_qualified_candidate", True),
            ("actual_bet_required", False),
        )
    ):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CANDIDATE_POLICY_INVALID")

    out["_sha256"] = sha256(raw).hexdigest()
    out["_sport_keys"] = sport_keys
    out["_book"] = book
    out["_markets"] = markets
    out["_decision_min"] = decision_min
    out["_decision_max"] = decision_max
    out["_close_min"] = close_min
    out["_close_max"] = close_max
    out["_close_definition_id"] = close_definition_id
    return out


_POLICY = load_forward_policy()
POLICY_SHA256 = str(_POLICY["_sha256"])
SUPPORTED_SPORTS = frozenset(_POLICY["_sport_keys"])
SPORT_KEYS = dict(_POLICY["_sport_keys"])
BOOK = str(_POLICY["_book"])
MAIN_MARKETS = frozenset(_POLICY["_markets"])
DECISION_MIN_LEAD = int(_POLICY["_decision_min"])
DECISION_MAX_LEAD = int(_POLICY["_decision_max"])
CLOSE_MIN_LEAD = int(_POLICY["_close_min"])
CLOSE_MAX_LEAD = int(_POLICY["_close_max"])
CLOSE_DEFINITION_ID = str(_POLICY["_close_definition_id"])
REQUEST_SHAPE = str(_POLICY["provider_request_shape"])


def _dt(value: Any, code: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise FootballForwardV2Error(code)
    try:
        out = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except ValueError as exc:
        raise FootballForwardV2Error(code) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise FootballForwardV2Error(code)
    return out.astimezone(timezone.utc)


def _num(value: Any, code: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise FootballForwardV2Error(code) from exc
    if not isfinite(out):
        raise FootballForwardV2Error(code)
    return out


def _shared_error(exc: EvidenceContractError) -> FootballForwardV2Error:
    return FootballForwardV2Error(str(exc))


def power_fair_pair(selected_american: float, opposite_american: float) -> tuple[float, float]:
    implied = [1.0 / american_to_decimal(selected_american), 1.0 / american_to_decimal(opposite_american)]
    fair = devig_power(implied)
    return float(fair[0]), float(fair[1])


def _validate_decision_line(row: Mapping[str, Any], market: str) -> float | None:
    if "line_at_decision" not in row:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_DECISION_LINE_FIELD_MISSING")
    raw = row.get("line_at_decision")
    if market == "h2h":
        if raw not in (None, ""):
            raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_H2H_LINE_MUST_BE_EMPTY")
        return None
    if raw in (None, ""):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_DECISION_LINE_REQUIRED")
    return _num(raw, "FOOTBALL_FORWARD_V2_DECISION_LINE_INVALID")


def validate_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        out = validate_decision_record(row)
    except EvidenceContractError as exc:
        raise _shared_error(exc) from exc

    for key in ("market", "side"):
        if not str(out.get(key) or "").strip():
            raise FootballForwardV2Error(f"FOOTBALL_FORWARD_V2_CANDIDATE_FIELD_MISSING:{key}")
    evidence_unit_id = str(out.get("evidence_unit_id") or "").strip().lower()
    if not _SHA256_RE.fullmatch(evidence_unit_id):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_EVIDENCE_UNIT_ID_INVALID")

    sport = str(out["sport"]).upper()
    if sport not in SUPPORTED_SPORTS:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_SPORT_UNSUPPORTED")
    market = str(out["market"]).lower()
    if market not in MAIN_MARKETS:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_MARKET_UNSUPPORTED")
    if str(out["book"]).lower() != BOOK:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_BOOK_MISMATCH")
    if out["qualifies_for_evidence"] is not True:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_NOT_EVIDENCE_QUALIFIED")

    try:
        selected_price = float(out["selected_price"])
        opposite_price = float(out["opposite_price"])
        power_fair_pair(selected_price, opposite_price)
    except (TypeError, ValueError) as exc:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_TWO_SIDED_PRICE_REQUIRED") from exc

    start = _dt(out["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID")
    model_at = _dt(out["model_p_computed_at"], "FOOTBALL_FORWARD_V2_MODEL_P_TS_INVALID")
    price_at = _dt(out["price_observed_at"], "FOOTBALL_FORWARD_V2_PRICE_TS_INVALID")
    decision_at = max(model_at, price_at)
    lead = (start - decision_at).total_seconds() / 60.0
    if not (DECISION_MIN_LEAD <= lead <= DECISION_MAX_LEAD):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_DECISION_OUTSIDE_WINDOW")

    out["evidence_unit_id"] = evidence_unit_id
    out["sport"] = sport
    out["market"] = market
    out["side"] = str(out["side"]).strip()
    out["book"] = BOOK
    out["selected_price"] = selected_price
    out["opposite_price"] = opposite_price
    out["line_at_decision"] = _validate_decision_line(out, market)
    return out


def _validate_same_threshold(
    candidate: Mapping[str, Any],
    *,
    selected_line: float | None,
    opposite_line: float | None,
) -> tuple[float | None, float | None]:
    market = str(candidate["market"])
    decision_line = candidate.get("line_at_decision")
    if market == "h2h":
        if selected_line is not None or opposite_line is not None:
            raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_H2H_CLOSE_LINE_MUST_BE_EMPTY")
        return None, None

    if selected_line is None or opposite_line is None:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_THRESHOLD_PAIR_REQUIRED")
    selected = _num(selected_line, "FOOTBALL_FORWARD_V2_CLOSE_LINE_INVALID")
    opposite = _num(opposite_line, "FOOTBALL_FORWARD_V2_CLOSE_LINE_INVALID")
    if decision_line is None or not isclose(selected, float(decision_line), abs_tol=1e-9):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_ORIGINAL_THRESHOLD_MISMATCH")
    expected_opposite = -selected if market == "spreads" else selected
    if not isclose(opposite, expected_opposite, abs_tol=1e-9):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_PAIR_LINE_MISMATCH")
    return selected, opposite


def _close_identity(
    *,
    decision_id: str,
    observed_at: str,
    selected_price: float,
    opposite_price: float,
    selected_line: float | None,
    opposite_line: float | None,
    snapshot_sha256: str,
) -> dict[str, Any]:
    return {
        "decision_id": decision_id,
        "observed_at": observed_at,
        "book": BOOK,
        "selected_price": float(selected_price),
        "opposite_price": float(opposite_price),
        "selected_line": selected_line,
        "opposite_line": opposite_line,
        "snapshot_sha256": str(snapshot_sha256).strip().lower(),
        "close_definition_id": CLOSE_DEFINITION_ID,
    }


def build_close_record(
    *,
    candidate: Mapping[str, Any],
    observed_at: str,
    selected_price: float,
    opposite_price: float,
    snapshot_sha256: str,
    selected_line: float | None = None,
    opposite_line: float | None = None,
) -> dict[str, Any]:
    row = validate_candidate(candidate)
    start = _dt(row["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID")
    observed = _dt(observed_at, "FOOTBALL_FORWARD_V2_CLOSE_TS_INVALID")
    lead = (start - observed).total_seconds() / 60.0
    if not (CLOSE_MIN_LEAD <= lead <= CLOSE_MAX_LEAD):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_OUTSIDE_WINDOW")
    decision_at = max(
        _dt(row["model_p_computed_at"], "FOOTBALL_FORWARD_V2_MODEL_P_TS_INVALID"),
        _dt(row["price_observed_at"], "FOOTBALL_FORWARD_V2_PRICE_TS_INVALID"),
    )
    if observed <= decision_at:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_NOT_AFTER_DECISION")

    close_selected_line, close_opposite_line = _validate_same_threshold(
        row, selected_line=selected_line, opposite_line=opposite_line
    )
    try:
        fair_selected, fair_opposite = power_fair_pair(selected_price, opposite_price)
    except (TypeError, ValueError) as exc:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_PRICE_PAIR_INVALID") from exc

    observed_iso = observed.isoformat()
    identity = _close_identity(
        decision_id=str(row["decision_id"]),
        observed_at=observed_iso,
        selected_price=float(selected_price),
        opposite_price=float(opposite_price),
        selected_line=close_selected_line,
        opposite_line=close_opposite_line,
        snapshot_sha256=snapshot_sha256,
    )
    base = {"close_id": canonical_sha256(identity), **identity}
    try:
        checked = validate_close_observation(base, decision=row)
    except EvidenceContractError as exc:
        raise _shared_error(exc) from exc

    return {
        **checked,
        "schema_version": CLOSE_SCHEMA_VERSION,
        "evidence_unit_id": row["evidence_unit_id"],
        "sport": row["sport"],
        "game_id": row["game_id"],
        "game_start_ts": start.isoformat(),
        "market": row["market"],
        "side": row["side"],
        "fair_selected_p": fair_selected,
        "fair_opposite_p": fair_opposite,
        "devig_method": "POWER_V1",
        "policy_sha256": POLICY_SHA256,
        "promotion_authority": False,
    }


def _validated_candidate_map(candidates: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw in candidates:
        row = validate_candidate(raw)
        decision_id = str(row["decision_id"])
        if decision_id in out:
            raise FootballForwardV2Error(f"FOOTBALL_FORWARD_V2_DUPLICATE_DECISION:{decision_id}")
        out[decision_id] = row
    return out


def _validate_close_record(raw: Mapping[str, Any], *, candidate: Mapping[str, Any]) -> dict[str, Any]:
    if str(raw.get("schema_version") or "") != CLOSE_SCHEMA_VERSION:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_SCHEMA_MISMATCH")
    if str(raw.get("close_definition_id") or "") != CLOSE_DEFINITION_ID:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_DEFINITION_MISMATCH")
    if str(raw.get("devig_method") or "") != "POWER_V1":
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_DEVIG_METHOD_MISMATCH")
    if str(raw.get("policy_sha256") or "") != POLICY_SHA256:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_POLICY_SHA_MISMATCH")
    for key in ("evidence_unit_id", "sport", "game_id", "market", "side"):
        if str(raw.get(key)) != str(candidate.get(key)):
            raise FootballForwardV2Error(f"FOOTBALL_FORWARD_V2_CLOSE_IDENTITY_MISMATCH:{key}")
    try:
        checked = validate_close_observation(raw, decision=candidate)
    except EvidenceContractError as exc:
        raise _shared_error(exc) from exc

    observed = _dt(checked["observed_at"], "FOOTBALL_FORWARD_V2_CLOSE_TS_INVALID")
    start = _dt(candidate["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID")
    lead = (start - observed).total_seconds() / 60.0
    if not (CLOSE_MIN_LEAD <= lead <= CLOSE_MAX_LEAD):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_OUTSIDE_WINDOW")
    decision_at = max(
        _dt(candidate["model_p_computed_at"], "FOOTBALL_FORWARD_V2_MODEL_P_TS_INVALID"),
        _dt(candidate["price_observed_at"], "FOOTBALL_FORWARD_V2_PRICE_TS_INVALID"),
    )
    if observed <= decision_at:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_NOT_AFTER_DECISION")

    selected_line, opposite_line = _validate_same_threshold(
        candidate,
        selected_line=raw.get("selected_line"),
        opposite_line=raw.get("opposite_line"),
    )
    fair_selected, fair_opposite = power_fair_pair(float(raw["selected_price"]), float(raw["opposite_price"]))
    if not isclose(float(raw.get("fair_selected_p", -1.0)), fair_selected, abs_tol=1e-12):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_FAIR_PRICE_MISMATCH")
    if not isclose(float(raw.get("fair_opposite_p", -1.0)), fair_opposite, abs_tol=1e-12):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_FAIR_PRICE_MISMATCH")

    identity = _close_identity(
        decision_id=str(candidate["decision_id"]),
        observed_at=observed.isoformat(),
        selected_price=float(raw["selected_price"]),
        opposite_price=float(raw["opposite_price"]),
        selected_line=selected_line,
        opposite_line=opposite_line,
        snapshot_sha256=str(raw["snapshot_sha256"]),
    )
    if str(raw.get("close_id") or "") != canonical_sha256(identity):
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_CLOSE_ID_MISMATCH")
    return dict(raw)


def _validated_close_map(
    closes: Iterable[Mapping[str, Any]],
    *,
    candidates: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw in closes:
        decision_id = str(raw.get("decision_id") or "")
        candidate = candidates.get(decision_id)
        if candidate is None:
            raise FootballForwardV2Error(f"FOOTBALL_FORWARD_V2_ORPHAN_CLOSE:{decision_id}")
        if decision_id in out:
            raise FootballForwardV2Error(f"FOOTBALL_FORWARD_V2_DUPLICATE_CLOSE:{decision_id}")
        out[decision_id] = _validate_close_record(raw, candidate=candidate)
    return out


def plan_due_bulk_sports(
    candidates: Iterable[Mapping[str, Any]],
    closes: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    current = now.astimezone(timezone.utc) if now.tzinfo and now.utcoffset() is not None else None
    if current is None:
        raise FootballForwardV2Error("FOOTBALL_FORWARD_V2_NOW_TIMEZONE_REQUIRED")
    candidate_map = _validated_candidate_map(candidates)
    close_map = _validated_close_map(closes, candidates=candidate_map)
    due: dict[str, list[str]] = {sport: [] for sport in SUPPORTED_SPORTS}
    expired: list[str] = []
    pending = 0
    for decision_id, row in candidate_map.items():
        if decision_id in close_map:
            continue
        pending += 1
        lead = (_dt(row["game_start_ts"], "FOOTBALL_FORWARD_V2_GAME_START_INVALID") - current).total_seconds() / 60.0
        if lead <= 0:
            expired.append(decision_id)
        elif CLOSE_MIN_LEAD <= lead <= CLOSE_MAX_LEAD:
            due[row["sport"]].append(decision_id)
    return {
        "now": current.isoformat(),
        "due_sports": sorted(sport for sport, ids in due.items() if ids),
        "due_decision_ids": {sport: sorted(ids) for sport, ids in due.items() if ids},
        "pending_unclosed": pending,
        "expired_unclosed": sorted(expired),
        "provider_request_count": sum(1 for ids in due.values() if ids),
        "request_shape": REQUEST_SHAPE,
        "policy_sha256": POLICY_SHA256,
    }


def coverage(candidates: Iterable[Mapping[str, Any]], closes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    candidate_map = _validated_candidate_map(candidates)
    close_map = _validated_close_map(closes, candidates=candidate_map)
    total = len(candidate_map)
    closed = len(close_map)
    return {
        "eligible_candidates": total,
        "captured_closes": closed,
        "missed_closes": total - closed,
        "coverage": None if total == 0 else closed / total,
        "policy_sha256": POLICY_SHA256,
    }


__all__ = [
    "BOOK", "CLOSE_DEFINITION_ID", "CLOSE_MAX_LEAD", "CLOSE_MIN_LEAD",
    "CLOSE_SCHEMA_VERSION", "DECISION_MAX_LEAD", "DECISION_MIN_LEAD",
    "FootballForwardV2Error", "MAIN_MARKETS", "POLICY_PATH", "POLICY_SHA256",
    "REQUEST_SHAPE", "SPORT_KEYS", "SUPPORTED_SPORTS", "build_close_record",
    "coverage", "load_forward_policy", "plan_due_bulk_sports", "power_fair_pair",
    "validate_candidate",
]
