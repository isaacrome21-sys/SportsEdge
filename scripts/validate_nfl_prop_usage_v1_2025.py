#!/usr/bin/env python3
"""Consume the single frozen 2025 validation look for NFL prop usage V1.

This script is intentionally validation-only:
- loads the exact 2021-2024 fitted artifact from the frozen prior workflow artifact,
- uses only the preregistered 2025 REG validation season,
- uses DraftKings last pre-kick paired close rows from the pinned public tape,
- requires ACT weekly roster status and latest pre-kick depth evidence,
- applies the frozen normal residual probability layer and frozen baseline,
- evaluates only the preregistered calibration/Brier/lineup gates,
- does not refit, retune, change thresholds, create Model_P, or promote anything.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from math import erf, isfinite, sqrt
from pathlib import Path
import sys
import tempfile
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import pyreadr
import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fit_nfl_prop_usage_v1 import _build_attempt9_runtime
from sportsedge.research.nfl_prop_usage_v1_fit import (
    MARKETS,
    SCRIPT_REF,
    validate_artifact,
)

FIT_ARTIFACT_SHA256 = "ef38c7101da0977f27b71a7cbbe40321149ee2e0fda3bb8371f04d8423c9c555"
ATTEMPT9_ARTIFACT_SHA256 = "3ebce8f1ae0ec2efeffb4d145b898af9919d755a6028519ad98e41b5fb683ed0"
FIT_WORKFLOW_RUN_ID = 36962280655
FIT_WORKFLOW_ARTIFACT_ID = 11208336341
FIT_WORKFLOW_ARTIFACT_DIGEST = "sha256:4eb92be476a88b795f849e7f14d95258131e42c40f30dfce19d2bb373b613cf3"
VALIDATION_SEASON = 2025
MAX_CALIBRATION_GAP = 0.06
TARGET_MARKETS = {
    "player_pass_yds": "passing_yards",
    "player_rush_yds": "rushing_yards",
    "player_reception_yds": "receiving_yards",
}
DK_ALIASES = {"draftkings", "dk", "68"}
PROP_COMMIT = "d3fbfe1bece2f095e775f08d476cc5936ba37e13"
PROP_URLS = (
    "https://raw.githubusercontent.com/emets393/new-wagerproof/"
    f"{PROP_COMMIT}/research/nfl-extreme-outcomes/data/props_rows.parquet",
    "https://raw.githubusercontent.com/emets393/new-wagerproof/"
    f"{PROP_COMMIT}/research/nfl-extreme-outcomes/data/props_rows_extra.parquet",
)
GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
PLAYER_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats_2025.csv"
ROSTER_URL = "https://github.com/nflverse/nflverse-data/releases/download/weekly_rosters/roster_weekly_2025.csv"
DEPTH_URL = "https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_2025.rds"
USER_AGENT = "SportsEdge-NFL-prop-v1-validation/1.0"

TEAM_ALIASES = {
    "LAR": "LA",
    "STL": "LA",
    "WSH": "WAS",
    "OAK": "LV",
    "SD": "LAC",
}


class NflPropValidationError(ValueError):
    pass


def _team(value: Any) -> str:
    raw = str(value or "").strip().upper()
    return TEAM_ALIASES.get(raw, raw)


def _fetch(url: str) -> tuple[bytes, dict[str, Any]]:
    response = requests.get(
        url,
        timeout=180,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    raw = response.content
    if not raw:
        raise NflPropValidationError(f"SOURCE_EMPTY:{url}")
    return raw, {
        "url": url,
        "bytes": len(raw),
        "sha256": sha256(raw).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def _csv(raw: bytes) -> list[dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows:
        raise NflPropValidationError("CSV_EMPTY")
    return rows


def _f(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise NflPropValidationError(f"{field}:NUMERIC_REQUIRED") from exc
    if not isfinite(out):
        raise NflPropValidationError(f"{field}:FINITE_REQUIRED")
    return out


def _weighted(values: Sequence[float], decay: float) -> float:
    if not values:
        raise NflPropValidationError("WEIGHTED_VALUES_EMPTY")
    arr = np.asarray(values, dtype=float)
    weights = float(decay) ** np.arange(len(arr) - 1, -1, -1)
    return float(np.average(arr, weights=weights))


def _runtime_target(runtime: Mapping[str, Any], target: str, features: Sequence[float]) -> float:
    row = runtime["runtime"]["targets"][target]
    x = np.asarray(features, dtype=float)
    mean = np.asarray(row["feature_mean"], dtype=float)
    std = np.asarray(row["feature_std"], dtype=float)
    coef = np.asarray(row["coefficients"], dtype=float)
    return float(((x - mean) / std) @ coef + float(row["intercept"]))


def build_attempt9_2025_environment(
    games: Sequence[Mapping[str, Any]], runtime: Mapping[str, Any]
) -> dict[tuple[int, int, str], float]:
    """Same chronological Attempt-9 environment as the frozen fit, now for 2025."""
    normalized: list[dict[str, Any]] = []
    for raw in games:
        try:
            season = int(float(str(raw.get("season") or "")))
            week = int(float(str(raw.get("week") or "")))
        except (TypeError, ValueError):
            continue
        if str(raw.get("game_type") or "").upper() != "REG":
            continue
        home = _team(raw.get("home_team"))
        away = _team(raw.get("away_team"))
        if not home or not away:
            continue
        hs = raw.get("home_score")
        aw = raw.get("away_score")
        normalized.append({
            "season": season,
            "week": week,
            "date": str(raw.get("gameday") or ""),
            "id": str(raw.get("game_id") or f"{season}_{week}_{away}_{home}"),
            "home": home,
            "away": away,
            "hs": None if hs in (None, "") else float(hs),
            "as": None if aw in (None, "") else float(aw),
        })
    normalized.sort(key=lambda g: (g["date"], g["id"]))

    history: dict[str, list[tuple[float, float]]] = defaultdict(list)
    out: dict[tuple[int, int, str], float] = {}
    current_date: str | None = None
    batch: list[dict[str, Any]] = []

    def flush(rows: list[dict[str, Any]]) -> None:
        for game in rows:
            if game["season"] == VALIDATION_SEASON and len(history[game["home"]]) >= 5 and len(history[game["away"]]) >= 5:
                hp_hist = history[game["home"]][-10:]
                ap_hist = history[game["away"]][-10:]
                hp_for = _weighted([x[0] for x in hp_hist], 0.85)
                hp_against = _weighted([x[1] for x in hp_hist], 0.85)
                ap_for = _weighted([x[0] for x in ap_hist], 0.85)
                ap_against = _weighted([x[1] for x in ap_hist], 0.85)
                features = [
                    hp_for, hp_against, ap_for, ap_against,
                    hp_for - hp_against, ap_for - ap_against,
                ]
                margin = _runtime_target(runtime, "margin", features)
                total = _runtime_target(runtime, "total", features)
                out[(VALIDATION_SEASON, game["week"], game["home"])] = (total + margin) / 2.0
                out[(VALIDATION_SEASON, game["week"], game["away"])] = (total - margin) / 2.0
        for game in rows:
            if game["hs"] is None or game["as"] is None:
                continue
            history[game["home"]].append((game["hs"], game["as"]))
            history[game["away"]].append((game["as"], game["hs"]))

    for game in normalized:
        if current_date is None:
            current_date = game["date"]
        if game["date"] != current_date:
            flush(batch)
            batch = []
            current_date = game["date"]
        batch.append(game)
    if batch:
        flush(batch)
    return out


def normalize_2025_player_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out = []
    required = {
        "season", "week", "season_type", "player_id", "position",
        "attempts", "passing_yards", "carries", "rushing_yards",
        "targets", "receiving_yards",
    }
    for raw in rows:
        if required - set(raw):
            continue
        try:
            season = int(float(str(raw.get("season") or "")))
            week = int(float(str(raw.get("week") or "")))
        except (TypeError, ValueError):
            continue
        if season != VALIDATION_SEASON or str(raw.get("season_type") or "").upper() != "REG":
            continue
        pid = str(raw.get("player_id") or "").strip()
        pos = str(raw.get("position") or "").strip().upper()
        team = _team(raw.get("team") or raw.get("recent_team"))
        if not pid or not pos or not team:
            continue
        def n(key: str) -> float:
            raw_v = raw.get(key)
            if raw_v in (None, ""):
                return 0.0
            try:
                v = float(raw_v)
            except (TypeError, ValueError):
                return 0.0
            return v if isfinite(v) else 0.0
        out.append({
            "season": season,
            "week": week,
            "player_id": pid,
            "player": str(raw.get("player_display_name") or raw.get("player_name") or pid).strip(),
            "position": pos,
            "team": team,
            "attempts": max(0.0, n("attempts")),
            "passing_yards": n("passing_yards"),
            "carries": max(0.0, n("carries")),
            "rushing_yards": n("rushing_yards"),
            "targets": max(0.0, n("targets")),
            "receiving_yards": n("receiving_yards"),
        })
    return sorted(out, key=lambda r: (r["week"], r["player_id"]))


def build_predictions(
    rows: Sequence[Mapping[str, Any]],
    env: Mapping[tuple[int, int, str], float],
    artifact: Mapping[str, Any],
) -> dict[tuple[int, str, str], dict[str, Any]]:
    histories: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    out: dict[tuple[int, str, str], dict[str, Any]] = {}
    for row in rows:
        pid = str(row["player_id"])
        hist = histories[pid]
        for market, spec in MARKETS.items():
            if row["position"] not in spec["positions"]:
                continue
            params = artifact["markets"][market]["selected"]
            if len(hist) < 3:
                continue
            team_key = (VALIDATION_SEASON, int(row["week"]), row["team"])
            if team_key not in env:
                continue
            sample = hist[-int(params["history_games"]):]
            usage = _weighted([float(x[spec["usage"]]) for x in sample], float(params["decay"]))
            weights = float(params["decay"]) ** np.arange(len(sample) - 1, -1, -1)
            opp = np.asarray([float(x[spec["usage"]]) for x in sample], dtype=float)
            yards = np.asarray([float(x[spec["yards"]]) for x in sample], dtype=float)
            weighted_opp = float(np.sum(weights * opp))
            weighted_yards = float(np.sum(weights * yards))
            prior = artifact["markets"][market]["efficiency_prior_by_position"].get(row["position"])
            if prior is None:
                continue
            prior_n = float(params["efficiency_prior_opportunities"])
            efficiency = (weighted_yards + prior_n * float(prior)) / (weighted_opp + prior_n)
            team_points = float(env[team_key])
            if team_points <= 0:
                continue
            script = (team_points / SCRIPT_REF) ** float(params["script_gamma"])
            prediction = usage * efficiency * script
            out[(int(row["week"]), pid, market)] = {
                "prediction": float(prediction),
                "actual": float(row[spec["yards"]]),
                "position": row["position"],
                "team": row["team"],
                "player": row["player"],
                "usage": float(usage),
                "efficiency": float(efficiency),
                "attempt9_team_points": team_points,
            }
        hist.append(row)
    return out


def normal_over_probability(mean: float, sigma: float, line: float) -> float:
    if sigma <= 0:
        raise NflPropValidationError("SIGMA_NONPOSITIVE")
    z = (line - mean) / (sigma * sqrt(2.0))
    p = 0.5 * (1.0 - erf(z))
    return min(1.0, max(0.0, float(p)))


def load_prop_closes(raws: Sequence[bytes]) -> pd.DataFrame:
    frames = [pd.read_parquet(io.BytesIO(raw)) for raw in raws]
    props = pd.concat(frames, ignore_index=True, sort=False)
    required = {
        "season", "week", "event_id", "player_id", "market", "line",
        "over_odds", "under_odds", "commence_time", "snapshot_time",
    }
    missing = required - set(props.columns)
    if missing:
        raise NflPropValidationError("PROP_COLUMNS_MISSING:" + ",".join(sorted(missing)))
    props = props[pd.to_numeric(props["season"], errors="coerce").eq(VALIDATION_SEASON)].copy()
    props["market"] = props["market"].astype("string").fillna("").str.strip().str.lower()
    props = props[props["market"].isin(TARGET_MARKETS)].copy()
    book_col = next((c for c in ("bookmaker", "book", "book_id") if c in props.columns), None)
    if not book_col:
        raise NflPropValidationError("PROP_BOOK_COLUMN_MISSING")
    props["book_norm"] = props[book_col].astype("string").fillna("").str.strip().str.lower()
    props = props[props["book_norm"].isin(DK_ALIASES)].copy()
    props["snapshot_time"] = pd.to_datetime(props["snapshot_time"], utc=True, errors="coerce")
    props["commence_time"] = pd.to_datetime(props["commence_time"], utc=True, errors="coerce")
    props["lead_seconds"] = (props["commence_time"] - props["snapshot_time"]).dt.total_seconds()
    props = props[
        props["snapshot_time"].notna()
        & props["commence_time"].notna()
        & props["lead_seconds"].gt(0)
        & props["line"].notna()
        & props["over_odds"].notna()
        & props["under_odds"].notna()
    ].copy()
    identity = ["event_id", "player_id", "market", "book_norm"]
    props = props.sort_values(identity + ["snapshot_time"]).drop_duplicates(identity, keep="last")
    if props.duplicated(identity, keep=False).any():
        raise NflPropValidationError("PROP_CLOSE_IDENTITY_DUPLICATE")
    return props


def load_active_roster(raw: bytes) -> set[tuple[int, str]]:
    df = pd.read_csv(io.BytesIO(raw), low_memory=False)
    if not {"week", "gsis_id", "status"}.issubset(df.columns):
        raise NflPropValidationError("ROSTER_COLUMNS_MISSING")
    week = pd.to_numeric(df["week"], errors="coerce")
    status = df["status"].astype("string").fillna("").str.upper().str.strip()
    gsis = df["gsis_id"].astype("string").fillna("").str.strip()
    mask = week.notna() & gsis.ne("") & status.eq("ACT")
    return {(int(w), p) for w, p in zip(week[mask], gsis[mask])}


def load_depth_snapshots(raw: bytes, temp_dir: Path):
    path = temp_dir / "depth_charts_2025.rds"
    path.write_bytes(raw)
    result = pyreadr.read_r(str(path))
    if not result:
        raise NflPropValidationError("DEPTH_RDS_EMPTY")
    df = next(iter(result.values())).copy()
    required = {"dt", "gsis_id", "team", "pos_abb", "pos_rank"}
    if not required.issubset(df.columns):
        raise NflPropValidationError("DEPTH_COLUMNS_MISSING")
    df["dt"] = pd.to_datetime(df["dt"], utc=True, errors="coerce")
    df["team_norm"] = df["team"].map(_team)
    df["gsis_norm"] = df["gsis_id"].astype("string").fillna("").str.strip()
    df["pos_norm"] = df["pos_abb"].astype("string").fillna("").str.upper().str.strip()
    df["rank_num"] = pd.to_numeric(df["pos_rank"], errors="coerce")
    df = df[df["dt"].notna() & df["team_norm"].ne("") & df["gsis_norm"].ne("")].copy()

    by_team: dict[str, dict[str, Any]] = {}
    for team, team_df in df.groupby("team_norm", sort=True):
        snapshots = []
        for stamp, snap in team_df.groupby("dt", sort=True):
            players = set(snap["gsis_norm"])
            qb1 = set(snap.loc[snap["pos_norm"].eq("QB") & snap["rank_num"].eq(1), "gsis_norm"])
            snapshots.append((stamp.to_pydatetime(), players, qb1))
        by_team[str(team)] = {
            "times": [x[0] for x in snapshots],
            "snapshots": snapshots,
        }
    return by_team


def depth_allows(
    depth_index: Mapping[str, Any],
    *,
    team: str,
    player_id: str,
    position: str,
    kickoff: datetime,
) -> tuple[bool, str | None]:
    row = depth_index.get(_team(team))
    if not row:
        return False, "DEPTH_TEAM_MISSING"
    times = row["times"]
    idx = bisect_right(times, kickoff) - 1
    if idx < 0:
        return False, "DEPTH_PREKICK_SNAPSHOT_MISSING"
    stamp, players, qb1 = row["snapshots"][idx]
    if position == "QB":
        return (player_id in qb1, None if player_id in qb1 else "QB_NOT_RANK1_PREKICK")
    return (player_id in players, None if player_id in players else "PLAYER_NOT_IN_PREKICK_DEPTH")


def evaluate_rows(
    closes: pd.DataFrame,
    predictions: Mapping[tuple[int, str, str], Mapping[str, Any]],
    artifact: Mapping[str, Any],
    active_roster: set[tuple[int, str]],
    depth_index: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    drops = Counter()
    for raw in closes.to_dict("records"):
        try:
            week = int(float(raw["week"]))
            pid = str(raw["player_id"]).strip()
            provider_market = str(raw["market"])
            market = TARGET_MARKETS[provider_market]
            line = float(raw["line"])
            kickoff = pd.Timestamp(raw["commence_time"]).to_pydatetime()
        except Exception:
            drops["identity_or_line_invalid"] += 1
            continue
        if line == int(line):
            drops["integer_line_fail_closed"] += 1
            continue
        key = (week, pid, market)
        pred = predictions.get(key)
        if pred is None:
            drops["model_prediction_unavailable"] += 1
            continue
        if (week, pid) not in active_roster:
            drops["weekly_roster_not_act_or_missing"] += 1
            continue
        allowed, reason = depth_allows(
            depth_index,
            team=str(pred["team"]),
            player_id=pid,
            position=str(pred["position"]),
            kickoff=kickoff,
        )
        if not allowed:
            drops[str(reason or "depth_rejected")] += 1
            continue

        m = artifact["markets"][market]
        sigma = m["oof_residual_sigma_by_position"].get(pred["position"], m["oof_residual_sigma_pooled"])
        model_p = normal_over_probability(float(pred["prediction"]), float(sigma), line)
        baseline = m["baseline_actual_distribution_by_position"].get(pred["position"])
        if not baseline:
            drops["baseline_distribution_missing"] += 1
            continue
        baseline_p = normal_over_probability(float(baseline["mean"]), float(baseline["sd"]), line)
        actual = float(pred["actual"])
        if actual == line:
            drops["actual_push_fail_closed"] += 1
            continue
        y = 1 if actual > line else 0
        rows.append({
            "event_id": str(raw["event_id"]),
            "week": week,
            "player_id": pid,
            "player_name": str(pred["player"]),
            "position": str(pred["position"]),
            "team": str(pred["team"]),
            "provider_market": provider_market,
            "market": market,
            "line": line,
            "kickoff": kickoff.astimezone(timezone.utc).isoformat(),
            "close_snapshot_time": pd.Timestamp(raw["snapshot_time"]).to_pydatetime().astimezone(timezone.utc).isoformat(),
            "prediction": float(pred["prediction"]),
            "actual": actual,
            "model_p_over": model_p,
            "baseline_p_over": baseline_p,
            "observed_over": y,
            "squared_error": (model_p - y) ** 2,
            "baseline_squared_error": (baseline_p - y) ** 2,
        })
    return rows, dict(sorted(drops.items()))


def scope_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "n": 0,
            "mean_model_p_over": None,
            "observed_over_rate": None,
            "calibration_gap": None,
            "candidate_brier": None,
            "baseline_brier": None,
        }
    n = len(rows)
    mean_p = sum(float(r["model_p_over"]) for r in rows) / n
    observed = sum(int(r["observed_over"]) for r in rows) / n
    return {
        "n": n,
        "mean_model_p_over": mean_p,
        "observed_over_rate": observed,
        "calibration_gap": abs(mean_p - observed),
        "candidate_brier": sum(float(r["squared_error"]) for r in rows) / n,
        "baseline_brier": sum(float(r["baseline_squared_error"]) for r in rows) / n,
    }


def run_validation(*, fit_artifact_path: Path, out_path: Path, rows_path: Path) -> dict[str, Any]:
    artifact = json.loads(fit_artifact_path.read_text())
    validate_artifact(artifact)
    if artifact["artifact_sha256"] != FIT_ARTIFACT_SHA256:
        raise NflPropValidationError("FROZEN_FIT_ARTIFACT_SHA_MISMATCH")
    if artifact["attempt9_artifact_sha256"] != ATTEMPT9_ARTIFACT_SHA256:
        raise NflPropValidationError("FROZEN_ATTEMPT9_ARTIFACT_SHA_MISMATCH")
    if artifact.get("validation_season_accessed") is not False:
        raise NflPropValidationError("VALIDATION_WINDOW_ALREADY_SPENT")

    receipts: dict[str, Any] = {}
    prop_raws = []
    for i, url in enumerate(PROP_URLS, start=1):
        raw, receipt = _fetch(url)
        prop_raws.append(raw)
        receipts[f"prop_tape_{i}"] = receipt
    games_raw, receipts["games"] = _fetch(GAMES_URL)
    players_raw, receipts["player_stats_2025"] = _fetch(PLAYER_URL)
    roster_raw, receipts["weekly_rosters_2025"] = _fetch(ROSTER_URL)
    depth_raw, receipts["depth_charts_2025"] = _fetch(DEPTH_URL)

    with tempfile.TemporaryDirectory(prefix="sportsedge-nfl-prop-v1-validation-") as tmp:
        runtime = _build_attempt9_runtime(Path(tmp))
        if runtime["artifact_sha256"] != ATTEMPT9_ARTIFACT_SHA256:
            raise NflPropValidationError("ATTEMPT9_RUNTIME_RECONSTRUCTION_MISMATCH")
        env = build_attempt9_2025_environment(_csv(games_raw), runtime)
        player_rows = normalize_2025_player_rows(_csv(players_raw))
        predictions = build_predictions(player_rows, env, artifact)
        closes = load_prop_closes(prop_raws)
        active = load_active_roster(roster_raw)
        depth = load_depth_snapshots(depth_raw, Path(tmp))
        rows, drops = evaluate_rows(closes, predictions, artifact, active, depth)

    by_market = {
        market: scope_metrics([r for r in rows if r["market"] == market])
        for market in ("passing_yards", "rushing_yards", "receiving_yards")
    }
    pooled = scope_metrics(rows)
    calibration_pass = all(
        by_market[m]["n"] > 0
        and by_market[m]["calibration_gap"] is not None
        and float(by_market[m]["calibration_gap"]) <= MAX_CALIBRATION_GAP
        for m in by_market
    ) and (
        pooled["n"] > 0
        and pooled["calibration_gap"] is not None
        and float(pooled["calibration_gap"]) <= MAX_CALIBRATION_GAP
    )
    brier_pass = (
        pooled["candidate_brier"] is not None
        and pooled["baseline_brier"] is not None
        and float(pooled["candidate_brier"]) <= float(pooled["baseline_brier"])
    )
    lineup_gate_pass = True  # evaluator emits only ACT + admissible latest-prekick depth rows
    verdict = "PASS_RESEARCH_ELIGIBLE_FOR_SEPARATE_PROMOTION_PR" if (
        calibration_pass and brier_pass and lineup_gate_pass
    ) else "FAIL_RESEARCH_WINDOW_SPENT"

    rows_digest = sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    report = {
        "schema": "SPORTSEDGE_NFL_PROP_USAGE_V1_2025_ONE_LOOK_V1",
        "status": verdict,
        "validation_season": VALIDATION_SEASON,
        "validation_window_spent": True,
        "second_look_allowed": False,
        "post_result_retune_allowed": False,
        "fit_binding": {
            "workflow_run_id": FIT_WORKFLOW_RUN_ID,
            "workflow_artifact_id": FIT_WORKFLOW_ARTIFACT_ID,
            "workflow_artifact_digest": FIT_WORKFLOW_ARTIFACT_DIGEST,
            "fit_artifact_sha256": FIT_ARTIFACT_SHA256,
            "attempt9_artifact_sha256": ATTEMPT9_ARTIFACT_SHA256,
        },
        "source_receipts": receipts,
        "row_count": len(rows),
        "rows_sha256": rows_digest,
        "drops": drops,
        "scopes": {
            **by_market,
            "pooled": pooled,
        },
        "gates": {
            "calibration_max_gap": MAX_CALIBRATION_GAP,
            "calibration_pass": calibration_pass,
            "brier_rule": "CANDIDATE_POOLED_BRIER_LE_BASELINE_POOLED_BRIER",
            "brier_pass": brier_pass,
            "lineup_gate": "ACT_WEEKLY_ROSTER_AND_LATEST_PREKICK_DEPTH",
            "lineup_gate_pass": lineup_gate_pass,
        },
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "truth_gate": False,
            "official": False,
            "promotion": False,
            "staking": False,
            "backfill": False,
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    rows_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n")
    print("NFL_PROP_USAGE_V1_2025_ONE_LOOK=" + json.dumps(report, sort_keys=True))
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-artifact", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("artifacts/nfl_prop_usage_v1/validation_2025.json"))
    ap.add_argument("--rows-out", type=Path, default=Path("artifacts/nfl_prop_usage_v1/validation_2025_rows.json"))
    args = ap.parse_args()
    run_validation(
        fit_artifact_path=args.fit_artifact,
        out_path=args.out,
        rows_path=args.rows_out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
