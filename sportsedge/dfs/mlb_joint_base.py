from __future__ import annotations

from math import exp, sqrt
import random
from typing import Any, Mapping

from sportsedge.sports.mlb.prop_efficiency_engine import build_efficiency_distribution
from sportsedge.sports.mlb.prop_volume_stage1 import MLBVolumeStage1

from .types import DKPlayer

_BATTING_ORDER_PA = {1: 4.65, 2: 4.55, 3: 4.45, 4: 4.35, 5: 4.25, 6: 4.15, 7: 4.05, 8: 3.95, 9: 3.85}


def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, float(value)))


def _ratio(num: float, den: float, prior: float, prior_n: float) -> float:
    return (max(0.0, num) + prior * prior_n) / max(max(0.0, den) + prior_n, 1e-9)


def _poisson(rng: random.Random, mean: float) -> int:
    lam = max(0.0, float(mean))
    if lam <= 0:
        return 0
    if lam >= 18:
        return max(0, int(round(rng.gauss(lam, sqrt(lam)))))
    threshold = exp(-lam)
    product = 1.0
    k = 0
    while product > threshold:
        k += 1
        product *= rng.random()
    return k - 1


def _binomial(rng: random.Random, n: int, p: float) -> int:
    n = max(0, int(n))
    p = _clamp(p, 0.0, 1.0)
    if n == 0 or p == 0:
        return 0
    if p == 1:
        return n
    if n >= 25:
        mean = n * p
        sd = sqrt(max(n * p * (1.0 - p), 1e-9))
        return min(n, max(0, int(round(rng.gauss(mean, sd)))))
    return sum(1 for _ in range(n) if rng.random() < p)


def _allocate(rng: random.Random, total: int, ids: list[str], weights: list[float]) -> dict[str, int]:
    if not ids:
        return {}
    out = {pid: 0 for pid in ids}
    positive = [max(1e-9, float(w)) for w in weights]
    if total <= 0:
        return out
    for pid in rng.choices(ids, weights=positive, k=int(total)):
        out[pid] += 1
    return out


