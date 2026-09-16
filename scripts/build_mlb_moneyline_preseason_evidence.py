from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np

STATSAPI = "https://statsapi.mlb.com/api/v1/schedule"
MODEL_VERSION = "mlb_moneyline_preseason_market_blind_v1"
TRAIN_SEASONS = (2023, 2024)
CALIBRATION_SEASON = 2025
HOLDOUT_SEASON = 2026
FEATURE_NAMES = (
    "prior_win_pct_diff",
    "prior_pythagorean_diff",
    "prior_run_diff_per_game_diff",
    "prior_home_vs_away_split_diff",
)
CALIBRATION_SLOPE_MIN = 0.90
CALIBRATION_SLOPE_MAX = 1.10
CALIBRATION_INTERCEPT_ABS_MAX = 0.03
ECE_MAX = 0.025
MIN_HOLDOUT = 200


class EvidenceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Game:
    season: int
    game_pk: int
    start_utc: datetime
    home_team_id: int
    away_team_id: int
    home_runs: int
    away_runs: int


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_sha(value: Any) -> str:
    return _sha_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode())


def _utc(text: str) -> datetime:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise EvidenceError("timezone required")
    return dt.astimezone(timezone.utc)


def _month_ranges(year: int, end: date) -> Iterable[tuple[date, date]]:
    cur = date(year, 3, 1)
    hard_end = min(end, date(year, 11, 15))
    while cur <= hard_end:
        nxt = min(cur + timedelta(days=30), hard_end)
        yield cur, nxt
        cur = nxt + timedelta(days=1)


def _fetch_json(url: str) -> tuple[bytes, dict[str, Any]]:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge-MLB-PIT/1"})
    with urlopen(req, timeout=30) as resp:
        raw = resp.read()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise EvidenceError("StatsAPI response must be object")
    return raw, value


