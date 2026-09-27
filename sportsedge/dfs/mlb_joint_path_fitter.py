from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import re
from typing import Iterable, Mapping, Sequence

from .mlb_joint_paths import BaserunningProfile, HookHazardSurface, PlateAppearanceProfile


MLB_JOINT_PATH_FIT_VERSION = "MLB_DFS_JOINT_PATH_FIT_V1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_HOOK_ROLES = frozenset({"STARTER", "BULLPEN"})
_BASERUN_KINDS = (
    "SINGLE_SECOND_SCORES",
    "SINGLE_FIRST_TO_THIRD",
    "DOUBLE_FIRST_SCORES",
)


class MlbJointPathFitError(ValueError):
    """Raised when strictly-prior input evidence is insufficient or unsafe."""


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise MlbJointPathFitError("DFS_MLB_FIT_TIMESTAMP_MUST_BE_AWARE")
    return value.astimezone(timezone.utc)


def _sha(value: str) -> str:
    text = str(value).strip().lower()
    if not _SHA256_RE.fullmatch(text):
        raise MlbJointPathFitError("DFS_MLB_FIT_SOURCE_SHA256_INVALID")
    return text


def _canonical_hash(payload: object) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(text.encode("utf-8")).hexdigest()


def _serialize_row(row: object) -> dict[str, object]:
    payload = asdict(row)
    for key, value in list(payload.items()):
        if isinstance(value, datetime):
            payload[key] = _utc(value).isoformat()
    return {str(key): payload[key] for key in sorted(payload)}


@dataclass(frozen=True)
class MlbJointPathFitPolicy:
    policy_id: str
    status: str
    cutoff_at: datetime
    min_pa: int
    min_hook_cell_trials: int
    min_baserunning_opportunities: int
    pitch_count_upper_bounds: tuple[int, ...]
    runs_allowed_upper_bounds: tuple[int, ...]

    def validate(self) -> None:
        if self.status != "FROZEN":
            raise MlbJointPathFitError("DFS_MLB_FIT_POLICY_NOT_FROZEN")
        if not self.policy_id.strip():
            raise MlbJointPathFitError("DFS_MLB_FIT_POLICY_ID_REQUIRED")
        _utc(self.cutoff_at)
        if self.min_pa < 1:
            raise MlbJointPathFitError("DFS_MLB_FIT_MIN_PA_INVALID")
        if self.min_hook_cell_trials < 1:
            raise MlbJointPathFitError("DFS_MLB_FIT_MIN_HOOK_CELL_TRIALS_INVALID")
        if self.min_baserunning_opportunities < 1:
            raise MlbJointPathFitError("DFS_MLB_FIT_MIN_BASERUN_OPPORTUNITIES_INVALID")
        if not self.pitch_count_upper_bounds or not self.runs_allowed_upper_bounds:
            raise MlbJointPathFitError("DFS_MLB_FIT_HOOK_BINS_EMPTY")
        if tuple(sorted(self.pitch_count_upper_bounds)) != self.pitch_count_upper_bounds:
            raise MlbJointPathFitError("DFS_MLB_FIT_PITCH_BINS_UNSORTED")
        if tuple(sorted(self.runs_allowed_upper_bounds)) != self.runs_allowed_upper_bounds:
            raise MlbJointPathFitError("DFS_MLB_FIT_RUN_BINS_UNSORTED")
        if self.pitch_count_upper_bounds[-1] < 200 or self.runs_allowed_upper_bounds[-1] < 20:
            raise MlbJointPathFitError("DFS_MLB_FIT_HOOK_BINS_INCOMPLETE_SUPPORT")

    def digest(self) -> str:
        self.validate()
        return _canonical_hash(
            {
                "fit_version": MLB_JOINT_PATH_FIT_VERSION,
                "policy_id": self.policy_id,
                "status": self.status,
                "cutoff_at": _utc(self.cutoff_at).isoformat(),
                "min_pa": self.min_pa,
                "min_hook_cell_trials": self.min_hook_cell_trials,
                "min_baserunning_opportunities": self.min_baserunning_opportunities,
                "pitch_count_upper_bounds": self.pitch_count_upper_bounds,
                "runs_allowed_upper_bounds": self.runs_allowed_upper_bounds,
            }
        )