def _stats_index(stats_snapshot: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    out: dict[str, Mapping[str, Any]] = {}
    for row in stats_snapshot.get("players") or []:
        if isinstance(row, Mapping):
            pid = str(row.get("dk_player_id") or "")
            if pid:
                out[pid] = row
    return out


def _rate_mean(metric: str, baseline: float, uncertainty: float = 0.06) -> float:
    return build_efficiency_distribution(
        metric,
        {"baseline": _clamp(baseline, 0.001, 0.999), "uncertainty": uncertainty},
    ).mean


def _hitter_profile(player: DKPlayer, row: Mapping[str, Any]) -> dict[str, float]:
    stat = row.get("hitting") if isinstance(row.get("hitting"), Mapping) else {}
    pa = float(stat.get("plate_appearances", 0.0) or 0.0)
    games = float(stat.get("games", 0.0) or 0.0)
    order = int(player.raw.get("mlb_batting_order") or 0)
    if order not in _BATTING_ORDER_PA:
        raise ValueError(f"MLB_DFS_BATTING_ORDER_MISSING:{player.team}:{player.name}")
    role_pa = _BATTING_ORDER_PA[order]
    per_game = pa / games if games > 0 else role_pa
    try:
        opportunity = MLBVolumeStage1().project(
            player_id=player.player_id,
            metric="plate_appearances",
            history=[{"plate_appearances": per_game}],
            role_opportunity_mean=role_pa,
        ).mean
    except Exception:
        opportunity = role_pa

    singles = float(stat.get("singles", 0.0) or 0.0)
    doubles = float(stat.get("doubles", 0.0) or 0.0)
    triples = float(stat.get("triples", 0.0) or 0.0)
    homers = float(stat.get("home_runs", 0.0) or 0.0)
    walks = float(stat.get("walks", 0.0) or 0.0)
    hbp = float(stat.get("hbp", 0.0) or 0.0)
    strikeouts = float(stat.get("strikeouts", 0.0) or 0.0)
    hit_rate = _rate_mean("hit_rate", _ratio(singles + doubles + triples + homers, pa, 0.225, 100.0))
    xb_rate = _rate_mean("extra_base_hit_rate", _ratio(doubles + triples + homers, pa, 0.080, 120.0))
    k_rate = _rate_mean("strikeout_rate", _ratio(strikeouts, pa, 0.225, 110.0))
    bb_rate = _rate_mean("walk_rate", _ratio(walks, pa, 0.082, 110.0))
    hr_rate = _ratio(homers, pa, 0.032, 140.0)
    triple_rate = _ratio(triples, pa, 0.004, 180.0)
    double_rate = max(0.0, xb_rate - hr_rate - triple_rate)
    single_rate = max(0.001, hit_rate - double_rate - triple_rate - hr_rate)
    hbp_rate = _ratio(hbp, pa, 0.011, 140.0)
    on_base = max(1.0, singles + doubles + triples + homers + walks + hbp)
    sb_rate = _ratio(float(stat.get("stolen_bases", 0.0) or 0.0), on_base, 0.055, 35.0)
    category_sum = single_rate + double_rate + triple_rate + hr_rate + bb_rate + hbp_rate + k_rate
    if category_sum > 0.94:
        scale = 0.94 / category_sum
        single_rate *= scale
        double_rate *= scale
        triple_rate *= scale
        hr_rate *= scale
        bb_rate *= scale
        hbp_rate *= scale
        k_rate *= scale
    return {
        "pa_mean": opportunity,
        "single_rate": single_rate,
        "double_rate": double_rate,
        "triple_rate": triple_rate,
        "hr_rate": hr_rate,
        "walk_rate": bb_rate,
        "hbp_rate": hbp_rate,
        "k_rate": k_rate,
        "sb_rate": _clamp(sb_rate, 0.0, 0.45),
        "order": float(order),
    }


def _pitcher_profile(player: DKPlayer, row: Mapping[str, Any]) -> dict[str, float]:
    stat = row.get("pitching") if isinstance(row.get("pitching"), Mapping) else {}
    starts = float(stat.get("games_started", 0.0) or 0.0)
    bf = float(stat.get("batters_faced", 0.0) or 0.0)
    pitches = float(stat.get("pitches_thrown", 0.0) or 0.0)
    bf_per_start = bf / starts if starts > 0 else 22.0
    pitch_per_start = pitches / starts if starts > 0 else 92.0
    volume = MLBVolumeStage1()
    try:
        bf_mean = volume.project(
            player_id=player.player_id,
            metric="batters_faced",
            history=[{"batters_faced": bf_per_start}],
            role_opportunity_mean=bf_per_start,
        ).mean
    except Exception:
        bf_mean = bf_per_start
    try:
        pitch_mean = volume.project(
            player_id=player.player_id,
            metric="pitches_thrown",
            history=[{"pitches_thrown": pitch_per_start}],
            role_opportunity_mean=pitch_per_start,
        ).mean
    except Exception:
        pitch_mean = pitch_per_start
    return {
        "bf_mean": _clamp(bf_mean, 8.0, 35.0),
        "pitch_mean": _clamp(pitch_mean, 35.0, 125.0),
        "k_rate": _rate_mean("strikeout_rate", _ratio(float(stat.get("strikeouts", 0.0) or 0.0), bf, 0.225, 120.0)),
        "bb_rate": _rate_mean("walk_rate", _ratio(float(stat.get("walks_allowed", 0.0) or 0.0), bf, 0.082, 120.0)),
        "hit_rate": _rate_mean("hit_rate", _ratio(float(stat.get("hits_allowed", 0.0) or 0.0), bf, 0.225, 120.0)),
        "er_rate": _clamp(_ratio(float(stat.get("earned_runs", 0.0) or 0.0), bf, 0.115, 150.0), 0.02, 0.30),
        "hbp_rate": _clamp(_ratio(float(stat.get("hbp_allowed", 0.0) or 0.0), bf, 0.011, 160.0), 0.001, 0.06),
    }