def acquire_season(season: int, *, end: date, cache_dir: Path) -> tuple[list[Game], list[dict[str, Any]]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    games: dict[int, Game] = {}
    receipts: list[dict[str, Any]] = []
    for start, stop in _month_ranges(season, end):
        params = urlencode({
            "sportId": 1,
            "gameTypes": "R",
            "startDate": start.isoformat(),
            "endDate": stop.isoformat(),
            "hydrate": "linescore",
        })
        url = f"{STATSAPI}?{params}"
        raw, payload = _fetch_json(url)
        cache_path = cache_dir / f"statsapi_schedule_{start.isoformat()}_{stop.isoformat()}.json"
        cache_path.write_bytes(raw)
        receipts.append({"url": url, "sha256": _sha_bytes(raw), "path": str(cache_path)})
        for day in payload.get("dates") or []:
            for row in day.get("games") or []:
                if str(row.get("gameType")) != "R":
                    continue
                status = row.get("status") or {}
                if str(status.get("abstractGameState")) != "Final":
                    continue
                teams = row.get("teams") or {}
                home = teams.get("home") or {}
                away = teams.get("away") or {}
                try:
                    game = Game(
                        season=season,
                        game_pk=int(row["gamePk"]),
                        start_utc=_utc(str(row["gameDate"])),
                        home_team_id=int((home.get("team") or {})["id"]),
                        away_team_id=int((away.get("team") or {})["id"]),
                        home_runs=int(home["score"]),
                        away_runs=int(away["score"]),
                    )
                except (KeyError, TypeError, ValueError):
                    continue
                if game.home_runs == game.away_runs:
                    continue
                games[game.game_pk] = game
    return sorted(games.values(), key=lambda g: (g.start_utc, g.game_pk)), receipts


def team_prior_stats(games: list[Game]) -> dict[int, dict[str, float]]:
    agg: dict[int, dict[str, float]] = {}
    def row(team_id: int) -> dict[str, float]:
        return agg.setdefault(team_id, {
            "games": 0.0, "wins": 0.0, "runs_for": 0.0, "runs_against": 0.0,
            "home_games": 0.0, "home_wins": 0.0, "away_games": 0.0, "away_wins": 0.0,
        })
    for g in games:
        h, a = row(g.home_team_id), row(g.away_team_id)
        h["games"] += 1; a["games"] += 1
        h["home_games"] += 1; a["away_games"] += 1
        h["runs_for"] += g.home_runs; h["runs_against"] += g.away_runs
        a["runs_for"] += g.away_runs; a["runs_against"] += g.home_runs
        if g.home_runs > g.away_runs:
            h["wins"] += 1; h["home_wins"] += 1
        else:
            a["wins"] += 1; a["away_wins"] += 1
    out: dict[int, dict[str, float]] = {}
    for team_id, x in agg.items():
        n = x["games"]
        if n < 100:
            continue
        rs, ra = x["runs_for"], x["runs_against"]
        pyth = (rs ** 1.83) / ((rs ** 1.83) + (ra ** 1.83)) if rs + ra > 0 else 0.5
        out[team_id] = {
            "win_pct": x["wins"] / n,
            "pythagorean": pyth,
            "run_diff_per_game": (rs - ra) / n,
            "home_win_pct": x["home_wins"] / x["home_games"] if x["home_games"] else 0.5,
            "away_win_pct": x["away_wins"] / x["away_games"] if x["away_games"] else 0.5,
            "games": n,
        }
    return out


def feature_freeze(season: int) -> datetime:
    return datetime(season, 1, 31, 12, 0, tzinfo=timezone.utc)


def build_examples(target_games: list[Game], prior_games: list[Game]) -> list[dict[str, Any]]:
    if not prior_games:
        raise EvidenceError("prior-season source games missing")
    freeze = feature_freeze(target_games[0].season if target_games else prior_games[0].season + 1)
    latest_source = max(g.start_utc for g in prior_games)
    if latest_source + timedelta(days=30) >= freeze:
        raise EvidenceError("prior-season source not separated from frozen feature timestamp by 30 days")
    stats = team_prior_stats(prior_games)
    rows = []
    for g in target_games:
        if freeze >= g.start_utc:
            raise EvidenceError(f"PIT_LEAKAGE feature_freeze={freeze.isoformat()} event={g.start_utc.isoformat()}")
        h, a = stats.get(g.home_team_id), stats.get(g.away_team_id)
        if h is None or a is None:
            continue
        features = [
            h["win_pct"] - a["win_pct"],
            h["pythagorean"] - a["pythagorean"],
            h["run_diff_per_game"] - a["run_diff_per_game"],
            h["home_win_pct"] - a["away_win_pct"],
        ]
        rows.append({
            "season": g.season,
            "game_pk": g.game_pk,
            "event_start_ts": g.start_utc.isoformat(),
            "feature_asof_ts": freeze.isoformat(),
            "home_team_id": g.home_team_id,
            "away_team_id": g.away_team_id,
            "home_win": 1 if g.home_runs > g.away_runs else 0,
            **{name: float(v) for name, v in zip(FEATURE_NAMES, features)},
        })
    return rows


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-x))


def fit_logistic(x: np.ndarray, y: np.ndarray, *, ridge: float = 1.0, max_iter: int = 100) -> np.ndarray:
    beta = np.zeros(x.shape[1], dtype=float)
    penalty = np.eye(x.shape[1]) * ridge
    penalty[0, 0] = 0.0
    for _ in range(max_iter):
        p = _sigmoid(x @ beta)
        w = np.clip(p * (1.0 - p), 1e-6, None)
        grad = x.T @ (y - p) - penalty @ beta
        h = x.T @ (w[:, None] * x) + penalty
        step = np.linalg.solve(h, grad)
        beta_new = beta + step
        if float(np.max(np.abs(beta_new - beta))) < 1e-10:
            beta = beta_new
            break
        beta = beta_new
    return beta


