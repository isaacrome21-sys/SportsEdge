"""Deterministic 2021-2024 fit for NFL discrete v2 family B."""
from __future__ import annotations

from hashlib import sha256
from math import exp, lgamma, log
from pathlib import Path
from typing import Any
import json

SNAPSHOT = Path(__file__).resolve().parents[3] / "data" / "nfl_discrete_v2" / "scores_2021_2024_reg.json"
FREEZE_PATH = Path(__file__).resolve().parents[3] / "config" / "nfl_discrete_v2_freeze.json"
SEASONS = {2021, 2022, 2023, 2024}
GRID_MAX = 70
L0_GRID = (0.2, 0.4, 0.6, 0.8, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0, 12.0)
L3_GRID = (1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0, 3.5)
L7_GRID = (1.0, 1.2, 1.5, 1.8, 2.0, 2.5, 3.0)
REFINE = (0.7, 0.85, 1.0, 1.15, 1.3)
REFINE3 = (0.85, 0.92, 1.0, 1.08, 1.15)


def canonical_sha256(value: dict[str, Any]) -> str:
    raw = json.dumps(dict(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def snapshot_sha256(path: Path | None = None) -> str:
    return sha256((path or SNAPSHOT).read_bytes()).hexdigest()


def load_fit_games(path: Path | None = None) -> list[tuple[int, int]]:
    payload = json.loads((path or SNAPSHOT).read_text())
    rows: list[tuple[int, int]] = []
    for season, _week, home, away in payload:
        season = int(season)
        if season not in SEASONS:
            raise ValueError(f"NFL_DISCRETE_V2_FIT_SEASON_LEAK:{season}")
        rows.append((int(home), int(away)))
    if len(rows) != 1087:
        raise ValueError(f"NFL_DISCRETE_V2_FIT_N:{len(rows)}")
    return rows


def _moments(rows: list[tuple[int, int]]) -> dict[str, float]:
    n = len(rows)
    mu_h = sum(h for h, _a in rows) / n
    mu_a = sum(a for _h, a in rows) / n
    var_h = sum((h - mu_h) ** 2 for h, _a in rows) / n
    var_a = sum((a - mu_a) ** 2 for _h, a in rows) / n
    return {
        "n": float(n),
        "mean_home_score": mu_h,
        "mean_away_score": mu_a,
        "nb_r_home": mu_h**2 / (var_h - mu_h),
        "nb_r_away": mu_a**2 / (var_a - mu_a),
        "home_win_rate_ties_as_not_home": sum(1 for h, a in rows if h > a) / n,
        "tie_rate": sum(1 for h, a in rows if h == a) / n,
        "p_abs_margin_3": sum(1 for h, a in rows if abs(h - a) == 3) / n,
        "p_abs_margin_7": sum(1 for h, a in rows if abs(h - a) == 7) / n,
        "p_abs_margin_10": sum(1 for h, a in rows if abs(h - a) == 10) / n,
    }


def _nb_logpmf(k: int, mu: float, r: float) -> float:
    p = r / (r + mu)
    return lgamma(k + r) - lgamma(k + 1) - lgamma(r) + r * log(p) + k * log(1.0 - p)


def _base_buckets(mu_h: float, mu_a: float, r_h: float, r_a: float) -> tuple[float, float, float, float]:
    lh = [_nb_logpmf(k, mu_h, r_h) for k in range(GRID_MAX + 1)]
    la = [_nb_logpmf(k, mu_a, r_a) for k in range(GRID_MAX + 1)]
    mx = max(lh) + max(la)
    b0 = b3 = b7 = other = 0.0
    for h in range(GRID_MAX + 1):
        for a in range(GRID_MAX + 1):
            p = exp(lh[h] + la[a] - mx)
            m = abs(h - a)
            if m == 0:
                b0 += p
            elif m == 3:
                b3 += p
            elif m == 7:
                b7 += p
            else:
                other += p
    return b0, b3, b7, other


def select_lifts(moments: dict[str, float]) -> tuple[float, float, float]:
    b0, b3, b7, other = _base_buckets(
        moments["mean_home_score"], moments["mean_away_score"], moments["nb_r_home"], moments["nb_r_away"]
    )
    target = (moments["tie_rate"], moments["p_abs_margin_3"], moments["p_abs_margin_7"])

    def err(l0: float, l3: float, l7: float) -> float:
        tot = b0 * l0 + b3 * l3 + b7 * l7 + other
        m0, m3, m7 = (b0 * l0) / tot, (b3 * l3) / tot, (b7 * l7) / tot
        return abs(m0 - target[0]) + abs(m3 - target[1]) + abs(m7 - target[2])

    best = None
    for l0 in L0_GRID:
        for l3 in L3_GRID:
            for l7 in L7_GRID:
                e = err(l0, l3, l7)
                if best is None or e < best[0]:
                    best = (e, l0, l3, l7)
    assert best is not None
    _e, s0, s3, s7 = best
    refined = None
    for l0 in (s0 * x for x in REFINE):
        for l3 in (s3 * x for x in REFINE3):
            for l7 in (s7 * x for x in REFINE3):
                e = err(l0, l3, l7)
                if refined is None or e < refined[0]:
                    refined = (e, l0, l3, l7)
    assert refined is not None
    return refined[1], refined[2], refined[3]


def build_freeze(path: Path | None = None) -> dict[str, Any]:
    source = path or SNAPSHOT
    moments = _moments(load_fit_games(source))
    l0, l3, l7 = select_lifts(moments)
    payload: dict[str, Any] = {
        "schema_version": "SPORTSEDGE_NFL_DISCRETE_V2_FREEZE_V1",
        "status": "FROZEN_FIT_WINDOW_ONLY_NOT_PROMOTED",
        "family": "B_INDEPENDENT_NB_PLUS_MARGIN_SPIKES_0_3_7",
        "spec": "1245_v2.1",
        "fit_window": {
            "seasons": [2021, 2022, 2023, 2024],
            "game_type": "REG",
            "n_games": 1087,
            "source": "data/nfl_discrete_v2/scores_2021_2024_reg.json",
            "source_sha256": snapshot_sha256(source),
        },
        "holdout": {
            "if_sha_before_2026_10_01_w4_kickoff": {"weeks": [4, 5, 6, 7, 8, 9, 10, 11, 12], "season": 2026, "game_type": "REG"},
            "if_sha_misses_kickoff": {"weeks": [5, 6, 7, 8, 9, 10, 11, 12, 13], "season": 2026, "game_type": "REG"},
            "min_n": 80,
        },
        "location": "FROZEN_ATTEMPT9_RAW_MARGIN_AND_TOTAL_UNCHANGED",
        "shape": {
            "grid_max": GRID_MAX,
            "nb_r_home": moments["nb_r_home"],
            "nb_r_away": moments["nb_r_away"],
            "margin_lifts": {"0": l0, "abs_3": l3, "abs_7": l7},
            "lift_fit_location": {"mean_home_score": moments["mean_home_score"], "mean_away_score": moments["mean_away_score"]},
        },
        "fit_window_baselines": {
            "home_win_rate_ties_as_not_home": moments["home_win_rate_ties_as_not_home"],
            "tie_rate": moments["tie_rate"],
            "p_abs_margin_3": moments["p_abs_margin_3"],
            "p_abs_margin_7": moments["p_abs_margin_7"],
            "p_abs_margin_10": moments["p_abs_margin_10"],
        },
        "authority": {"creates_model_p": False, "phone_card": False, "truth_gate": False, "official": False},
        "notes": "Family B frozen on 2021-2024 only. Do not look at 2025 or 2026 W1-W3 for retune. Attempt 9 and M2 bytes untouched.",
    }
    payload["artifact_sha256"] = canonical_sha256({k: v for k, v in payload.items() if k != "artifact_sha256"})
    return payload


def write_freeze(path: Path | None = None) -> dict[str, Any]:
    payload = build_freeze()
    (path or FREEZE_PATH).write_text(json.dumps(payload, indent=2) + "\n")
    return payload
