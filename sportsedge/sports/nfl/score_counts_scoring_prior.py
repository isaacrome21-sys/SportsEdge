"""Build a PIT-safe TD scoring-composition prior from NFL score-count rows.

The score-count feature builder already materializes completed historical team
rows with exact touchdown/field-goal/conversion/safety counts. This adapter
reuses those rows so TD prop composition does not require a second data source
or any sportsbook input.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence

from sports.common.ev_math import EVError, parse_utc
from sportsedge.nfl_scoring_composition_fit import (
    NflScoringCompositionFitError,
    ScoringCompositionPrior,
    fit_scoring_composition_prior,
)

SCHEMA = "SPORTSEDGE_NFL_SCORE_COUNTS_SCORING_COMPOSITION_PRIOR_V1"
FORBIDDEN_MARKET_KEYS = frozenset({
    "price_american",
    "odds",
    "market_no_vig_p",
    "edge_probability_points",
    "ev_per_dollar",
    "fair_american",
    "sportsbook_probability",
    "spread",
    "total_line",
    "moneyline",
})


class ScoreCountScoringPriorError(ValueError):
    pass


def _utc(value: Any, field: str) -> datetime:
    try:
        out = parse_utc(value).astimezone(timezone.utc)
    except (EVError, TypeError, ValueError) as exc:
        raise ScoreCountScoringPriorError(f"{field}:TIMESTAMP_REQUIRED") from exc
    return out


def _count(row: Mapping[str, Any], key: str) -> int:
    raw = row.get(key)
    if isinstance(raw, bool):
        raise ScoreCountScoringPriorError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED")
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ScoreCountScoringPriorError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED") from exc
    if value < 0 or value != int(value):
        raise ScoreCountScoringPriorError(f"{key}:NONNEGATIVE_INTEGER_REQUIRED")
    return int(value)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical(value)).hexdigest()


def _sha256(value: Any, field: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ScoreCountScoringPriorError(f"{field}:SHA256_REQUIRED")
    return text


def score_count_rows_to_scoring_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime | str,
) -> list[dict[str, Any]]:
    """Convert completed historical score-count rows into scoring-prior rows.

    The score-count row carries kickoff rather than a completion timestamp.
    We conservatively treat availability as kickoff + 8 hours. This never makes
    a historical row available earlier than the game itself and is immaterial
    for the intended 2018-2025 -> 2026 forward fit.
    """
    cutoff = _utc(as_of, "as_of")
    if not rows:
        raise ScoreCountScoringPriorError("TRAINING_ROWS_EMPTY")
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ScoreCountScoringPriorError(f"row[{idx}]:OBJECT_REQUIRED")
        if FORBIDDEN_MARKET_KEYS.intersection(row):
            raise ScoreCountScoringPriorError("MARKET_INPUT_FORBIDDEN")
        start = _utc(row.get("game_start_ts"), f"row[{idx}].game_start_ts")
        completed_at = start + timedelta(hours=8)
        if completed_at >= cutoff:
            raise ScoreCountScoringPriorError("PIT_FUTURE_OR_SAME_TIME_ROW")

        offense_td = _count(row, "offense_touchdowns")
        def_st_td = _count(row, "def_st_touchdowns")
        pat = _count(row, "pat_made")
        two = _count(row, "two_point_made")
        fg = _count(row, "made_field_goals")
        safety = _count(row, "safeties")
        touchdowns = offense_td + def_st_td
        score = 6 * touchdowns + pat + 2 * two + 3 * fg + 2 * safety
        out.append({
            "completed_at": completed_at.isoformat(),
            "score": score,
            "touchdowns": touchdowns,
            "extra_points_made": pat,
            "two_point_made": two,
            "field_goals_made": fg,
            "safeties": safety,
        })
    return out


def build_scoring_composition_prior_artifact(
    rows: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime | str,
    source_manifest_sha256: str,
    code_identity: str,
) -> dict[str, Any]:
    scoring_rows = score_count_rows_to_scoring_rows(rows, as_of=as_of)
    try:
        prior = fit_scoring_composition_prior(scoring_rows, as_of=as_of)
    except NflScoringCompositionFitError as exc:
        raise ScoreCountScoringPriorError(str(exc)) from exc
    source_sha = _sha256(source_manifest_sha256, "source_manifest_sha256")
    code = str(code_identity or "").strip()
    if not code:
        raise ScoreCountScoringPriorError("CODE_IDENTITY_REQUIRED")

    counts: dict[str, list[dict[str, Any]]] = {}
    for score, bucket in sorted(prior.counts_by_score.items()):
        rows_out = []
        for composition, count in sorted(bucket.items()):
            rows_out.append({
                "composition": list(composition),
                "count": int(count),
            })
        counts[str(int(score))] = rows_out

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "FITTED_HISTORICAL_PRIOR",
        "as_of": prior.as_of,
        "training_rows": prior.training_rows,
        "source_manifest_sha256": source_sha,
        "code_identity": code,
        "counts_by_score": counts,
        "market_data_used": False,
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "pricing": False,
            "promotion": False,
            "staking": False,
            "official": False,
        },
    }
    payload["artifact_sha256"] = _digest(payload)
    return payload


def scoring_composition_prior_from_artifact(
    artifact: Mapping[str, Any],
) -> ScoringCompositionPrior:
    if artifact.get("schema") != SCHEMA:
        raise ScoreCountScoringPriorError("SCHEMA_INVALID")
    expected = str(artifact.get("artifact_sha256") or "")
    check = dict(artifact)
    check.pop("artifact_sha256", None)
    if _digest(check) != expected:
        raise ScoreCountScoringPriorError("ARTIFACT_DIGEST_MISMATCH")
    training_rows = _count(artifact, "training_rows")
    if training_rows <= 0:
        raise ScoreCountScoringPriorError("TRAINING_ROWS_EMPTY")

    raw_counts = artifact.get("counts_by_score")
    if not isinstance(raw_counts, Mapping) or not raw_counts:
        raise ScoreCountScoringPriorError("COUNTS_BY_SCORE_REQUIRED")
    counts_by_score: dict[int, dict[tuple[int, int, int, int, int], int]] = {}
    observed = 0
    for raw_score, entries in raw_counts.items():
        try:
            score = int(raw_score)
        except (TypeError, ValueError) as exc:
            raise ScoreCountScoringPriorError("SCORE_INTEGER_REQUIRED") from exc
        if score < 0 or not isinstance(entries, Sequence) or isinstance(entries, (str, bytes, bytearray)):
            raise ScoreCountScoringPriorError("SCORE_BUCKET_INVALID")
        bucket: dict[tuple[int, int, int, int, int], int] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ScoreCountScoringPriorError("COMPOSITION_ENTRY_OBJECT_REQUIRED")
            raw_comp = entry.get("composition")
            if not isinstance(raw_comp, Sequence) or isinstance(raw_comp, (str, bytes, bytearray)) or len(raw_comp) != 5:
                raise ScoreCountScoringPriorError("COMPOSITION_VECTOR_REQUIRED")
            comp = tuple(int(v) for v in raw_comp)
            count = _count(entry, "count")
            if count <= 0:
                raise ScoreCountScoringPriorError("COMPOSITION_COUNT_POSITIVE_REQUIRED")
            if comp in bucket:
                raise ScoreCountScoringPriorError("COMPOSITION_DUPLICATE")
            bucket[comp] = count
            observed += count
        counts_by_score[score] = bucket
    if observed != training_rows:
        raise ScoreCountScoringPriorError("TRAINING_ROW_COUNT_MISMATCH")

    return ScoringCompositionPrior(
        as_of=str(artifact.get("as_of") or ""),
        training_rows=training_rows,
        counts_by_score=counts_by_score,
    )


__all__ = [
    "SCHEMA",
    "ScoreCountScoringPriorError",
    "build_scoring_composition_prior_artifact",
    "score_count_rows_to_scoring_rows",
    "scoring_composition_prior_from_artifact",
]
