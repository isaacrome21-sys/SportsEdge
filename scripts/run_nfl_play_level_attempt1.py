#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import numpy as np

from sportsedge.sports.nfl.m2_history_features import select_starting_qb

try:
    from scripts.build_nfl_attempt9_runtime_artifact import reconstruct as reconstruct_attempt9
except ModuleNotFoundError:
    from build_nfl_attempt9_runtime_artifact import reconstruct as reconstruct_attempt9

ROOT = Path(__file__).resolve().parents[1]
PRELOCK_PATH = ROOT / "config/research/nfl_play_level_attempt1_prelock_v1.json"
IMPL_PATH = ROOT / "config/research/nfl_play_level_attempt1_implementation_v2.json"
SOURCE_CONFIG = ROOT / "config/public_training_sources_v1.json"
PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.csv.gz"
DEPTH_URL = "https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{season}.csv"
EASTERN = ZoneInfo("America/New_York")
TEAM_ALIASES = {"LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV", "WSH": "WAS", "JAC": "JAX"}
ZERO_AUTHORITY = {
    "creates_model_p": False,
    "promotion_authority": False,
    "truth_gate_authority": False,
    "official_authority": False,
    "staking_authority": False,
    "changes_2026_owner": False,
}

FEATURE_NAMES = (
    "off_epa_per_play",
    "def_epa_allowed_per_play",
    "off_success_rate",
    "def_success_rate_allowed",
    "off_pass_epa_per_dropback",
    "def_pass_epa_allowed_per_dropback",
    "off_rush_epa_per_rush",
    "def_rush_epa_allowed_per_rush",
    "neutral_pass_oe",
    "pace_plays_per_game",
    "starting_qb_epa_shrunk",
    "starting_qb_cpoe_shrunk",
)


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return TEAM_ALIASES.get(raw, raw)


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _int(value: Any) -> int | None:
    f = _float(value)
    return None if f is None else int(f)


def _flag(value: Any) -> bool:
    f = _float(value)
    return bool(f is not None and abs(f - 1.0) < 1e-12)


def _fetch(url: str, *, timeout: int = 180) -> bytes:
    req = Request(url, headers={"User-Agent": "SportsEdge-NFL-play-level-attempt1/1.0"})
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def _csv_rows(raw: bytes, *, gzipped: bool = False) -> Iterable[dict[str, str]]:
    source: io.BufferedIOBase
    if gzipped:
        source = gzip.GzipFile(fileobj=io.BytesIO(raw))
    else:
        source = io.BytesIO(raw)
    wrapper = io.TextIOWrapper(source, encoding="utf-8-sig", newline="")
    yield from csv.DictReader(wrapper)


def _kickoff(row: Mapping[str, Any]) -> datetime:
    day = str(row.get("gameday") or "").strip()
    clock = str(row.get("gametime") or "").strip()
    if not day or not clock:
        raise ValueError("NFL_ATTEMPT1_SCHEDULE_KICKOFF_MISSING")
    dt = datetime.fromisoformat(f"{day}T{clock}")
    return dt.replace(tzinfo=EASTERN)


def _depth_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt


def _half_point(line: float | None) -> bool:
    if line is None:
        return False
    doubled = line * 2.0
    return abs(doubled - round(doubled)) <= 1e-9 and int(round(doubled)) % 2 == 1


def _normal_cdf(x: float, mean: float, sigma: float) -> float:
    z = (x - mean) / (sigma * math.sqrt(2.0))
    return 0.5 * (1.0 + math.erf(z))


def _clip_p(p: float) -> float:
    return min(1.0 - 1e-12, max(1e-12, float(p)))


def _log_loss(ps: Iterable[float], ys: Iterable[int]) -> float:
    vals = []
    for p, y in zip(ps, ys):
        p = _clip_p(p)
        vals.append(-(y * math.log(p) + (1 - y) * math.log(1.0 - p)))
    return float(np.mean(vals)) if vals else float("nan")


def _brier(ps: Iterable[float], ys: Iterable[int]) -> float:
    vals = [(float(p) - int(y)) ** 2 for p, y in zip(ps, ys)]
    return float(np.mean(vals)) if vals else float("nan")


