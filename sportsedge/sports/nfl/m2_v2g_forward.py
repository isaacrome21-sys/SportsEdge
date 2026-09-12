"""Prospective-only prediction capture for the frozen NFL M2 V2G research artifact.

This module is deliberately separate from production M2 and bettor-facing RUN IT.
It materializes a future-game score distribution before kickoff and binds it to:
- the exact frozen V2G research artifact;
- exact immutable schedule snapshot bytes;
- the exact capture-code git SHA;
- a capture timestamp strictly before kickoff.

It cannot create production Model_P, promotion authority, eligibility, PASS, or
OFFICIAL status. Market prices are never accepted as inputs.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Mapping

from .m2_v2g_artifact import artifact_sha256, validate_v2g_research_artifact
from .m2_v2g_candidate import (
    NFLM2V2GCandidateModel,
    NFLV2GTeamState,
    derive_nfl_m2_v2g_score_distribution,
)

FORWARD_SCHEMA = "NFL_M2_V2G_PROSPECTIVE_PREDICTION_V1"
FREEZE_CORRECTION_SCHEMA = "SPORTSEDGE_NFL_V2G_ARTIFACT_FREEZE_CORRECTION_V1"


class NFLV2GForwardError(ValueError):
    pass


def _require(ok: bool, code: str) -> None:
    if not ok:
        raise NFLV2GForwardError(code)


def _hex(value: Any, length: int, field: str) -> str:
    text = str(value or "").strip().lower()
    _require(len(text) == length and all(ch in "0123456789abcdef" for ch in text), f"NFL_V2G_FORWARD_HASH_INVALID:{field}")
    return text


def _ts(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise NFLV2GForwardError(f"NFL_V2G_FORWARD_TIMESTAMP_INVALID:{field}") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, f"NFL_V2G_FORWARD_TIMESTAMP_TZ_REQUIRED:{field}")
    return parsed.astimezone(timezone.utc)


def canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(dict(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def prediction_sha256(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("prediction_sha256", None)
    return sha256(canonical_bytes(payload)).hexdigest()


def _load_model(artifact: Mapping[str, Any]) -> NFLM2V2GCandidateModel:
    model = artifact.get("model")
    _require(isinstance(model, Mapping), "NFL_V2G_FORWARD_MODEL_PAYLOAD_REQUIRED")
    raw_state = model.get("team_state")
    _require(isinstance(raw_state, Mapping) and bool(raw_state), "NFL_V2G_FORWARD_TEAM_STATE_REQUIRED")
    state: dict[str, NFLV2GTeamState] = {}
    for team, raw in sorted(raw_state.items()):
        _require(isinstance(raw, Mapping), "NFL_V2G_FORWARD_TEAM_STATE_INVALID")
        state[str(team)] = NFLV2GTeamState(
            games=int(raw["games"]),
            drives=int(raw["drives"]),
            touchdowns=int(raw["touchdowns"]),
            field_goals=int(raw["field_goals"]),
            drives_faced=int(raw["drives_faced"]),
            touchdowns_allowed=int(raw["touchdowns_allowed"]),
            field_goals_allowed=int(raw["field_goals_allowed"]),
        )
    return NFLM2V2GCandidateModel(
        model_id=str(model["model_id"]),
        distribution_contract=str(model["distribution_contract"]),
        event_contract=str(model["event_contract"]),
        train_seasons=tuple(int(x) for x in model["train_seasons"]),
        league_drives_per_team_game=float(model["league_drives_per_team_game"]),
        league_td_rate=float(model["league_td_rate"]),
        league_fg_rate=float(model["league_fg_rate"]),
        team_state=state,
        prior_drives=float(model["prior_drives"]),
        max_touchdowns=int(model["max_touchdowns"]),
        max_field_goals=int(model["max_field_goals"]),
    )


def validate_freeze_correction(correction: Mapping[str, Any]) -> dict[str, str]:
    _require(correction.get("schema_version") == FREEZE_CORRECTION_SCHEMA, "NFL_V2G_FORWARD_FREEZE_SCHEMA_INVALID")
    _require(correction.get("status") == "FROZEN_RESEARCH_ARTIFACT_FOR_PROSPECTIVE_CAPTURE", "NFL_V2G_FORWARD_FREEZE_STATUS_INVALID")
    bound = correction.get("source_bound_research_artifact")
    _require(isinstance(bound, Mapping), "NFL_V2G_FORWARD_FROZEN_ARTIFACT_REQUIRED")
    _require(correction.get("artifact_freeze_may_create_model_p") is False, "NFL_V2G_FORWARD_MODEL_P_AUTHORITY_FORBIDDEN")
    _require(correction.get("promotion_authority") is False, "NFL_V2G_FORWARD_PROMOTION_AUTHORITY_FORBIDDEN")
    return {
        "candidate_id": str(correction.get("candidate_id") or ""),
        "implementation_commit_sha": _hex(correction.get("implementation_commit_sha"), 40, "implementation_commit_sha"),
        "candidate_source_git_blob_sha1": _hex(correction.get("candidate_source_git_blob_sha1"), 40, "candidate_source_git_blob_sha1"),
        "preregistration_commit_sha": _hex(correction.get("preregistration_commit_sha"), 40, "preregistration_commit_sha"),
        "artifact_sha256": _hex(bound.get("artifact_sha256"), 64, "artifact_sha256"),
        "preregistration_timestamp_utc": _ts(correction.get("preregistration_timestamp_utc"), "preregistration_timestamp_utc").isoformat(),
    }


def build_prospective_prediction(
    *,
    artifact: Mapping[str, Any],
    implementation_freeze: Mapping[str, Any],
    freeze_correction: Mapping[str, Any],
    schedule_snapshot_sha256: str,
    capture_code_git_sha: str,
    captured_at_utc: str,
    game_id: str,
    season: int,
    week: int,
    kickoff_utc: str,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    frozen = validate_freeze_correction(freeze_correction)
    actual_artifact_sha = validate_v2g_research_artifact(artifact, implementation_freeze=implementation_freeze)
    _require(actual_artifact_sha == frozen["artifact_sha256"], "NFL_V2G_FORWARD_ARTIFACT_SHA_MISMATCH")
    _require(str(artifact.get("candidate_id") or "") == frozen["candidate_id"], "NFL_V2G_FORWARD_CANDIDATE_ID_MISMATCH")
    for field in ("implementation_commit_sha", "candidate_source_git_blob_sha1", "preregistration_commit_sha"):
        _require(str(artifact.get(field) or "").lower() == frozen[field], f"NFL_V2G_FORWARD_ARTIFACT_BINDING_MISMATCH:{field}")

    captured = _ts(captured_at_utc, "captured_at_utc")
    kickoff = _ts(kickoff_utc, "kickoff_utc")
    prereg = _ts(frozen["preregistration_timestamp_utc"], "preregistration_timestamp_utc")
    _require(captured > prereg, "NFL_V2G_FORWARD_CAPTURE_BEFORE_PREREGISTRATION")
    _require(captured < kickoff, "NFL_V2G_FORWARD_CAPTURE_NOT_PREGAME")
    _require(bool(str(game_id).strip()), "NFL_V2G_FORWARD_GAME_ID_REQUIRED")
    _require(int(season) >= 2026 and int(week) >= 1, "NFL_V2G_FORWARD_GAME_SCOPE_INVALID")
    home = str(home_team or "").strip()
    away = str(away_team or "").strip()
    _require(home and away and home != away, "NFL_V2G_FORWARD_TEAM_IDENTITY_INVALID")

    schedule_sha = _hex(schedule_snapshot_sha256, 64, "schedule_snapshot_sha256")
    code_sha = _hex(capture_code_git_sha, 40, "capture_code_git_sha")
    model = _load_model(artifact)
    distribution = derive_nfl_m2_v2g_score_distribution(model, {"home_team": home, "away_team": away})

    home_win = sum(float(x["weight"]) for x in distribution if int(x["margin"]) > 0)
    tie = sum(float(x["weight"]) for x in distribution if int(x["margin"]) == 0)
    away_win = sum(float(x["weight"]) for x in distribution if int(x["margin"]) < 0)
    expected_home = sum(float(x["home_score"]) * float(x["weight"]) for x in distribution)
    expected_away = sum(float(x["away_score"]) * float(x["weight"]) for x in distribution)
    for number in (home_win, tie, away_win, expected_home, expected_away):
        _require(isfinite(number), "NFL_V2G_FORWARD_SUMMARY_NONFINITE")
    _require(abs(home_win + tie + away_win - 1.0) <= 1e-10, "NFL_V2G_FORWARD_OUTCOME_MASS_INVALID")

    record: dict[str, Any] = {
        "schema_version": FORWARD_SCHEMA,
        "status": "PROSPECTIVE_RESEARCH_PREDICTION_CAPTURED",
        "candidate_id": frozen["candidate_id"],
        "artifact_sha256": actual_artifact_sha,
        "implementation_commit_sha": frozen["implementation_commit_sha"],
        "candidate_source_git_blob_sha1": frozen["candidate_source_git_blob_sha1"],
        "preregistration_commit_sha": frozen["preregistration_commit_sha"],
        "capture_code_git_sha": code_sha,
        "schedule_snapshot_sha256": schedule_sha,
        "game_id": str(game_id).strip(),
        "season": int(season),
        "week": int(week),
        "kickoff_utc": kickoff.isoformat(),
        "captured_at_utc": captured.isoformat(),
        "home_team": home,
        "away_team": away,
        "summary": {
            "home_win_probability": home_win,
            "tie_probability": tie,
            "away_win_probability": away_win,
            "expected_home_score": expected_home,
            "expected_away_score": expected_away,
        },
        "score_distribution": [dict(x) for x in distribution],
        "historical_data_role": "REUSED_RESEARCH_HISTORY_NOT_FINAL_HOLDOUT",
        "market_prices_consumed": False,
        "promotion_authority": False,
        "may_create_model_p": False,
        "market_eligibility_changed": False,
        "truth_gate_pass_granted": False,
        "official_status_granted": False,
    }
    record["prediction_sha256"] = prediction_sha256(record)
    return record


def validate_prospective_prediction(record: Mapping[str, Any]) -> str:
    _require(record.get("schema_version") == FORWARD_SCHEMA, "NFL_V2G_FORWARD_SCHEMA_INVALID")
    _require(record.get("status") == "PROSPECTIVE_RESEARCH_PREDICTION_CAPTURED", "NFL_V2G_FORWARD_STATUS_INVALID")
    _require(record.get("market_prices_consumed") is False, "NFL_V2G_FORWARD_MARKET_INPUT_FORBIDDEN")
    _require(record.get("promotion_authority") is False, "NFL_V2G_FORWARD_PROMOTION_FORBIDDEN")
    _require(record.get("may_create_model_p") is False, "NFL_V2G_FORWARD_MODEL_P_FORBIDDEN")
    _require(record.get("market_eligibility_changed") is False, "NFL_V2G_FORWARD_ELIGIBILITY_FORBIDDEN")
    _require(record.get("truth_gate_pass_granted") is False, "NFL_V2G_FORWARD_TRUTH_GATE_FORBIDDEN")
    _require(record.get("official_status_granted") is False, "NFL_V2G_FORWARD_OFFICIAL_FORBIDDEN")
    captured = _ts(record.get("captured_at_utc"), "captured_at_utc")
    kickoff = _ts(record.get("kickoff_utc"), "kickoff_utc")
    _require(captured < kickoff, "NFL_V2G_FORWARD_CAPTURE_NOT_PREGAME")
    expected = prediction_sha256(record)
    _require(str(record.get("prediction_sha256") or "").lower() == expected, "NFL_V2G_FORWARD_PREDICTION_SHA_MISMATCH")
    return expected
