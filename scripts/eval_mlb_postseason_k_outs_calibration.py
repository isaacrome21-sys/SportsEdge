#!/usr/bin/env python3
"""MLB postseason K/outs calibration, chronological holdouts, research only.

Historical predictions and settlements come from the already-executed official
2023-25 postseason workload archive (workflow run 37707010690). Source bytes
are hash-locked. One log-odds intercept per market/model, fitted on earlier
postseason seasons only, is tested out of sample on 2024 and 2025.

This compares *context-blind* pregame regular-season marginals, not the full
opponent/lineup-adjusted live model. No live pricing is changed and no result
is authorization to publish a pitcher prop.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from math import exp, isfinite, log
from pathlib import Path
from random import Random
from statistics import mean
from typing import Any, Mapping, Sequence

ARCHIVE_SHA256 = "701d6d2bbac53f35f09bf2e292bafd58710b7cf1d1e333fc558f91c68bfb3c2d"
SOURCE_VERSION = "mlb_postseason_starter_workload_audit_2023_2025_v1"
REPORT_VERSION = "mlb_postseason_k_outs_temporal_calibration_v1"
MARKET_LINES = {
    "PITCHER_K": (2.5, 4.5),
    "PITCHER_OUTS": (12.5, 15.5, 17.5),
}
PROBABILITY_SOURCES = ("p_recent_only", "p_recent_plus_capped_prior")
CHRONOLOGICAL_FOLDS = ((2024, (2023,)), (2025, (2023, 2024)))
BOOTSTRAP_DRAWS = 1000


def read_locked_archive(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    digest = sha256(raw).hexdigest()
    if digest != ARCHIVE_SHA256:
        raise ValueError(f"Historical audit bytes mismatch: {digest}")
    payload = json.loads(raw)
    if payload.get("version") != SOURCE_VERSION:
        raise ValueError("Unexpected historical workload archive version")
    if payload.get("frozen_seasons") != [2023, 2024, 2025]:
        raise ValueError("Historical postseason seasons mismatch")
    if payload.get("official_postseason_game_count") != 131:
        raise ValueError("Historical official game coverage mismatch")
    if payload.get("evaluable_starters") != 237:
        raise ValueError("Historical regular-season history coverage mismatch")
    return payload


def extract_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str, float]] = set()
    for start in payload["starts"]:
        if start["history_status"] != "EVALUATED":
            if start.get("records"):
                raise ValueError("Excluded starter has pricing rows")
            continue
        game_pk, pitcher_id = int(start["game_pk"]), int(start["player_id"])
        year = int(str(start["date"])[:4])
        if year not in (2023, 2024, 2025):
            raise ValueError("Unexpected postseason outcome season")
        history = list(start["records"])
        if len(history) != sum(len(v) for v in MARKET_LINES.values()):
            raise ValueError("Missing fixed-market pitcher history rows")
        for market, lines in MARKET_LINES.items():
            subset = [r for r in history if r["market"] == market]
            if sorted(float(r["line"]) for r in subset) != sorted(lines):
                raise ValueError("Missing or extra fixed-market lines")
            for r in subset:
                if r["game_pk"] != game_pk or r["pitcher_id"] != pitcher_id:
                    raise ValueError("Pitcher history identity mismatch")
                if str(r["date"]) != str(start["date"]):
                    raise ValueError("Game date identity mismatch")
                y = float(r["actual_over"])
                if y not in (0.0, 1.0):
                    raise ValueError("Invalid historical settlement")
                key = (game_pk, pitcher_id, market, float(r["line"]))
                if key in seen:
                    raise ValueError("Duplicate pitcher-market outcome")
                seen.add(key)
                for source in PROBABILITY_SOURCES:
                    p = float(r[source])
                    if not isfinite(p) or not 0 <= p <= 1:
                        raise ValueError("Invalid source model probability")
                rows.append({
                    "game_pk": game_pk, "pitcher_id": pitcher_id,
                    "year": year, "market": market, "line": float(r["line"]),
                    "outcome": y,
                    **{src:float(r[src]) for src in PROBABILITY_SOURCES},
                })
    if len(rows) != 237 * sum(len(x) for x in MARKET_LINES.values()):
        raise ValueError("Missing historical evaluation observations")
    return rows


def _clip(p: float) -> float:
    return min(1.0-1e-9, max(1e-9, p))


def shifted(p: float, offset: float) -> float:
    if not isfinite(float(p)) or not 0 <= float(p) <= 1:
        raise ValueError("Bad base model probability")
    if not isfinite(offset) or abs(offset) > 6:
        raise ValueError("Bad postseason offset")
    v = _clip(float(p))
    log_odds = log(v/(1-v)) + offset
    return 1/(1+exp(-log_odds))


def fit_intercept(training: Sequence[Mapping[str, Any]], source: str) -> float:
    if source not in PROBABILITY_SOURCES or len(training) < 80:
        raise ValueError("Insufficient pregame training evidence")
    lo, hi = -6.0, 6.0
    for _ in range(80):
        middle = (lo+hi)/2
        net = sum(shifted(float(row[source]), middle)-float(row["outcome"])
                  for row in training)
        if net > 0:
            hi = middle
        else:
            lo = middle
    return (lo+hi)/2


def metrics(rows: Sequence[Mapping[str, Any]], source: str, offset: float) -> dict[str, float]:
    if not rows: raise ValueError("Empty later-season holdout")
    probs = [shifted(float(r[source]), offset) for r in rows]
    ys = [float(r["outcome"]) for r in rows]
    return {
        "brier":mean((p-y)**2 for p,y in zip(probs,ys)),
        "log_loss":mean(-y*log(p)-(1-y)*log(1-p) for p,y in zip(probs,ys)),
        "predicted_over_rate":mean(probs),
        "observed_over_rate":mean(ys),
    }


def game_cluster_interval(rows: Sequence[Mapping[str, Any]], source: str,
                          offset: float, seed: int) -> list[float]:
    grouped: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        original = shifted(row[source], 0.0)
        adjusted = shifted(row[source], offset)
        y = row["outcome"]
        grouped[row["game_pk"]].append((adjusted-y)**2-(original-y)**2)
    means = [mean(v) for _,v in sorted(grouped.items())]
    if len(means) < 25:
        raise ValueError("Not enough independent postseason games")
    random = Random(seed)
    boot = sorted(mean(means[random.randrange(len(means))] for _ in means)
                  for _ in range(BOOTSTRAP_DRAWS))
    return [boot[int(0.025*len(boot))],boot[int(0.975*len(boot))]]


def evaluate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    output = []
    for holdout_year, training_years in CHRONOLOGICAL_FOLDS:
        if max(training_years) >= holdout_year:
            raise ValueError("Chronological holdout misconfigured")
        by_market={}
        for market in MARKET_LINES:
            train = [r for r in rows if r["year"] in training_years and r["market"]==market]
            test = [r for r in rows if r["year"]==holdout_year and r["market"]==market]
            if len(train) < 80 or len(test) < 80:
                raise ValueError(f"Missing market coverage: {market}, {holdout_year}")
            by_source={}
            for source in PROBABILITY_SOURCES:
                intercept=fit_intercept(train,source)
                a=metrics(test,source,0.0)
                b=metrics(test,source,intercept)
                by_source[source]={
                    "train_count_correlated_thresholds":len(train),
                    "holdout_count_correlated_thresholds":len(test),
                    "heldout_pitcher_games":len({(r["game_pk"],r["pitcher_id"]) for r in test}),
                    "heldout_game_clusters":len({r["game_pk"] for r in test}),
                    "fitted_prior_season_log_odds_intercept":intercept,
                    "before":a,"after":b,
                    "brier_change":b["brier"]-a["brier"],
                    "log_loss_change":b["log_loss"]-a["log_loss"],
                    "game_cluster_bootstrap_descriptive_95_brier_change":game_cluster_interval(
                        test,source,intercept,seed=holdout_year+(1 if source==PROBABILITY_SOURCES[1] else 0)
                    ),
                }
            by_market[market]=by_source
        output.append({
            "training_years":list(training_years),
            "heldout_year":holdout_year,
            "markets":by_market,
        })
    return {
        "version":REPORT_VERSION,
        "source_archive_sha256":ARCHIVE_SHA256,
        "research_only":True,
        "production_price_changed":False,
        "live_quote_validated":False,
        "deployable_postseason_calibration":False,
        "folds":output,
        "limitations":"Historic cross-season holdout only; context-blind pregame regular-season marginal, not matchup-adjusted live pitcher pricing. Correlated half-lines share games. Does not model individual managers, lineup context or real-time sportsbook quotes.",
    }


def main()->None:
    p=argparse.ArgumentParser()
    p.add_argument("--input",required=True)
    p.add_argument("--output",required=True)
    a=p.parse_args()
    report=evaluate(extract_rows(read_locked_archive(Path(a.input))))
    path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf8")
    for fold in report["folds"]:
        for market,source_map in fold["markets"].items():
            for source,record in source_map.items():
                print("POSTSEASON_PROP_HOLDOUT",fold["heldout_year"],market,source,
                      f"offset={record['fitted_prior_season_log_odds_intercept']:.3f}",
                      f"Brier {record['before']['brier']:.4f} -> {record['after']['brier']:.4f}",
                      f"Logloss {record['before']['log_loss']:.4f} -> {record['after']['log_loss']:.4f}")
    print("HISTORICAL_RESEARCH_ONLY")


if __name__=="__main__":
    main()