def _ece(ps: list[float], ys: list[int], bins: int = 10) -> float:
    if not ps:
        return float("nan")
    total = len(ps)
    out = 0.0
    for b in range(bins):
        lo = b / bins
        hi = (b + 1) / bins
        idx = [i for i, p in enumerate(ps) if (lo <= p < hi) or (b == bins - 1 and p == 1.0)]
        if not idx:
            continue
        mp = sum(ps[i] for i in idx) / len(idx)
        my = sum(ys[i] for i in idx) / len(idx)
        out += (len(idx) / total) * abs(mp - my)
    return out


def _calibration_logistic(ps: list[float], ys: list[int]) -> tuple[float, float]:
    if len(ps) < 20 or len(set(ys)) < 2:
        return float("nan"), float("nan")
    x = np.asarray([math.log(_clip_p(p) / (1.0 - _clip_p(p))) for p in ps], dtype=float)
    y = np.asarray(ys, dtype=float)
    design = np.column_stack([np.ones(len(x)), x])
    beta = np.asarray([0.0, 1.0], dtype=float)
    for _ in range(80):
        eta = np.clip(design @ beta, -30.0, 30.0)
        mu = 1.0 / (1.0 + np.exp(-eta))
        w = np.maximum(mu * (1.0 - mu), 1e-8)
        h = design.T @ (design * w[:, None])
        g = design.T @ (y - mu)
        try:
            step = np.linalg.solve(h, g)
        except np.linalg.LinAlgError:
            return float("nan"), float("nan")
        beta = beta + step
        if float(np.max(np.abs(step))) < 1e-10:
            break
    return float(beta[0]), float(beta[1])


@dataclass
class OffensiveAgg:
    plays: int = 0
    epa_sum: float = 0.0
    success_sum: float = 0.0
    dropbacks: int = 0
    pass_epa_sum: float = 0.0
    rushes: int = 0
    rush_epa_sum: float = 0.0
    neutral_oe_n: int = 0
    neutral_oe_sum: float = 0.0
    qb: dict[str, list[float]] = field(default_factory=dict)

    def add_qb(self, player: str, qb_epa: float, cpoe: float | None) -> None:
        row = self.qb.setdefault(player, [0.0, 0.0, 0.0, 0.0])
        row[0] += 1.0
        row[1] += qb_epa
        if cpoe is not None:
            row[2] += 1.0
            row[3] += cpoe

    def finalize(self) -> dict[str, Any] | None:
        if self.plays <= 0 or self.dropbacks <= 0 or self.rushes <= 0 or self.neutral_oe_n <= 0:
            return None
        return {
            "epa": self.epa_sum / self.plays,
            "success": self.success_sum / self.plays,
            "pass_epa": self.pass_epa_sum / self.dropbacks,
            "rush_epa": self.rush_epa_sum / self.rushes,
            "pass_oe": self.neutral_oe_sum / self.neutral_oe_n,
            "plays": float(self.plays),
            "qb": {k: tuple(v) for k, v in self.qb.items()},
        }


