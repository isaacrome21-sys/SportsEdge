#!/usr/bin/env python3
"""NFL Attempt 3: point-in-time EPA efficiency versus the closing market."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from collections import defaultdict
from datetime import date
from itertools import groupby
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

import fit_football_baselines as base

PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{season}.parquet"


def fetch(url: str) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "SportsEdge-research-fit/1.0"}), timeout=180) as response:
        return response.read()


def epa_game_stats(seasons: set[int]) -> tuple[dict[tuple[str, str], dict[str, float]], str]:
    stats: dict[tuple[str, str], dict[str, float]] = {}
    hashes = []
    for season in sorted(seasons):
        raw = fetch(PBP_URL.format(season=season))
        hashes.append(raw)
        frame = pd.read_parquet(io.BytesIO(raw), columns=[
            "game_id", "posteam", "defteam", "epa", "play_type", "season_type",
            "pass", "rush"
        ])
        frame = frame[frame["season_type"].isin(["REG", "POST"])]
        frame = frame[frame["posteam"].notna() & frame["defteam"].notna() & frame["epa"].notna()]
        frame = frame[frame["play_type"].isin(["pass", "run", "qb_kneel", "qb_spike"])]
        if frame.empty:
            continue
        frame["pass_epa"] = frame["epa"].where(frame["pass"].eq(1))
        frame["rush_epa"] = frame["epa"].where(frame["rush"].eq(1))
        grouped = frame.groupby(["game_id", "posteam", "defteam"], sort=False)
        for (game_id, posteam, defteam), g in grouped:
            def avg(column: str) -> float:
                values = g[column].dropna()
                return float(values.mean()) if len(values) else 0.0
            stats[(str(game_id), str(posteam))] = {
                "off_epa": avg("epa"),
                "pass_epa": avg("pass_epa"),
                "rush_epa": avg("rush_epa"),
                "defteam": str(defteam),
                "plays": float(len(g)),
            }
    return stats, hashlib.sha256(b"".join(hashes)).hexdigest()


def add_epa_stats(games: list[dict], stats: dict[tuple[str, str], dict[str, float]]) -> list[dict]:
    enriched = []
    for game in games:
        key = str(game["id"])
        home = stats.get((key, str(game["home"])))
        away = stats.get((key, str(game["away"])))
        if not home or not away:
            continue
        enriched.append({**game, "home_epa": home, "away_epa": away})
    return enriched


def epa_features(games: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], list[str], list[tuple[str, str, dict]]]:
    ordered = sorted(games, key=lambda x: (x["date"], x["id"]))
    history = defaultdict(list)
    names = [
        "home_off_epa", "home_def_epa", "home_pass_epa", "home_rush_epa",
        "away_off_epa", "away_def_epa", "away_pass_epa", "away_rush_epa",
    ]
    X, ym, yt, dates, keys = [], [], [], [], []
    for game_date, group in groupby(ordered, key=lambda x: x["date"]):
        batch = list(group)
        for g in batch:
            h, a = g["home"], g["away"]
            if len(history[h]) < 3 or len(history[a]) < 3:
                continue
            def recent(team: str) -> np.ndarray:
                return np.mean(np.asarray(history[team][-10:], dtype=float), axis=0)
            hp, ap = recent(h), recent(a)
            X.append([hp[0], hp[1], hp[2], hp[3], ap[0], ap[1], ap[2], ap[3]])
            ym.append(g["hs"] - g["as"])
            yt.append(g["hs"] + g["as"])
            dates.append(game_date)
            keys.append((game_date, str(g["id"]), g))
        for g in batch:
            home, away = g["home_epa"], g["away_epa"]
            # Defensive EPA is the opponent's offensive EPA in this game:
            # lower allowed EPA is better. Append only after all same-date
            # rows were emitted so no game can see its own result.
            history[g["home"]].append([home["off_epa"], away["off_epa"], home["pass_epa"], home["rush_epa"]])
            history[g["away"]].append([away["off_epa"], home["off_epa"], away["pass_epa"], away["rush_epa"]])
    return np.asarray(X, float), np.asarray(ym, float), np.asarray(yt, float), names, dates, keys


def benchmark(reports, games, dates, keys, hold_start, hold_end, target):
    target_keys = {(d, k) for d, k, _ in keys if hold_start <= int(d[:4]) <= hold_end}
    rows = {(str(g["date"]), str(g["id"])): g for g in games}
    selected = [rows[k] for k in sorted(target_keys) if k in rows]
    model = np.asarray(reports["holdout_predictions"], float)
    if len(model) != len(selected):
        raise RuntimeError(f"EPA_BENCHMARK_ALIGNMENT_FAILED:{target}:model={len(model)}:rows={len(selected)}")
    field = "spread_line" if target == "margin" else "total_line"
    market = np.asarray([g.get(field) for g in selected], object)
    actual = np.asarray([g["hs"] - g["as"] if target == "margin" else g["hs"] + g["as"] for g in selected], float)
    valid = np.asarray([v is not None for v in market])
    market = market[valid].astype(float)
    actual = actual[valid]
    model = model[valid]
    result = {
        "n_holdout": int(valid.sum()),
        "rmse": float(np.sqrt(np.mean((market - actual) ** 2))),
        "source_field": field,
        "comparison": "MODEL_VS_CLOSING_LINE_REPORTED_ONLY",
        "paired_rmse_bootstrap": base.bootstrap_rmse_delta(model, market, actual),
    }
    if target == "margin":
        result["spread_line_home_margin_correlation"] = float(np.corrcoef(market, actual)[0, 1])
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2010,2011,2012,2013,2014,2015,2016,2017,2018,2019")
    ap.add_argument("--policy", default="config/nfl_research_search_policy_v1.json")
    ap.add_argument("--out", default="artifacts/football_baselines_attempt3.json")
    args = ap.parse_args()
    policy_path = Path(args.policy)
    policy = json.loads(policy_path.read_text())
    hold_start, hold_end = policy["immediate_holdout_range"]
    training = policy["training_seasons_for_immediate_holdout"]
    train_start, train_end = map(int, training.split("-"))
    seasons = {int(s) for s in args.seasons.split(",") if s.strip()}
    required = set(range(train_start, hold_end + 1))
    if not required.issubset(seasons):
        raise RuntimeError(f"SEASONS_OMIT_POLICY_WINDOW:{sorted(required - seasons)}")
    games, game_sha, _ = base.nfl(seasons)
    games = [g for g in games if g["date"][:4].isdigit() and int(g["date"][:4]) <= hold_end]
    epa, epa_sha = epa_game_stats(seasons)
    enriched = add_epa_stats(games, epa)
    if len(enriched) < 200:
        raise RuntimeError(f"EPA_INSUFFICIENT_ENRICHED_GAMES:{len(enriched)}")
    X, ym, yt, names, dates, keys = epa_features(enriched)
    if len(X) < 200:
        raise RuntimeError(f"EPA_INSUFFICIENT_FEATURE_ROWS:{len(X)}")
    base.feature_names, base.hold_dates = names, dates
    targets = {
        "margin": base.run_target(X, ym, hold_start, hold_end, close_threshold=7),
        "total": base.run_target(X, yt, hold_start, hold_end),
    }
    X0, ym0, yt0, names0, dates0 = base.features(games, "baseline")
    base.feature_names, base.hold_dates = names0, dates0
    control = {
        "budget_counted": False,
        "reason": "pre_registered_control_calibration",
        "targets": {
            "margin": base.run_target(X0, ym0, hold_start, hold_end, close_threshold=7),
            "total": base.run_target(X0, yt0, hold_start, hold_end),
        },
    }
    report = {
        "schema": "NFL_EPA_ATTEMPT3_V1",
        "source": PBP_URL,
        "games_source_sha256": game_sha,
        "epa_source_sha256": epa_sha,
        "policy_path": str(policy_path),
        "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
        "training_years": [train_start, train_end],
        "holdout_years": [hold_start, hold_end],
        "feature_set": "epa_efficiency",
        "feature_names": names,
        "enriched_games": len(enriched),
        "usable_rows": len(X),
        "status": "RESEARCH_ONLY_NOT_MODEL_P",
        "targets": targets,
        "control_baseline_same_holdout": control,
        "closing_line_benchmark": {
            "margin": benchmark(targets["margin"], enriched, dates, keys, hold_start, hold_end, "margin"),
            "total": benchmark(targets["total"], enriched, dates, keys, hold_start, hold_end, "total"),
        },
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
