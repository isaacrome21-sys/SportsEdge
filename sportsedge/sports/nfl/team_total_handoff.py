"""Provenance-bound NFL score-distribution handoff for team-total diagnostics.

This module does not change the frozen NFL M2 or canonical run-machine bytes.
It captures the single canonical market-blind score-distribution call while
run_nfl_machine executes, then binds those exact score rows to the report's
existing distribution hash and model/feature identities.

The handoff is evidence plumbing only. Team-total pricing remains diagnostic and
market-specific promotion/Truth Gate authority is unchanged.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
from threading import Lock
from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl import m2 as nfl_m2
from sportsedge.sports.nfl import run_machine as canonical
from sportsedge.sports.nfl.team_totals import price_nfl_team_totals

HANDOFF_SCHEMA = "NFL_TEAM_TOTAL_DISTRIBUTION_HANDOFF_V1"
CAPTURE_METHOD = "SINGLE_CANONICAL_DERIVATION_INTERCEPT"
_CAPTURE_LOCK = Lock()


class NFLTeamTotalHandoffError(ValueError):
    pass


def _canonical_hash(value: Any) -> str:
    try:
        raw = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_CANONICAL_JSON_INVALID") from exc
    return sha256(raw).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_REPORT_INVALID")


def _result_rows(report: Any) -> list[dict[str, Any]]:
    payload = _mapping(report)
    raw = payload.get("results")
    if not isinstance(raw, (list, tuple)):
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_REPORT_RESULTS_INVALID")
    rows: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping):
            rows.append(dict(item))
        elif is_dataclass(item):
            rows.append(asdict(item))
        else:
            raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_REPORT_RESULT_INVALID")
    return rows


def _score_rows(value: Sequence[Mapping[str, Any]]) -> list[dict[str, int]]:
    if not value:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_SCORE_ROWS_EMPTY")
    out: list[dict[str, int]] = []
    for raw in value:
        if not isinstance(raw, Mapping):
            raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_SCORE_ROW_INVALID")
        try:
            home = int(raw["home_score"])
            away = int(raw["away_score"])
            margin = int(raw["margin"])
            total = int(raw["total"])
        except (KeyError, TypeError, ValueError) as exc:
            raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_SCORE_ROW_INVALID") from exc
        if min(home, away, total) < 0:
            raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_SCORE_ROW_NEGATIVE")
        if margin != home - away:
            raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_MARGIN_CONSERVATION_FAILED")
        if total != home + away:
            raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_TOTAL_CONSERVATION_FAILED")
        out.append({
            "home_score": home,
            "away_score": away,
            "margin": margin,
            "total": total,
        })
    return out


def _report_identity(report: Any) -> dict[str, str]:
    payload = _mapping(report)
    required = (
        "machine_version",
        "model_artifact_sha256",
        "model_code_git_sha",
        "training_source_manifest_sha256",
        "live_feature_source_manifest_sha256",
        "live_feature_asof_ts",
    )
    out: dict[str, str] = {}
    for field in required:
        text = str(payload.get(field) or "").strip()
        if not text:
            raise NFLTeamTotalHandoffError(f"NFL_TEAM_TOTAL_HANDOFF_REPORT_IDENTITY_MISSING:{field}")
        out[field] = text
    return out


def _build_handoff(
    *,
    report: Any,
    game_id: str,
    score_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = _score_rows(score_rows)
    results = [row for row in _result_rows(report) if str(row.get("game_id") or "") == game_id]
    if not results:
        raise NFLTeamTotalHandoffError(f"NFL_TEAM_TOTAL_HANDOFF_GAME_NOT_IN_REPORT:{game_id}")
    reported_hashes = {str(row.get("distribution_sha256") or "") for row in results}
    if len(reported_hashes) != 1 or "" in reported_hashes:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_REPORT_DISTRIBUTION_IDENTITY_INVALID")

    distribution_sha = canonical._distribution_hash(rows)
    if reported_hashes != {distribution_sha}:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_DISTRIBUTION_HASH_MISMATCH")

    identity = _report_identity(report)
    payload: dict[str, Any] = {
        "schema_version": HANDOFF_SCHEMA,
        "capture_method": CAPTURE_METHOD,
        "game_id": game_id,
        "machine_version": identity["machine_version"],
        "model_artifact_sha256": identity["model_artifact_sha256"],
        "model_code_git_sha": identity["model_code_git_sha"],
        "training_source_manifest_sha256": identity["training_source_manifest_sha256"],
        "live_feature_source_manifest_sha256": identity["live_feature_source_manifest_sha256"],
        "live_feature_asof_ts": identity["live_feature_asof_ts"],
        "distribution_sha256": distribution_sha,
        "score_row_count": len(rows),
        "score_rows": rows,
        "path_conservation_verified": True,
        "market_blind_boundary": True,
        "distribution_recomputed_after_market": False,
        "authority": {
            "creates_model_p": False,
            "truth_gate": False,
            "official": False,
            "promotion": False,
            "staking": False,
            "changes_engine_state": False,
        },
    }
    payload["handoff_sha256"] = _canonical_hash(payload)
    return payload


def verify_team_total_distribution_handoff(
    handoff: Mapping[str, Any],
    *,
    report: Any,
) -> dict[str, Any]:
    """Verify a handoff against the exact canonical report before derivative use."""
    if not isinstance(handoff, Mapping):
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_INVALID")
    payload = dict(handoff)
    if payload.get("schema_version") != HANDOFF_SCHEMA:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_SCHEMA_INVALID")
    if payload.get("capture_method") != CAPTURE_METHOD:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_CAPTURE_METHOD_INVALID")
    if payload.get("market_blind_boundary") is not True:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_MARKET_BLIND_PROOF_REQUIRED")
    if payload.get("distribution_recomputed_after_market") is not False:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_POST_MARKET_RECOMPUTE_FORBIDDEN")
    authority = payload.get("authority")
    if not isinstance(authority, Mapping) or any(value is not False for value in authority.values()):
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_AUTHORITY_LEAK")

    rows_raw = payload.get("score_rows")
    if not isinstance(rows_raw, list):
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_SCORE_ROWS_INVALID")
    rows = _score_rows(rows_raw)
    if payload.get("score_row_count") != len(rows):
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_SCORE_ROW_COUNT_MISMATCH")
    distribution_sha = canonical._distribution_hash(rows)
    if payload.get("distribution_sha256") != distribution_sha:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_DISTRIBUTION_HASH_MISMATCH")

    supplied_handoff_sha = str(payload.pop("handoff_sha256", "")).strip()
    if supplied_handoff_sha != _canonical_hash(payload):
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_SHA256_MISMATCH")
    payload["handoff_sha256"] = supplied_handoff_sha

    game_id = str(payload.get("game_id") or "").strip()
    if not game_id:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_GAME_ID_REQUIRED")
    report_rows = [row for row in _result_rows(report) if str(row.get("game_id") or "") == game_id]
    if not report_rows:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_GAME_ID_MISMATCH")
    report_hashes = {str(row.get("distribution_sha256") or "") for row in report_rows}
    if report_hashes != {distribution_sha}:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_REPORT_DISTRIBUTION_HASH_MISMATCH")

    identity = _report_identity(report)
    for field, expected in identity.items():
        if str(payload.get(field) or "") != expected:
            raise NFLTeamTotalHandoffError(f"NFL_TEAM_TOTAL_HANDOFF_REPORT_IDENTITY_MISMATCH:{field}")

    return payload


def run_nfl_machine_with_team_total_handoff(**kwargs: Any):
    """Run the untouched canonical machine and capture its single score path.

    The module-global derive function is wrapped only for the duration of this
    serialized call. The wrapper delegates exactly once to the original frozen
    function for each game, records the returned rows, and returns the same rows
    unchanged to the canonical machine.
    """
    captured: dict[str, list[dict[str, Any]]] = {}

    with _CAPTURE_LOCK:
        original = canonical.derive_nfl_m2_score_distribution
        if original is not nfl_m2.derive_nfl_m2_score_distribution:
            raise NFLTeamTotalHandoffError(
                "NFL_TEAM_TOTAL_HANDOFF_CANONICAL_DERIVE_IDENTITY_CHANGED"
            )

        def capture(model: Any, game: Mapping[str, Any]):
            game_id = str(game.get("game_id") or "").strip()
            if not game_id:
                raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_GAME_ID_REQUIRED")
            if game_id in captured:
                raise NFLTeamTotalHandoffError(
                    f"NFL_TEAM_TOTAL_HANDOFF_DUPLICATE_DERIVATION:{game_id}"
                )
            rows = tuple(original(model, dict(game)))
            captured[game_id] = [dict(row) for row in rows]
            return rows

        canonical.derive_nfl_m2_score_distribution = capture
        try:
            report = canonical.run_nfl_machine(**kwargs)
        finally:
            canonical.derive_nfl_m2_score_distribution = original

    report_games = sorted({str(row.get("game_id") or "") for row in _result_rows(report)})
    captured_games = sorted(captured)
    if report_games != captured_games:
        raise NFLTeamTotalHandoffError(
            "NFL_TEAM_TOTAL_HANDOFF_CAPTURED_GAME_SET_MISMATCH"
        )

    handoffs = tuple(
        _build_handoff(report=report, game_id=game_id, score_rows=captured[game_id])
        for game_id in captured_games
    )
    return report, handoffs


def price_verified_team_totals(
    *,
    handoff: Mapping[str, Any],
    report: Any,
    home_total_line: float,
    away_total_line: float,
) -> dict[str, Any]:
    """Price diagnostic team totals only after exact handoff verification."""
    verified = verify_team_total_distribution_handoff(handoff, report=report)
    priced = price_nfl_team_totals(
        verified["score_rows"],
        home_total_line=home_total_line,
        away_total_line=away_total_line,
    )
    return {
        "schema_version": "NFL_TEAM_TOTAL_DIAGNOSTIC_V1",
        "game_id": verified["game_id"],
        "distribution_sha256": verified["distribution_sha256"],
        "handoff_sha256": verified["handoff_sha256"],
        "home_total_line": float(home_total_line),
        "away_total_line": float(away_total_line),
        "probabilities": priced,
        "engine_status": "PRICED_DIAGNOSTIC",
        "bet_status": "BLOCKED",
        "official_eligible": False,
        "reason": "TEAM_TOTAL_MARKET_SPECIFIC_PROMOTION_EVIDENCE_REQUIRED",
        "authority": {
            "creates_model_p": False,
            "truth_gate": False,
            "official": False,
            "promotion": False,
            "staking": False,
            "changes_engine_state": False,
        },
    }


__all__ = [
    "CAPTURE_METHOD",
    "HANDOFF_SCHEMA",
    "NFLTeamTotalHandoffError",
    "price_verified_team_totals",
    "run_nfl_machine_with_team_total_handoff",
    "verify_team_total_distribution_handoff",
]