def parse_pbp_seasons(seasons: Iterable[int]) -> tuple[dict[str, dict[str, dict[str, Any]]], dict[str, str]]:
    games: dict[str, dict[str, OffensiveAgg]] = defaultdict(dict)
    hashes: dict[str, str] = {}
    for season in seasons:
        url = PBP_URL.format(season=int(season))
        raw = _fetch(url)
        hashes[str(season)] = sha256(raw).hexdigest()
        for row in _csv_rows(raw, gzipped=True):
            if _int(row.get("season")) != int(season):
                continue
            game_id = str(row.get("game_id") or "").strip()
            offense = _team(row.get("posteam"))
            defense = _team(row.get("defteam"))
            if not game_id or not offense or not defense or offense == defense:
                continue
            if _flag(row.get("no_play")) or _flag(row.get("two_point_attempt")) or _flag(row.get("qb_kneel")):
                continue
            dropback = _flag(row.get("qb_dropback"))
            rush = _flag(row.get("rush_attempt")) and not _flag(row.get("qb_spike"))
            if not (dropback or rush):
                continue
            epa = _float(row.get("epa"))
            if epa is None:
                continue
            bucket = games[game_id].setdefault(offense, OffensiveAgg())
            bucket.plays += 1
            bucket.epa_sum += epa
            success = _float(row.get("success"))
            bucket.success_sum += (1.0 if epa > 0 else 0.0) if success is None else success
            if dropback:
                qbe = _float(row.get("qb_epa"))
                if qbe is None:
                    qbe = epa
                bucket.dropbacks += 1
                bucket.pass_epa_sum += qbe
                player = str(row.get("passer_player_id") or "").strip()
                if player:
                    bucket.add_qb(player, qbe, _float(row.get("cpoe")))
            if rush:
                bucket.rushes += 1
                bucket.rush_epa_sum += epa
            down = _int(row.get("down"))
            qtr = _int(row.get("qtr"))
            diff = _float(row.get("score_differential"))
            half_sec = _float(row.get("half_seconds_remaining"))
            pass_oe = _float(row.get("pass_oe"))
            xpass = _float(row.get("xpass"))
            neutral = (
                down in {1, 2}
                and qtr is not None and 1 <= qtr <= 3
                and diff is not None and abs(diff) <= 8.0
                and half_sec is not None and half_sec > 120.0
                and xpass is not None and pass_oe is not None
            )
            if neutral:
                bucket.neutral_oe_n += 1
                bucket.neutral_oe_sum += pass_oe
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for game_id, by_team in games.items():
        finalized = {team: agg.finalize() for team, agg in by_team.items()}
        good = {team: row for team, row in finalized.items() if row is not None}
        if len(good) == 2:
            out[game_id] = good
    return out, hashes