@dataclass(frozen=True)
class HistoricalPlateAppearance:
    occurred_at: datetime
    batter_id: str
    pitcher_role: str
    outcome: str
    pitch_count: int
    source_sha256: str

    def validate(self) -> None:
        _utc(self.occurred_at)
        if not self.batter_id.strip():
            raise MlbJointPathFitError("DFS_MLB_FIT_BATTER_ID_REQUIRED")
        if self.pitcher_role not in _HOOK_ROLES:
            raise MlbJointPathFitError("DFS_MLB_FIT_PITCHER_ROLE_INVALID")
        if not self.outcome.strip():
            raise MlbJointPathFitError("DFS_MLB_FIT_PA_OUTCOME_REQUIRED")
        if isinstance(self.pitch_count, bool) or int(self.pitch_count) < 1:
            raise MlbJointPathFitError("DFS_MLB_FIT_PA_PITCH_COUNT_INVALID")
        _sha(self.source_sha256)


@dataclass(frozen=True)
class HistoricalHookOpportunity:
    occurred_at: datetime
    cumulative_pitch_count: int
    cumulative_runs_allowed: int
    removed_before_next_batter: bool
    source_sha256: str

    def validate(self) -> None:
        _utc(self.occurred_at)
        if isinstance(self.cumulative_pitch_count, bool) or int(self.cumulative_pitch_count) < 0:
            raise MlbJointPathFitError("DFS_MLB_FIT_HOOK_PITCH_COUNT_INVALID")
        if isinstance(self.cumulative_runs_allowed, bool) or int(self.cumulative_runs_allowed) < 0:
            raise MlbJointPathFitError("DFS_MLB_FIT_HOOK_RUNS_INVALID")
        if not isinstance(self.removed_before_next_batter, bool):
            raise MlbJointPathFitError("DFS_MLB_FIT_HOOK_REMOVAL_FLAG_INVALID")
        _sha(self.source_sha256)


@dataclass(frozen=True)
class HistoricalBaserunningOpportunity:
    occurred_at: datetime
    kind: str
    success: bool
    source_sha256: str

    def validate(self) -> None:
        _utc(self.occurred_at)
        if self.kind not in _BASERUN_KINDS:
            raise MlbJointPathFitError("DFS_MLB_FIT_BASERUN_KIND_INVALID")
        if not isinstance(self.success, bool):
            raise MlbJointPathFitError("DFS_MLB_FIT_BASERUN_SUCCESS_INVALID")
        _sha(self.source_sha256)


def _validate_prior_rows(rows: Sequence[object], policy: MlbJointPathFitPolicy) -> None:
    policy.validate()
    cutoff = _utc(policy.cutoff_at)
    if not rows:
        raise MlbJointPathFitError("DFS_MLB_FIT_ROWS_EMPTY")
    for row in rows:
        validate = getattr(row, "validate", None)
        if validate is None:
            raise MlbJointPathFitError("DFS_MLB_FIT_ROW_TYPE_INVALID")
        validate()
        occurred_at = _utc(getattr(row, "occurred_at"))
        if occurred_at >= cutoff:
            raise MlbJointPathFitError(
                f"DFS_MLB_FIT_NON_PRIOR_OBSERVATION:{occurred_at.isoformat()}:{cutoff.isoformat()}"
            )


def _source_id(label: str, rows: Sequence[object], policy: MlbJointPathFitPolicy) -> str:
    if not label.strip():
        raise MlbJointPathFitError("DFS_MLB_FIT_SOURCE_LABEL_REQUIRED")
    payload = {
        "fit_version": MLB_JOINT_PATH_FIT_VERSION,
        "label": label,
        "policy_sha256": policy.digest(),
        "rows": [_serialize_row(row) for row in rows],
    }
    return f"{label}:{_canonical_hash(payload)}"


def fit_plate_appearance_profile(
    observations: Iterable[HistoricalPlateAppearance],
    *,
    policy: MlbJointPathFitPolicy,
    batter_id: str,
    pitcher_role: str,
    source_label: str,
) -> PlateAppearanceProfile:
    rows = list(observations)
    _validate_prior_rows(rows, policy)
    if pitcher_role not in _HOOK_ROLES:
        raise MlbJointPathFitError("DFS_MLB_FIT_PITCHER_ROLE_INVALID")
    selected = [row for row in rows if row.batter_id == batter_id and row.pitcher_role == pitcher_role]
    if len(selected) < policy.min_pa:
        raise MlbJointPathFitError(
            f"DFS_MLB_FIT_PA_INSUFFICIENT:{batter_id}:{pitcher_role}:{len(selected)}:{policy.min_pa}"
        )

    outcome_counts: dict[str, int] = {}
    pitch_counts: dict[int, int] = {}
    for row in selected:
        outcome_counts[row.outcome] = outcome_counts.get(row.outcome, 0) + 1
        pitch_counts[int(row.pitch_count)] = pitch_counts.get(int(row.pitch_count), 0) + 1
    n = len(selected)
    return PlateAppearanceProfile(
        outcome_probabilities={key: count / n for key, count in sorted(outcome_counts.items())},
        pitch_count_probabilities={key: count / n for key, count in sorted(pitch_counts.items())},
        source_id=_source_id(source_label, selected, policy),
    )