def matrix(rows: list[dict[str, Any]], mean: np.ndarray | None = None, sd: np.ndarray | None = None):
    raw = np.asarray([[r[name] for name in FEATURE_NAMES] for r in rows], dtype=float)
    if mean is None:
        mean = raw.mean(axis=0)
    if sd is None:
        sd = raw.std(axis=0)
        sd = np.where(sd < 1e-9, 1.0, sd)
    z = (raw - mean) / sd
    x = np.column_stack([np.ones(len(rows)), z])
    y = np.asarray([r["home_win"] for r in rows], dtype=float)
    return x, y, mean, sd


def calibration_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    eps = 1e-9
    p = np.clip(p, eps, 1.0 - eps)
    brier = float(np.mean((p - y) ** 2))
    log_loss = float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))
    logit = np.log(p / (1.0 - p))
    design = np.column_stack([np.ones(len(p)), logit])
    cal = fit_logistic(design, y, ridge=1e-8)
    order = np.argsort(p)
    bins = np.array_split(order, 10)
    ece = 0.0
    for idx in bins:
        if len(idx) == 0:
            continue
        ece += (len(idx) / len(p)) * abs(float(np.mean(p[idx])) - float(np.mean(y[idx])))
    return {
        "brier": brier,
        "log_loss": log_loss,
        "calibration_intercept": float(cal[0]),
        "calibration_slope": float(cal[1]),
        "ece_10_equal_frequency": float(ece),
    }