def parse_depth_seasons(seasons: Iterable[int]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Load raw depth rows for the already-audited M2 dual historical/modern resolver."""
    rows: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for season in seasons:
        url = DEPTH_URL.format(season=int(season))
        raw = _fetch(url)
        hashes[str(season)] = sha256(raw).hexdigest()
        for raw_row in _csv_rows(raw):
            row = dict(raw_row)
            if row.get("season") in (None, ""):
                row["season"] = str(int(season))
            if row.get("team") not in (None, ""):
                row["team"] = _team(row.get("team"))
            if row.get("club_code") not in (None, ""):
                row["club_code"] = _team(row.get("club_code"))
            rows.append(row)
    return rows, hashes


def starter_at(depth: Iterable[Mapping[str, Any]], team: str, game: Mapping[str, Any]) -> str | None:
    """Delegate QB identity to the merged production-M2 PIT depth contract."""
    week = game.get("week")
    if week is None:
        return None
    try:
        return select_starting_qb(
            depth,
            team=_team(team),
            season=int(game["season"]),
            week=int(week),
            game_start_ts=game["kickoff"],
        )
    except ValueError:
        return None


def load_schedule() -> tuple[list[dict[str, Any]], str]:
    cfg = json.loads(SOURCE_CONFIG.read_text())
    source = cfg["sources"]["nfl_attempt9"]
    raw = _fetch(source["raw_url"])
    digest = sha256(raw).hexdigest()
    if digest != source["expected_sha256"]:
        raise ValueError(f"NFL_ATTEMPT1_GAMES_SOURCE_SHA_MISMATCH:{digest}")
    rows: list[dict[str, Any]] = []
    for row in _csv_rows(raw):
        season = _int(row.get("season"))
        if season is None or season < 2010 or season > 2025:
            continue
        if str(row.get("game_type") or "REG").strip().upper() != "REG":
            continue
        hs = _int(row.get("home_score"))
        aw = _int(row.get("away_score"))
        if hs is None or aw is None:
            continue
        try:
            kickoff = _kickoff(row)
        except ValueError:
            continue
        rows.append({
            "season": season,
            "week": _int(row.get("week")),
            "game_id": str(row.get("game_id") or "").strip(),
            "kickoff": kickoff,
            "home": _team(row.get("home_team")),
            "away": _team(row.get("away_team")),
            "home_score": hs,
            "away_score": aw,
            "spread_line": _float(row.get("spread_line")),
            "total_line": _float(row.get("total_line")),
        })
    rows.sort(key=lambda g: (g["kickoff"], g["game_id"]))
    return rows, digest


def _attempt9_weighted(history: list[tuple[int, int]]) -> np.ndarray:
    arr = np.asarray(history[-10:], dtype=float)
    weights = 0.85 ** np.arange(len(arr) - 1, -1, -1)
    return np.average(arr, axis=0, weights=weights)


def _apply_attempt9(artifact: Mapping[str, Any], features: list[float], target: str) -> float:
    row = artifact["runtime"]["targets"][target]
    x = np.asarray(features, dtype=float)
    mean = np.asarray(row["feature_mean"], dtype=float)
    std = np.asarray(row["feature_std"], dtype=float)
    beta = np.asarray(row["coefficients"], dtype=float)
    return float(((x - mean) / std) @ beta + float(row["intercept"]))


def _wavg(items: list[dict[str, float]], key: str, lookback: int = 8, decay: float = 0.85) -> float | None:
    recent = items[-lookback:]
    vals = [row.get(key) for row in recent]
    if len(vals) < 4 or any(v is None or not math.isfinite(float(v)) for v in vals):
        return None
    weights = decay ** np.arange(len(vals) - 1, -1, -1)
    return float(np.average(np.asarray(vals, dtype=float), weights=weights))


def _team_vector(history: list[dict[str, float]], qb_epa: float, qb_cpoe: float) -> list[float] | None:
    keys = ["off_epa", "def_epa", "off_success", "def_success", "off_pass", "def_pass", "off_rush", "def_rush", "pass_oe", "plays"]
    vals = [_wavg(history, key) for key in keys]
    if any(v is None for v in vals):
        return None
    return [float(v) for v in vals] + [float(qb_epa), float(qb_cpoe)]


def _shrunk_qb(qb_hist: Mapping[str, list[float]], starter: str, prior_epa: float, prior_cpoe: float, pseudo: float = 100.0) -> tuple[float, float] | None:
    row = qb_hist.get(starter)
    if not row or row[0] < 20:
        return None
    n_db, epa_sum, n_cpoe, cpoe_sum = row
    if n_cpoe <= 0:
        return None
    epa = (epa_sum + pseudo * prior_epa) / (n_db + pseudo)
    cpoe = (cpoe_sum + pseudo * prior_cpoe) / (n_cpoe + pseudo)
    return float(epa), float(cpoe)


def build_rows(
    schedule: list[dict[str, Any]],
    pbp: Mapping[str, Mapping[str, Mapping[str, Any]]],
    depth: Iterable[Mapping[str, Any]],
    attempt9: Mapping[str, Any],
    seasons: set[int],
) -> list[dict[str, Any]]:
    score_hist: dict[str, list[tuple[int, int]]] = defaultdict(list)
    team_hist: dict[str, list[dict[str, float]]] = defaultdict(list)
    qb_hist: dict[str, list[float]] = {}
    pool_db = pool_epa = pool_cpoe_n = pool_cpoe = 0.0
    out: list[dict[str, Any]] = []

    for game in schedule:
        home = game["home"]
        away = game["away"]
        game_id = game["game_id"]
        a9: tuple[float, float] | None = None
        if len(score_hist[home]) >= 5 and len(score_hist[away]) >= 5:
            hp = _attempt9_weighted(score_hist[home])
            ap = _attempt9_weighted(score_hist[away])
            f = [hp[0], hp[1], ap[0], ap[1], hp[0] - hp[1], ap[0] - ap[1]]
            a9 = (_apply_attempt9(attempt9, f, "margin"), _apply_attempt9(attempt9, f, "total"))

        if game["season"] in seasons and a9 is not None and game_id in pbp and pool_db >= 100 and pool_cpoe_n >= 100:
            hs = starter_at(depth, home, game)
            aws = starter_at(depth, away, game)
            if hs and aws:
                prior_epa = pool_epa / pool_db
                prior_cpoe = pool_cpoe / pool_cpoe_n
                hq = _shrunk_qb(qb_hist, hs, prior_epa, prior_cpoe)
                aq = _shrunk_qb(qb_hist, aws, prior_epa, prior_cpoe)
                if hq and aq:
                    hv = _team_vector(team_hist[home], *hq)
                    av = _team_vector(team_hist[away], *aq)
                    if hv and av:
                        out.append({
                            **game,
                            "attempt9_margin": a9[0],
                            "attempt9_total": a9[1],
                            "x_margin": [h - a for h, a in zip(hv, av)],
                            "x_total": [h + a for h, a in zip(hv, av)],
                            "starter_home": hs,
                            "starter_away": aws,
                        })

        score_hist[home].append((game["home_score"], game["away_score"]))
        score_hist[away].append((game["away_score"], game["home_score"]))
        by_team = pbp.get(game_id)
        if not by_team or home not in by_team or away not in by_team:
            continue
        h = by_team[home]
        a = by_team[away]
        team_hist[home].append({
            "off_epa": h["epa"], "def_epa": a["epa"], "off_success": h["success"], "def_success": a["success"],
            "off_pass": h["pass_epa"], "def_pass": a["pass_epa"], "off_rush": h["rush_epa"], "def_rush": a["rush_epa"],
            "pass_oe": h["pass_oe"], "plays": h["plays"],
        })
        team_hist[away].append({
            "off_epa": a["epa"], "def_epa": h["epa"], "off_success": a["success"], "def_success": h["success"],
            "off_pass": a["pass_epa"], "def_pass": h["pass_epa"], "off_rush": a["rush_epa"], "def_rush": h["rush_epa"],
            "pass_oe": a["pass_oe"], "plays": a["plays"],
        })
        for offense in (h, a):
            for player, values in offense["qb"].items():
                row = qb_hist.setdefault(player, [0.0, 0.0, 0.0, 0.0])
                for i in range(4):
                    row[i] += float(values[i])
                pool_db += float(values[0])
                pool_epa += float(values[1])
                pool_cpoe_n += float(values[2])
                pool_cpoe += float(values[3])
    return out


def _fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float) -> dict[str, Any]:
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std == 0] = 1.0
    xs = (x - mean) / std
    xm = xs.mean(axis=0)
    ym = y.mean()
    xc = xs - xm
    yc = y - ym
    beta = np.linalg.solve(xc.T @ xc + float(alpha) * np.eye(x.shape[1]), xc.T @ yc)
    intercept = float(ym - xm @ beta)
    return {"mean": mean, "std": std, "beta": beta, "intercept": intercept, "alpha": float(alpha)}


def _predict(model: Mapping[str, Any], x: np.ndarray) -> np.ndarray:
    return ((x - model["mean"]) / model["std"]) @ model["beta"] + float(model["intercept"])


def select_alpha(rows: list[dict[str, Any]], target: str, grid: Iterable[float]) -> tuple[float, dict[str, float]]:
    xkey = "x_margin" if target == "margin" else "x_total"
    ykey = "home_margin" if target == "margin" else "game_total"
    basekey = "attempt9_margin" if target == "margin" else "attempt9_total"
    scores: dict[str, float] = {}
    for alpha in grid:
        se: list[float] = []
        for val_season in (2019, 2020, 2021, 2022, 2023):
            train = [r for r in rows if r["season"] < val_season]
            valid = [r for r in rows if r["season"] == val_season]
            if len(train) < 100 or not valid:
                continue
            x = np.asarray([r[xkey] for r in train], dtype=float)
            y = np.asarray([r[ykey] - r[basekey] for r in train], dtype=float)
            model = _fit_ridge(x, y, alpha)
            xv = np.asarray([r[xkey] for r in valid], dtype=float)
            corr = _predict(model, xv)
            pred = corr + np.asarray([r[basekey] for r in valid], dtype=float)
            actual = np.asarray([r[ykey] for r in valid], dtype=float)
            se.extend(((pred - actual) ** 2).tolist())
        if not se:
            raise ValueError("NFL_ATTEMPT1_ALPHA_CV_EMPTY")
        scores[str(alpha)] = float(math.sqrt(sum(se) / len(se)))
    best = min((score, float(alpha)) for alpha, score in ((float(k), v) for k, v in scores.items()))[1]
    return best, scores


def oof_sigma(rows: list[dict[str, Any]], target: str, alpha: float) -> float:
    xkey = "x_margin" if target == "margin" else "x_total"
    ykey = "home_margin" if target == "margin" else "game_total"
    basekey = "attempt9_margin" if target == "margin" else "attempt9_total"
    residuals: list[float] = []
    for val_season in (2019, 2020, 2021, 2022, 2023):
        train = [r for r in rows if r["season"] < val_season]
        valid = [r for r in rows if r["season"] == val_season]
        if len(train) < 100 or not valid:
            continue
        model = _fit_ridge(
            np.asarray([r[xkey] for r in train], dtype=float),
            np.asarray([r[ykey] - r[basekey] for r in train], dtype=float),
            alpha,
        )
        pred = _predict(model, np.asarray([r[xkey] for r in valid], dtype=float)) + np.asarray([r[basekey] for r in valid], dtype=float)
        actual = np.asarray([r[ykey] for r in valid], dtype=float)
        residuals.extend((actual - pred).tolist())
    if len(residuals) < 100:
        raise ValueError("NFL_ATTEMPT1_OOF_RESIDUALS_INSUFFICIENT")
    return float(np.std(np.asarray(residuals, dtype=float), ddof=1))


def _market_metrics(
    rows: list[dict[str, Any]],
    *,
    market: str,
    candidate_key: str,
    baseline_key: str,
    candidate_sigma: float,
    baseline_sigma: float,
) -> dict[str, Any]:
    cp: list[float] = []
    bp: list[float] = []
    y: list[int] = []
    for row in rows:
        if market == "spread":
            line = row.get("spread_line")
            if not _half_point(line):
                continue
            threshold = float(line)
            actual = float(row["home_margin"])
        else:
            line = row.get("total_line")
            if not _half_point(line):
                continue
            threshold = float(line)
            actual = float(row["game_total"])
        cp.append(_clip_p(1.0 - _normal_cdf(threshold, float(row[candidate_key]), candidate_sigma)))
        bp.append(_clip_p(1.0 - _normal_cdf(threshold, float(row[baseline_key]), baseline_sigma)))
        y.append(int(actual > threshold))
    ci, cs = _calibration_logistic(cp, y)
    bi, bs = _calibration_logistic(bp, y)
    return {
        "n": len(y),
        "candidate": {"log_loss": _log_loss(cp, y), "brier": _brier(cp, y), "ece": _ece(cp, y), "calibration_intercept": ci, "calibration_slope": cs},
        "attempt9": {"log_loss": _log_loss(bp, y), "brier": _brier(bp, y), "ece": _ece(bp, y), "calibration_intercept": bi, "calibration_slope": bs},
    }


def evaluate(dev_rows: list[dict[str, Any]], val_rows: list[dict[str, Any]], cfg: Mapping[str, Any]) -> dict[str, Any]:
    for r in dev_rows + val_rows:
        r["home_margin"] = float(r["home_score"] - r["away_score"])
        r["game_total"] = float(r["home_score"] + r["away_score"])
    min_dev = int(cfg["sample_requirements"]["minimum_development_games"])
    min_val = int(cfg["sample_requirements"]["minimum_validation_games"])
    if len(dev_rows) < min_dev:
        raise ValueError(f"NFL_ATTEMPT1_DEV_COVERAGE_INSUFFICIENT:{len(dev_rows)}:{min_dev}")
    if len(val_rows) < min_val:
        return {"status": "INSUFFICIENT_VALIDATION_SOURCE_COVERAGE", "pass": False, "n_development": len(dev_rows), "n_validation": len(val_rows), "minimum_validation": min_val, "attempt_spent": True, "authority": dict(ZERO_AUTHORITY)}

    grid = [float(x) for x in cfg["fit"]["ridge_alpha_grid"]]
    am, cvm = select_alpha(dev_rows, "margin", grid)
    at, cvt = select_alpha(dev_rows, "total", grid)

    mm = _fit_ridge(
        np.asarray([r["x_margin"] for r in dev_rows], dtype=float),
        np.asarray([r["home_margin"] - r["attempt9_margin"] for r in dev_rows], dtype=float),
        am,
    )
    mt = _fit_ridge(
        np.asarray([r["x_total"] for r in dev_rows], dtype=float),
        np.asarray([r["game_total"] - r["attempt9_total"] for r in dev_rows], dtype=float),
        at,
    )
    cm_sigma = oof_sigma(dev_rows, "margin", am)
    ct_sigma = oof_sigma(dev_rows, "total", at)
    bms = float(np.std([r["home_margin"] - r["attempt9_margin"] for r in dev_rows], ddof=1))
    bts = float(np.std([r["game_total"] - r["attempt9_total"] for r in dev_rows], ddof=1))

    pm = _predict(mm, np.asarray([r["x_margin"] for r in val_rows], dtype=float))
    pt = _predict(mt, np.asarray([r["x_total"] for r in val_rows], dtype=float))
    for i, row in enumerate(val_rows):
        row["candidate_margin"] = float(row["attempt9_margin"] + pm[i])
        row["candidate_total"] = float(row["attempt9_total"] + pt[i])

    spread = _market_metrics(
        val_rows,
        market="spread",
        candidate_key="candidate_margin",
        baseline_key="attempt9_margin",
        candidate_sigma=cm_sigma,
        baseline_sigma=bms,
    )
    total = _market_metrics(
        val_rows,
        market="total",
        candidate_key="candidate_total",
        baseline_key="attempt9_total",
        candidate_sigma=ct_sigma,
        baseline_sigma=bts,
    )
    min_market = int(cfg["sample_requirements"]["minimum_half_point_rows_per_market"])
    if spread["n"] < min_market or total["n"] < min_market:
        return {
            "status": "INSUFFICIENT_HALF_POINT_MARKET_ROWS",
            "pass": False,
            "attempt_spent": True,
            "n_development": len(dev_rows),
            "n_validation": len(val_rows),
            "spread": spread,
            "total": total,
            "authority": dict(ZERO_AUTHORITY),
        }

    rmse = {
        "margin_candidate": float(math.sqrt(np.mean([(r["candidate_margin"] - r["home_margin"]) ** 2 for r in val_rows]))),
        "margin_attempt9": float(math.sqrt(np.mean([(r["attempt9_margin"] - r["home_margin"]) ** 2 for r in val_rows]))),
        "total_candidate": float(math.sqrt(np.mean([(r["candidate_total"] - r["game_total"]) ** 2 for r in val_rows]))),
        "total_attempt9": float(math.sqrt(np.mean([(r["attempt9_total"] - r["game_total"]) ** 2 for r in val_rows]))),
    }
    pooled_candidate = (spread["candidate"]["log_loss"] + total["candidate"]["log_loss"]) / 2.0
    pooled_base = (spread["attempt9"]["log_loss"] + total["attempt9"]["log_loss"]) / 2.0
    g = cfg["validation_pass_rules"]
    market_regress_ok = (
        spread["candidate"]["log_loss"] - spread["attempt9"]["log_loss"] <= float(g["market_log_loss_max_regression"])
        and total["candidate"]["log_loss"] - total["attempt9"]["log_loss"] <= float(g["market_log_loss_max_regression"])
    )
    one_market_gain = max(
        spread["attempt9"]["log_loss"] - spread["candidate"]["log_loss"],
        total["attempt9"]["log_loss"] - total["candidate"]["log_loss"],
    ) >= float(g["at_least_one_market_log_loss_improvement_min"])
    cal_ok = all(
        float(g["calibration_slope_min"]) <= m["candidate"]["calibration_slope"] <= float(g["calibration_slope_max"])
        and abs(m["candidate"]["calibration_intercept"]) <= float(g["calibration_intercept_abs_max"])
        and m["candidate"]["ece"] <= float(g["ece_max"])
        for m in (spread, total)
    )
    passed = bool(
        pooled_candidate < pooled_base
        and market_regress_ok
        and one_market_gain
        and rmse["margin_candidate"] <= rmse["margin_attempt9"]
        and rmse["total_candidate"] <= rmse["total_attempt9"]
        and cal_ok
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "pass": passed,
        "attempt_spent": True,
        "n_development": len(dev_rows),
        "n_validation": len(val_rows),
        "selected_alpha": {"margin": am, "total": at},
        "cv_rmse_by_alpha": {"margin": cvm, "total": cvt},
        "sigma": {
            "candidate_margin_oof": cm_sigma,
            "candidate_total_oof": ct_sigma,
            "attempt9_margin_dev": bms,
            "attempt9_total_dev": bts,
        },
        "spread": spread,
        "total": total,
        "pooled_log_loss": {"candidate": pooled_candidate, "attempt9": pooled_base, "improvement": pooled_base - pooled_candidate},
        "rmse": rmse,
        "gates": {
            "pooled_log_loss_better": pooled_candidate < pooled_base,
            "market_regression_ok": market_regress_ok,
            "one_market_min_gain": one_market_gain,
            "rmse_not_worse": rmse["margin_candidate"] <= rmse["margin_attempt9"] and rmse["total_candidate"] <= rmse["total_attempt9"],
            "calibration": cal_ok,
        },
        "authority": dict(ZERO_AUTHORITY),
    }


def run() -> dict[str, Any]:
    prelock = json.loads(PRELOCK_PATH.read_text())
    cfg = json.loads(IMPL_PATH.read_text())
    if prelock.get("status") != "FROZEN_BEFORE_ATTEMPT1_SCORING" or int(prelock.get("attempt_number", -1)) != 1:
        raise ValueError("NFL_ATTEMPT1_PRELOCK_INVALID")
    if cfg.get("status") != "FROZEN_IMPLEMENTATION_BEFORE_2024_LOOK":
        raise ValueError("NFL_ATTEMPT1_IMPLEMENTATION_FREEZE_INVALID")

    attempt9 = reconstruct_attempt9(SOURCE_CONFIG)
    schedule, games_sha = load_schedule()
    dev_pbp, dev_pbp_sha = parse_pbp_seasons(range(2016, 2024))
    dev_depth, dev_depth_sha = parse_depth_seasons(range(2016, 2024))
    dev_rows = build_rows(schedule, dev_pbp, dev_depth, attempt9, set(range(2016, 2024)))
    dev_schedule = [g for g in schedule if 2016 <= g["season"] <= 2023]
    dev_pbp_matches = sum(1 for g in dev_schedule if g["game_id"] in dev_pbp)
    dev_depth_records = len(dev_depth)
    dev_depth_weekly_rows = sum(1 for row in dev_depth if row.get("week") not in (None, ""))
    dev_depth_timestamped_rows = sum(1 for row in dev_depth if row.get("dt") not in (None, ""))
    dev_both_starters = sum(
        1 for g in dev_schedule
        if starter_at(dev_depth, g["home"], g)
        and starter_at(dev_depth, g["away"], g)
    )
    print(json.dumps({
        "phase": "DEVELOPMENT_PREFLIGHT_ONLY_NO_2024_ACCESS",
        "schedule_games_2016_2023": len(dev_schedule),
        "pbp_complete_games": len(dev_pbp),
        "schedule_pbp_matches": dev_pbp_matches,
        "depth_rows": dev_depth_records,
        "depth_weekly_rows": dev_depth_weekly_rows,
        "depth_timestamped_rows": dev_depth_timestamped_rows,
        "games_with_both_pit_starters": dev_both_starters,
        "eligible_development_rows": len(dev_rows),
    }, sort_keys=True), flush=True)
    min_dev = int(cfg["sample_requirements"]["minimum_development_games"])
    if len(dev_rows) < min_dev:
        raise ValueError(f"NFL_ATTEMPT1_DEV_PREFLIGHT_INSUFFICIENT:{len(dev_rows)}:{min_dev}")

    val_pbp, val_pbp_sha = parse_pbp_seasons([2024])
    val_depth, val_depth_sha = parse_depth_seasons([2024])
    all_pbp = dict(dev_pbp)
    all_pbp.update(val_pbp)
    all_depth = [*dev_depth, *val_depth]

    rows = build_rows(schedule, all_pbp, all_depth, attempt9, set(range(2016, 2025)))
    dev_rows = [r for r in rows if 2016 <= r["season"] <= 2023]
    val_rows = [r for r in rows if r["season"] == 2024]
    result = evaluate(dev_rows, val_rows, cfg)
    receipt = {
        "schema": "SPORTSEDGE_NFL_PLAY_LEVEL_ATTEMPT1_ONE_SHOT_RESULT_V1",
        "attempt_id": prelock["attempt_id"],
        "validation_season": 2024,
        "validation_role": "EXPOSED_RESEARCH_VALIDATION_NOT_FRESH_PROMOTION_HOLDOUT",
        "implementation_sha256": sha256(IMPL_PATH.read_bytes()).hexdigest(),
        "prelock_sha256": sha256(PRELOCK_PATH.read_bytes()).hexdigest(),
        "feature_names": list(FEATURE_NAMES),
        "sources": {
            "games_csv_sha256": games_sha,
            "pbp_compressed_sha256": {**dev_pbp_sha, **val_pbp_sha},
            "depth_csv_sha256": {**dev_depth_sha, **val_depth_sha},
        },
        "result": result,
    }
    receipt["receipt_sha256"] = sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return receipt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    receipt = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
