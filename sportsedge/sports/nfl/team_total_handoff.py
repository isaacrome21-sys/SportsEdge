"""Provenance-safe NFL team-total distribution handoff.

This module does not modify the frozen NFL run machine. It materializes the same
market-blind M2 score rows before sportsbook thresholds are applied, binds them
to the exact model/live-feature identities, and verifies their distribution hash
against a canonical NFL run-machine report before team-total diagnostics can be
priced.

Verification grants no promotion authority. Team totals remain evidence-blocked
until their own forward evidence and Truth Gate requirements are satisfied.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .m2 import derive_nfl_m2_score_distribution
from .run_machine import (
    DEFAULT_FEATURE_TTL_SECONDS,
    NFL_MACHINE_VERSION,
    NFLMachineReport,
    NFLRunMachineError,
    _aware,
    _distribution_hash,
    _load_bound_model,
    _validate_live_features,
)
from .team_totals import price_nfl_team_totals

HANDOFF_SCHEMA = "NFL_TEAM_TOTAL_DISTRIBUTION_HANDOFF_V1"
VERIFIED_STATUS = "VERIFIED_SAME_DISTRIBUTION"
AUTHORITY = "RESEARCH_DIAGNOSTIC_ONLY_NO_MODEL_P_NO_OFFICIAL_NO_PROMOTION"


class NFLTeamTotalHandoffError(ValueError):
    pass


def _report_dict(report: NFLMachineReport | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(report, NFLMachineReport):
        return report.to_dict()
    if isinstance(report, Mapping):
        return dict(report)
    raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_CANONICAL_REPORT_REQUIRED")


def _game_identity(game: Mapping[str, Any]) -> dict[str, str]:
    fields = ("game_id", "home_team", "away_team", "provider_home_team", "provider_away_team")
    out = {field: str(game.get(field) or "").strip() for field in fields}
    missing = [field for field, value in out.items() if not value]
    if missing:
        raise NFLTeamTotalHandoffError(
            "NFL_TEAM_TOTAL_HANDOFF_GAME_IDENTITY_MISSING:" + ",".join(missing)
        )
    return out


def build_team_total_distribution_handoff(
    *,
    model_artifact: Mapping[str, Any],
    expected_model_artifact_sha256: str,
    runtime_code_git_sha: str,
    live_features: Mapping[str, Any],
    now: datetime,
    feature_ttl_seconds: int = DEFAULT_FEATURE_TTL_SECONDS,
) -> dict[str, Any]:
    """Build a market-blind handoff before any team-total line is applied."""
    current = _aware(now, "NFL_TEAM_TOTAL_HANDOFF_NOW_INVALID")
    try:
        model, artifact_sha, code_sha, training_sha = _load_bound_model(
            model_artifact,
            expected_model_artifact_sha256=expected_model_artifact_sha256,
            runtime_code_git_sha=runtime_code_git_sha,
        )
        live_sha, live_asof, games = _validate_live_features(
            live_features,
            current=current,
            feature_ttl_seconds=feature_ttl_seconds,
        )
    except NFLRunMachineError as exc:
        raise NFLTeamTotalHandoffError(str(exc)) from exc

    rows = []
    for game in games:
        identity = _game_identity(game)
        try:
            distribution = tuple(derive_nfl_m2_score_distribution(model, dict(game)))
        except ValueError as exc:
            raise NFLTeamTotalHandoffError(str(exc)) from exc
        if not distribution:
            raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_DISTRIBUTION_EMPTY")
        score_rows = [dict(row) for row in distribution]
        rows.append({
            **identity,
            "game_start_ts": _aware(
                game.get("game_start_ts"),
                f"NFL_TEAM_TOTAL_HANDOFF_GAME_START_INVALID:{identity['game_id']}",
            ).isoformat(),
            "distribution_sha256": _distribution_hash(score_rows),
            "score_rows": score_rows,
        })

    if not rows:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_GAMES_EMPTY")

    return {
        "schema_version": HANDOFF_SCHEMA,
        "authority": AUTHORITY,
        "generated_at_utc": current.isoformat(),
        "model_artifact_sha256": artifact_sha,
        "model_code_git_sha": code_sha,
        "training_source_manifest_sha256": training_sha,
        "live_feature_source_manifest_sha256": live_sha,
        "live_feature_asof_ts": live_asof.isoformat(),
        "markets_applied": False,
        "sportsbook_consumed": False,
        "promotion_changed": False,
        "official_eligible": False,
        "games": sorted(rows, key=lambda row: row["game_id"]),
    }


def verify_team_total_distribution_handoff(
    handoff: Mapping[str, Any],
    canonical_report: NFLMachineReport | Mapping[str, Any],
) -> dict[str, Any]:
    """Prove the handoff reproduces the canonical run-machine distribution."""
    if not isinstance(handoff, Mapping) or handoff.get("schema_version") != HANDOFF_SCHEMA:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_SCHEMA_INVALID")
    if handoff.get("markets_applied") is not False or handoff.get("sportsbook_consumed") is not False:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_MARKET_BLINDNESS_REQUIRED")

    report = _report_dict(canonical_report)
    if report.get("machine_version") != NFL_MACHINE_VERSION:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_CANONICAL_MACHINE_VERSION_MISMATCH")

    identity_fields = (
        "model_artifact_sha256",
        "model_code_git_sha",
        "training_source_manifest_sha256",
        "live_feature_source_manifest_sha256",
        "live_feature_asof_ts",
    )
    for field in identity_fields:
        if str(handoff.get(field) or "") != str(report.get(field) or ""):
            raise NFLTeamTotalHandoffError(f"NFL_TEAM_TOTAL_HANDOFF_IDENTITY_MISMATCH:{field}")

    raw_results = report.get("results")
    if not isinstance(raw_results, (list, tuple)) or not raw_results:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_CANONICAL_RESULTS_EMPTY")

    canonical_by_game: dict[str, str] = {}
    for raw in raw_results:
        row = dict(raw) if isinstance(raw, Mapping) else dict(vars(raw))
        game_id = str(row.get("game_id") or "").strip()
        dist_sha = str(row.get("distribution_sha256") or "").strip()
        if not game_id or not dist_sha:
            raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_CANONICAL_DISTRIBUTION_IDENTITY_MISSING")
        existing = canonical_by_game.setdefault(game_id, dist_sha)
        if existing != dist_sha:
            raise NFLTeamTotalHandoffError(
                f"NFL_TEAM_TOTAL_CANONICAL_DISTRIBUTION_SPLIT:{game_id}"
            )

    games = handoff.get("games")
    if not isinstance(games, list) or not games:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_GAMES_EMPTY")

    handoff_ids = {str(game.get("game_id") or "").strip() for game in games if isinstance(game, Mapping)}
    if handoff_ids != set(canonical_by_game):
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_GAME_SET_MISMATCH")

    verified_games = []
    for game in games:
        if not isinstance(game, Mapping):
            raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_GAME_INVALID")
        identity = _game_identity(game)
        game_id = identity["game_id"]
        score_rows = game.get("score_rows")
        if not isinstance(score_rows, list) or not score_rows:
            raise NFLTeamTotalHandoffError(
                f"NFL_TEAM_TOTAL_HANDOFF_SCORE_ROWS_EMPTY:{game_id}"
            )
        computed = _distribution_hash([dict(row) for row in score_rows])
        declared = str(game.get("distribution_sha256") or "").strip()
        if computed != declared:
            raise NFLTeamTotalHandoffError(
                f"NFL_TEAM_TOTAL_HANDOFF_DISTRIBUTION_HASH_MISMATCH:{game_id}"
            )
        if declared != canonical_by_game[game_id]:
            raise NFLTeamTotalHandoffError(
                f"NFL_TEAM_TOTAL_HANDOFF_CANONICAL_HASH_MISMATCH:{game_id}"
            )
        verified_games.append({
            **dict(game),
            "verification_status": VERIFIED_STATUS,
        })

    return {
        **dict(handoff),
        "verification_status": VERIFIED_STATUS,
        "canonical_machine_version": NFL_MACHINE_VERSION,
        "ready_for_team_total_diagnostics": True,
        "promotion_changed": False,
        "official_eligible": False,
        "games": verified_games,
    }


def price_verified_team_total_diagnostics(
    verified_handoff: Mapping[str, Any],
    *,
    game_id: str,
    home_total_line: float,
    away_total_line: float,
) -> dict[str, Any]:
    """Apply team-total thresholds only after same-distribution verification."""
    if verified_handoff.get("verification_status") != VERIFIED_STATUS:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_NOT_VERIFIED")
    games = verified_handoff.get("games")
    if not isinstance(games, list):
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_GAMES_EMPTY")
    matches = [
        game for game in games
        if isinstance(game, Mapping) and str(game.get("game_id") or "") == str(game_id)
    ]
    if len(matches) != 1:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_GAME_LOOKUP_INVALID")
    game = matches[0]
    if game.get("verification_status") != VERIFIED_STATUS:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_GAME_NOT_VERIFIED")
    score_rows = game.get("score_rows")
    if not isinstance(score_rows, list) or not score_rows:
        raise NFLTeamTotalHandoffError("NFL_TEAM_TOTAL_HANDOFF_SCORE_ROWS_EMPTY")

    priced = price_nfl_team_totals(
        score_rows,
        home_total_line=home_total_line,
        away_total_line=away_total_line,
    )
    return {
        "schema_version": "NFL_TEAM_TOTAL_DIAGNOSTIC_V1",
        "authority": AUTHORITY,
        "game_id": str(game_id),
        "distribution_sha256": str(game["distribution_sha256"]),
        "verification_status": VERIFIED_STATUS,
        "home_total_line": float(home_total_line),
        "away_total_line": float(away_total_line),
        "probabilities": priced,
        "bet_status": "BLOCKED",
        "engine_status": "DIAGNOSTIC_PRICED_FROM_VERIFIED_CANONICAL_DISTRIBUTION",
        "reason": "TEAM_TOTAL_MARKET_SPECIFIC_PROMOTION_EVIDENCE_REQUIRED",
        "official_eligible": False,
        "promotion_changed": False,
    }


__all__ = [
    "AUTHORITY",
    "HANDOFF_SCHEMA",
    "NFLTeamTotalHandoffError",
    "VERIFIED_STATUS",
    "build_team_total_distribution_handoff",
    "price_verified_team_total_diagnostics",
    "verify_team_total_distribution_handoff",
]