def write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise EvidenceError("pyarrow required for mandated parquet cache") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--holdout-cutoff", default="2026-09-15")
    parser.add_argument("--cache-dir", default="data/mlb_moneyline_preseason")
    parser.add_argument("--artifact-dir", default="artifacts/mlb_moneyline_preseason")
    args = parser.parse_args()
    cutoff = date.fromisoformat(args.holdout_cutoff)
    cache_dir = Path(args.cache_dir)
    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    seasons: dict[int, list[Game]] = {}
    all_receipts: list[dict[str, Any]] = []
    for season in range(2022, 2027):
        end = cutoff if season == HOLDOUT_SEASON else date(season, 11, 15)
        games, receipts = acquire_season(season, end=end, cache_dir=cache_dir / "raw" / str(season))
        if not games:
            raise EvidenceError(f"no completed regular-season games for {season}")
        seasons[season] = games
        all_receipts.extend(receipts)

    examples: dict[int, list[dict[str, Any]]] = {}
    for season in range(2023, 2027):
        examples[season] = build_examples(seasons[season], seasons[season - 1])

    train_rows = examples[2023] + examples[2024]
    cal_rows = examples[CALIBRATION_SEASON]
    hold_rows = examples[HOLDOUT_SEASON]
    if len(hold_rows) < MIN_HOLDOUT:
        raise EvidenceError(f"holdout sample {len(hold_rows)} < {MIN_HOLDOUT}")

    x_train, y_train, mean, sd = matrix(train_rows)
    beta = fit_logistic(x_train, y_train, ridge=1.0)
    x_cal, y_cal, _, _ = matrix(cal_rows, mean, sd)
    raw_cal_logit = x_cal @ beta
    calibrator = fit_logistic(np.column_stack([np.ones(len(cal_rows)), raw_cal_logit]), y_cal, ridge=1e-6)
    x_hold, y_hold, _, _ = matrix(hold_rows, mean, sd)
    raw_hold_logit = x_hold @ beta
    p_hold = _sigmoid(calibrator[0] + calibrator[1] * raw_hold_logit)
    for row, p in zip(hold_rows, p_hold):
        row["model_p_home"] = float(p)
        row["model_p_away"] = float(1.0 - p)

    metrics = calibration_metrics(y_hold, p_hold)
    calibration_pass = (
        CALIBRATION_SLOPE_MIN <= metrics["calibration_slope"] <= CALIBRATION_SLOPE_MAX
        and abs(metrics["calibration_intercept"]) <= CALIBRATION_INTERCEPT_ABS_MAX
        and metrics["ece_10_equal_frequency"] <= ECE_MAX
        and len(hold_rows) >= MIN_HOLDOUT
    )

    floor_cfg = json.loads(Path("config/truth_gate_floors.json").read_text())
    edge_floor = float(floor_cfg["truth_gate"]["edge_floors"]["MLB"]["moneyline"])
    if edge_floor <= 0:
        raise EvidenceError("MLB moneyline edge floor must be frozen and non-zero")
    deployment = json.loads(Path("config/deployments.json").read_text())["markets"]["MONEYLINE"]
    if deployment.get("eligible") is not False:
        raise EvidenceError("evidence build must run while MONEYLINE deployment remains fail-closed")

    model_artifact = {
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "market": "MONEYLINE",
        "market_blind": True,
        "forbidden_inputs": ["odds", "current_lines", "implied_probability", "public_betting", "consensus", "handicapper_opinion"],
        "training_seasons": list(TRAIN_SEASONS),
        "calibration_season": CALIBRATION_SEASON,
        "holdout_season": HOLDOUT_SEASON,
        "feature_names": list(FEATURE_NAMES),
        "feature_standardization_mean": mean.tolist(),
        "feature_standardization_sd": sd.tolist(),
        "raw_logistic_beta": beta.tolist(),
        "platt_calibrator": {"intercept": float(calibrator[0]), "slope": float(calibrator[1])},
        "pit_policy": "whole prior regular season only; fixed Jan-31 UTC freeze; >=30-day source-event embargo; feature_asof_ts < event_start_ts",
        "edge_floor": edge_floor,
        "source_receipts_sha256": _canonical_sha(all_receipts),
        "promotion_authority": False,
    }
    model_artifact["artifact_sha256"] = _canonical_sha(model_artifact)

    report = {
        "schema_version": 1,
        "market": "MONEYLINE",
        "model_artifact_sha256": model_artifact["artifact_sha256"],
        "holdout_cutoff": cutoff.isoformat(),
        "sample_size": len(hold_rows),
        "metrics": metrics,
        "calibration_thresholds": {
            "slope": [CALIBRATION_SLOPE_MIN, CALIBRATION_SLOPE_MAX],
            "intercept_abs_max": CALIBRATION_INTERCEPT_ABS_MAX,
            "ece_max": ECE_MAX,
            "min_sample": MIN_HOLDOUT,
        },
        "calibration_gate_pass": calibration_pass,
        "edge_floor": edge_floor,
        "clv_evidence_status": "MISSING_PAIRED_NO_VIG_CLOSES",
        "forward_evidence_status": "NOT_SATISFIED_BY_HISTORICAL_CALIBRATION",
        "truth_gate_complete": False,
        "deployment_eligible_after_this_artifact": False,
        "promotion_authority": False,
        "remaining_blockers": [
            "paired no-vig closing-price CLV evidence",
            "required forward evidence/sample under frozen policy",
            "fresh quote acquisition and identity binding",
            "production inference parity with this exact model artifact",
        ],
    }

    write_parquet(cache_dir / "schedule_final_games.parquet", [
        {
            "season": g.season, "game_pk": g.game_pk, "start_utc": g.start_utc.isoformat(),
            "home_team_id": g.home_team_id, "away_team_id": g.away_team_id,
            "home_runs": g.home_runs, "away_runs": g.away_runs,
        }
        for season in sorted(seasons) for g in seasons[season]
    ])
    write_parquet(cache_dir / "holdout_predictions.parquet", hold_rows)
    (artifact_dir / "model_artifact.json").write_text(json.dumps(model_artifact, indent=2, sort_keys=True) + "\n")
    (artifact_dir / "calibration_holdout_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    (artifact_dir / "source_receipts.json").write_text(json.dumps(all_receipts, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