def _bucket(value: int, upper_bounds: tuple[int, ...], *, label: str) -> int:
    for index, upper in enumerate(upper_bounds):
        if value <= upper:
            return index
    raise MlbJointPathFitError(f"{label}:OUT_OF_SUPPORT:{value}")


def fit_hook_hazard_surface(
    observations: Iterable[HistoricalHookOpportunity],
    *,
    policy: MlbJointPathFitPolicy,
    source_label: str,
) -> HookHazardSurface:
    rows = list(observations)
    _validate_prior_rows(rows, policy)
    pitch_bins = policy.pitch_count_upper_bounds
    run_bins = policy.runs_allowed_upper_bounds
    trials = [[0 for _ in run_bins] for _ in pitch_bins]
    removals = [[0 for _ in run_bins] for _ in pitch_bins]

    for row in rows:
        pidx = _bucket(int(row.cumulative_pitch_count), pitch_bins, label="DFS_MLB_FIT_HOOK_PITCH")
        ridx = _bucket(int(row.cumulative_runs_allowed), run_bins, label="DFS_MLB_FIT_HOOK_RUNS")
        trials[pidx][ridx] += 1
        removals[pidx][ridx] += int(row.removed_before_next_batter)

    probabilities: list[tuple[float, ...]] = []
    for pidx, row_trials in enumerate(trials):
        fitted_row: list[float] = []
        for ridx, cell_trials in enumerate(row_trials):
            if cell_trials < policy.min_hook_cell_trials:
                raise MlbJointPathFitError(
                    f"DFS_MLB_FIT_HOOK_CELL_INSUFFICIENT:{pidx}:{ridx}:{cell_trials}:{policy.min_hook_cell_trials}"
                )
            fitted_row.append(removals[pidx][ridx] / cell_trials)
        probabilities.append(tuple(fitted_row))

    return HookHazardSurface(
        pitch_count_upper_bounds=pitch_bins,
        runs_allowed_upper_bounds=run_bins,
        remove_probabilities=tuple(probabilities),
        source_id=_source_id(source_label, rows, policy),
    )


def fit_baserunning_profile(
    observations: Iterable[HistoricalBaserunningOpportunity],
    *,
    policy: MlbJointPathFitPolicy,
    source_label: str,
) -> BaserunningProfile:
    rows = list(observations)
    _validate_prior_rows(rows, policy)
    values: dict[str, float] = {}
    for kind in _BASERUN_KINDS:
        selected = [row for row in rows if row.kind == kind]
        if len(selected) < policy.min_baserunning_opportunities:
            raise MlbJointPathFitError(
                f"DFS_MLB_FIT_BASERUN_INSUFFICIENT:{kind}:{len(selected)}:{policy.min_baserunning_opportunities}"
            )
        values[kind] = sum(int(row.success) for row in selected) / len(selected)

    return BaserunningProfile(
        single_second_scores=values["SINGLE_SECOND_SCORES"],
        single_first_to_third=values["SINGLE_FIRST_TO_THIRD"],
        double_first_scores=values["DOUBLE_FIRST_SCORES"],
        source_id=_source_id(source_label, rows, policy),
    )


def fit_receipt(
    *,
    policy: MlbJointPathFitPolicy,
    pa_profiles: Mapping[str, PlateAppearanceProfile],
    hook_surfaces: Mapping[str, HookHazardSurface],
    baserunning: BaserunningProfile,
) -> dict[str, object]:
    """Return a deterministic zero-authority identity for an assembled fit bundle."""
    policy.validate()
    payload = {
        "fit_version": MLB_JOINT_PATH_FIT_VERSION,
        "policy_id": policy.policy_id,
        "policy_sha256": policy.digest(),
        "cutoff_at": _utc(policy.cutoff_at).isoformat(),
        "pa_profiles": {key: value.identity() for key, value in sorted(pa_profiles.items())},
        "hook_surfaces": {key: value.identity() for key, value in sorted(hook_surfaces.items())},
        "baserunning": baserunning.identity(),
    }
    return {
        "fit_version": MLB_JOINT_PATH_FIT_VERSION,
        "policy_id": policy.policy_id,
        "policy_sha256": policy.digest(),
        "cutoff_at": _utc(policy.cutoff_at).isoformat(),
        "bundle_sha256": _canonical_hash(payload),
        "model_p_authority": False,
        "truth_gate_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "dfs_production_ready": False,
    }
