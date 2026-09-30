"""NFL discrete v2 family B — frozen 2021-2024 shape only.

Independent negative-binomial scores plus extra mass on exact margins
{0, ±3, ±7}. Location comes from frozen Attempt 9 means. Does not edit
Attempt 9 or M2. Does not emit Model_P or price the phone card.
"""
from __future__ import annotations

from hashlib import sha256
from math import exp, lgamma, log
from pathlib import Path
from typing import Any, Mapping
import json

FREEZE_PATH = Path(__file__).resolve().parents[3] / "config" / "nfl_discrete_v2_freeze.json"
SCHEMA = "SPORTSEDGE_NFL_DISCRETE_V2_FREEZE_V1"
FAMILY = "B_INDEPENDENT_NB_PLUS_MARGIN_SPIKES_0_3_7"


def canonical_sha256(value: Mapping[str, Any]) -> str:
    raw = json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def load_freeze(path: Path | None = None) -> dict[str, Any]:
    artifact = json.loads((path or FREEZE_PATH).read_text())
    expected = str(artifact.get("artifact_sha256") or "").lower()
    payload = dict(artifact)
    payload.pop("artifact_sha256", None)
    actual = canonical_sha256(payload)
    if artifact.get("schema_version") != SCHEMA:
        raise ValueError("NFL_DISCRETE_V2_SCHEMA_INVALID")
    if artifact.get("family") != FAMILY:
        raise ValueError("NFL_DISCRETE_V2_FAMILY_INVALID")
    if artifact.get("status") != "FROZEN_FIT_WINDOW_ONLY_NOT_PROMOTED":
        raise ValueError("NFL_DISCRETE_V2_STATUS_INVALID")
    if expected != actual:
        raise ValueError(f"NFL_DISCRETE_V2_SHA_MISMATCH:{actual}")
    return artifact


def _nb_logpmf(k: int, mu: float, r: float) -> float:
    if mu <= 0 or r <= 0 or k < 0:
        raise ValueError("NFL_DISCRETE_V2_NB_INVALID")
    p = r / (r + mu)
    return lgamma(k + r) - lgamma(k + 1) - lgamma(r) + r * log(p) + k * log(1.0 - p)


def score_grid(mean_home: float, mean_away: float, freeze: Mapping[str, Any] | None = None) -> list[list[float]]:
    art = freeze or load_freeze()
    shape = art["shape"]
    max_s = int(shape["grid_max"])
    r_h = float(shape["nb_r_home"])
    r_a = float(shape["nb_r_away"])
    lifts = shape["margin_lifts"]
    l0 = float(lifts["0"])
    l3 = float(lifts["abs_3"])
    l7 = float(lifts["abs_7"])
    lh = [_nb_logpmf(k, float(mean_home), r_h) for k in range(max_s + 1)]
    la = [_nb_logpmf(k, float(mean_away), r_a) for k in range(max_s + 1)]
    mx = max(lh) + max(la)
    grid = [[0.0] * (max_s + 1) for _ in range(max_s + 1)]
    total = 0.0
    for h in range(max_s + 1):
        for a in range(max_s + 1):
            p = exp(lh[h] + la[a] - mx)
            m = h - a
            if m == 0:
                p *= l0
            elif abs(m) == 3:
                p *= l3
            elif abs(m) == 7:
                p *= l7
            grid[h][a] = p
            total += p
    for h in range(max_s + 1):
        for a in range(max_s + 1):
            grid[h][a] /= total
    return grid


def margin_mass(grid: list[list[float]], abs_margin: int) -> float:
    out = 0.0
    for h, row in enumerate(grid):
        for a, p in enumerate(row):
            if abs(h - a) == abs_margin:
                out += p
    return out


def home_win_mass(grid: list[list[float]]) -> float:
    return sum(p for h, row in enumerate(grid) for a, p in enumerate(row) if h > a)


def tie_mass(grid: list[list[float]]) -> float:
    return margin_mass(grid, 0)
