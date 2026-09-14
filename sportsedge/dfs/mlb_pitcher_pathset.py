from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Iterable, Mapping


MLB_PITCHER_PATH_SET_VALIDATION_VERSION = "MLB_SP_PATH_SET_V1"


class MlbPitcherPathSetError(ValueError):
    """Raised when a starter path set cannot prove endogenous behavior."""


@dataclass(frozen=True)
class MlbPitcherPathSetPolicy:
    policy_id: str
    status: str
    min_paths: int
    p_outs_ge_21_min: float
    p_outs_ge_21_max: float
    min_bullpen_active_fraction: float
    min_lead_divergence_fraction: float

    def validate(self) -> None:
        if self.status != "FROZEN":
            raise MlbPitcherPathSetError("DFS_MLB_PITCHER_PATH_SET_POLICY_NOT_FROZEN")
        if not self.policy_id.strip():
            raise MlbPitcherPathSetError("DFS_MLB_PITCHER_PATH_SET_POLICY_ID_MISSING")
        if self.min_paths < 2:
            raise MlbPitcherPathSetError("DFS_MLB_PITCHER_PATH_SET_MIN_PATHS_INVALID")
        for name, value in (
            ("p_outs_ge_21_min", self.p_outs_ge_21_min),
            ("p_outs_ge_21_max", self.p_outs_ge_21_max),
            ("min_bullpen_active_fraction", self.min_bullpen_active_fraction),
            ("min_lead_divergence_fraction", self.min_lead_divergence_fraction),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise MlbPitcherPathSetError(f"DFS_MLB_PITCHER_PATH_SET_POLICY_VALUE_INVALID:{name}")
        if self.p_outs_ge_21_min > self.p_outs_ge_21_max:
            raise MlbPitcherPathSetError("DFS_MLB_PITCHER_PATH_SET_OUTS_BAND_INVALID")
        if self.min_bullpen_active_fraction <= 0.0:
            raise MlbPitcherPathSetError("DFS_MLB_PITCHER_PATH_SET_BULLPEN_FRACTION_MUST_BE_POSITIVE")
        if self.min_lead_divergence_fraction <= 0.0:
            raise MlbPitcherPathSetError("DFS_MLB_PITCHER_PATH_SET_LEAD_DIVERGENCE_MUST_BE_POSITIVE")

    def digest(self) -> str:
        payload = {
            "min_bullpen_active_fraction": self.min_bullpen_active_fraction,
            "min_lead_divergence_fraction": self.min_lead_divergence_fraction,
            "min_paths": self.min_paths,
            "p_outs_ge_21_max": self.p_outs_ge_21_max,
            "p_outs_ge_21_min": self.p_outs_ge_21_min,
            "policy_id": self.policy_id,
            "status": self.status,
            "validation_version": MLB_PITCHER_PATH_SET_VALIDATION_VERSION,
        }
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class MlbPitcherPathSetValidation:
    validation_version: str
    policy_id: str
    policy_sha256: str
    path_set_sha256: str
    path_count: int
    bf_earned_run_correlation: float
    p_outs_ge_21: float
    bullpen_active_fraction: float
    lead_divergence_fraction: float
    passed: bool
    failures: tuple[str, ...]


def _number(row: Mapping[str, object], key: str) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MlbPitcherPathSetError(f"DFS_MLB_PITCHER_PATH_SET_FIELD_INVALID:{key}")
    value = float(value)
    if not math.isfinite(value):
        raise MlbPitcherPathSetError(f"DFS_MLB_PITCHER_PATH_SET_FIELD_NONFINITE:{key}")
    return value


def _binary(row: Mapping[str, object], key: str) -> int:
    value = _number(row, key)
    if value not in (0.0, 1.0):
        raise MlbPitcherPathSetError(f"DFS_MLB_PITCHER_PATH_SET_BINARY_INVALID:{key}:{value}")
    return int(value)


def _pearson(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        raise MlbPitcherPathSetError("DFS_MLB_PITCHER_PATH_SET_CORRELATION_SAMPLE_INVALID")
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = math.sqrt(sum(v * v for v in dx) * sum(v * v for v in dy))
    if denom <= 0.0:
        raise MlbPitcherPathSetError("DFS_MLB_PITCHER_PATH_SET_CORRELATION_UNDEFINED")
    return sum(a * b for a, b in zip(dx, dy)) / denom


def _canonical_path_set_digest(rows: list[Mapping[str, object]]) -> str:
    canonical = []
    for row in rows:
        canonical.append({str(key): row[key] for key in sorted(row)})
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(payload.encode()).hexdigest()


def validate_mlb_pitcher_path_set(
    paths: Iterable[Mapping[str, object]],
    policy: MlbPitcherPathSetPolicy,
) -> MlbPitcherPathSetValidation:
    """Validate behaviors that cannot be established by per-path producer flags.

    This intentionally ignores the V3 self-asserted behavioral booleans. It derives
    hook/bullpen/final-state diagnostics from the path distribution itself.
    """
    policy.validate()
    rows = list(paths)
    if len(rows) < policy.min_paths:
        raise MlbPitcherPathSetError(
            f"DFS_MLB_PITCHER_PATH_SET_TOO_SMALL:{len(rows)}:{policy.min_paths}"
        )

    bfs: list[float] = []
    earned_runs: list[float] = []
    outs: list[float] = []
    bullpen_active = 0
    lead_divergence = 0

    for row in rows:
        bf = _number(row, "starter_exit_batters_faced")
        er = _number(row, "earned_runs")
        path_outs = _number(row, "outs")
        bullpen_hits = _number(row, "bullpen_hits_allowed")
        lead_at_exit = _binary(row, "lead_at_exit")
        lead_preserved = _binary(row, "lead_preserved_to_final")
        if bf < 0 or er < 0 or path_outs < 0 or bullpen_hits < 0:
            raise MlbPitcherPathSetError("DFS_MLB_PITCHER_PATH_SET_NEGATIVE_VALUE")
        bfs.append(bf)
        earned_runs.append(er)
        outs.append(path_outs)
        if bullpen_hits > 0.0:
            bullpen_active += 1
        if lead_at_exit != lead_preserved:
            lead_divergence += 1

    corr = _pearson(bfs, earned_runs)
    p_outs_ge_21 = sum(value >= 21.0 for value in outs) / len(rows)
    bullpen_active_fraction = bullpen_active / len(rows)
    lead_divergence_fraction = lead_divergence / len(rows)

    failures: list[str] = []
    if not corr < 0.0:
        failures.append("BF_EARNED_RUN_CORRELATION_NOT_NEGATIVE")
    if not policy.p_outs_ge_21_min <= p_outs_ge_21 <= policy.p_outs_ge_21_max:
        failures.append("OUTS_GE_21_OUTSIDE_FROZEN_BAND")
    if bullpen_active_fraction < policy.min_bullpen_active_fraction:
        failures.append("BULLPEN_ACTIVE_FRACTION_TOO_LOW")
    if lead_divergence_fraction < policy.min_lead_divergence_fraction:
        failures.append("LEAD_FINAL_DIVERGENCE_TOO_LOW")

    return MlbPitcherPathSetValidation(
        validation_version=MLB_PITCHER_PATH_SET_VALIDATION_VERSION,
        policy_id=policy.policy_id,
        policy_sha256=policy.digest(),
        path_set_sha256=_canonical_path_set_digest(rows),
        path_count=len(rows),
        bf_earned_run_correlation=corr,
        p_outs_ge_21=p_outs_ge_21,
        bullpen_active_fraction=bullpen_active_fraction,
        lead_divergence_fraction=lead_divergence_fraction,
        passed=not failures,
        failures=tuple(failures),
    )
