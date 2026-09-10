#!/usr/bin/env python3
"""Fit the MLB baseline score model from free MLB StatsAPI data.

This is the simplest defensible baseline, not the production engine. Its job is
to answer one question that has never been answered in this project: does a
fitted model on real held-out MLB data show any signal at all?

Deliberate properties:
  * No paid provider. MLB StatsAPI is free and needs no key. Odds are required
    for market readout, not for fitting a score model, so none are used here.
  * Point-in-time by construction. Every feature for a game is built only from
    games that finished strictly before that game's date.
  * StatsAPI can list one final gamePk on multiple schedule dates after a
    reschedule/resumption. Identical duplicate outcomes are conservatively
    assigned to the latest listed date so a final score is never pulled backward;
    conflicting duplicate rows fail closed.
  * The sacred holdout is carved before fitting or alpha selection and is used
    only for final research diagnostics.
  * Ridge alpha is cross-validated on the training fold only. It is not assumed.
  * A shuffled-label placebo runs before the real evaluation is reported.
  * The report hashes the exact raw source rows, normalized rows, and exact
    usable model rows so a result cannot be mistaken for another input set.

It promotes nothing. It writes a JSON report and exits.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from itertools import groupby
import json
import hashlib
from pathlib import Path
import sys
import time
from typing import Any
import urllib.request

import numpy as np

STATSAPI = "https://statsapi.mlb.com/api/v1/schedule"
ALPHAS = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
ROLL = 30          # rolling window of prior games per team
MIN_PRIOR = 20     # a team needs this many prior games before it is usable


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _normalize_schedule_duplicates(
    raw_games: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collapse duplicate gamePk rows without moving outcomes earlier in time.

    StatsAPI season schedule responses can expose the same final gamePk on an
    original and later rescheduled/resumed date. We permit normalization only
    when teams and final scores are identical. The latest listed date is the
    conservative chronology: it may delay information, but cannot introduce a
    final score before the last date on which the source associates the game.
    """
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in raw_games:
        grouped[int(row["game_pk"])].append(row)

    normalized: list[dict[str, Any]] = []
    duplicate_game_pks = 0
    duplicate_rows_removed = 0
    examples: list[dict[str, Any]] = []
    for game_pk, rows in sorted(grouped.items()):
        signatures = {
            (
                int(row["home_id"]),
                int(row["away_id"]),
                int(row["home_score"]),
                int(row["away_score"]),
            )
            for row in rows
        }
        if len(signatures) != 1:
            raise ValueError(
                "STATSAPI_DUPLICATE_GAME_PK_CONFLICT:"
                + json.dumps({"game_pk": game_pk, "rows": rows}, sort_keys=True)
            )
        chosen = max(rows, key=lambda row: str(row["date"]))
        normalized.append(dict(chosen))
        if len(rows) > 1:
            duplicate_game_pks += 1
            duplicate_rows_removed += len(rows) - 1
            if len(examples) < 25:
                examples.append({
                    "game_pk": game_pk,
                    "listed_dates": sorted(str(row["date"]) for row in rows),
                    "chosen_date": str(chosen["date"]),
                })

    normalized.sort(key=lambda row: (str(row["date"]), int(row["game_pk"])))
    return normalized, {
        "rule": "IDENTICAL_OUTCOME_DUPLICATE_GAME_PK_USE_LATEST_LISTED_DATE_V1",
        "duplicate_game_pk_count": duplicate_game_pks,
        "duplicate_rows_removed": duplicate_rows_removed,
        "conflicting_duplicates_allowed": False,
        "examples": examples,
    }


# --------------------------------------------------------------------------
# acquisition (free, unauthenticated)
# --------------------------------------------------------------------------
def fetch_season(year: int, *, retries: int = 3) -> list[dict[str, Any]]:
    url = (
        f"{STATSAPI}?sportId=1&season={year}"
        f"&startDate={year}-03-01&endDate={year}-11-15"
        "&gameType=R&fields=dates,date,games,gamePk,status,codedGameState,"
        "teams,home,away,team,id,name,score"
    )
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=90) as resp:
                payload = json.load(resp)
            break
        except Exception as exc:  # network flake on a free endpoint
            last = exc
            time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"MLB StatsAPI failed for {year}: {last}")

    rows: list[dict[str, Any]] = []
    for day in payload.get("dates", []):
        for g in day.get("games", []):
            if g.get("status", {}).get("codedGameState") != "F":
                continue
            home, away = g["teams"]["home"], g["teams"]["away"]
            if "score" not in home or "score" not in away:
                continue
            rows.append({
                "game_pk": g["gamePk"],
                "date": day["date"],
                "home_id": home["team"]["id"],
                "away_id": away["team"]["id"],
                "home_score": int(home["score"]),
                "away_score": int(away["score"]),
            })
    return rows


# --------------------------------------------------------------------------
# point-in-time features
# --------------------------------------------------------------------------
def build_rows(games: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str], list[str], list[int]]:
    """Return X, y_margin, y_total, feature_names, dates, game_pks.

    Every feature uses only games strictly before the current game's date.
    Games are processed in date order; all rows for a date are emitted before
    any game from that date is appended, so no game can see same-date results.
    """
    games = sorted(games, key=lambda r: (r["date"], r["game_pk"]))
    scored: dict[int, list[float]] = defaultdict(list)
    allowed: dict[int, list[float]] = defaultdict(list)
    home_scored: dict[int, list[float]] = defaultdict(list)
    away_scored: dict[int, list[float]] = defaultdict(list)

    names = [
        "home_rs_roll", "home_ra_roll", "away_rs_roll", "away_ra_roll",
        "home_net_roll", "away_net_roll",
        "home_rs_home_split", "away_rs_away_split",
        "home_rest_proxy", "away_rest_proxy",
    ]
    X, ym, yt, dates, game_pks = [], [], [], [], []
    last_played: dict[int, str] = {}

    def mean_tail(seq: list[float], n: int = ROLL) -> float:
        tail = seq[-n:]
        return float(np.mean(tail)) if tail else 0.0

    def day_gap(team: int, date: str) -> float:
        prev = last_played.get(team)
        if not prev:
            return 1.0
        a = tuple(int(x) for x in prev.split("-"))
        b = tuple(int(x) for x in date.split("-"))
        import datetime as _dt
        gap = (_dt.date(*b) - _dt.date(*a)).days
        return float(min(max(gap, 0), 7))

    # Emit a complete calendar date from the prior-date snapshot. This avoids
    # same-day ordering leakage when a later game is processed after an earlier
    # game on the same date.
    for d, date_group in groupby(games, key=lambda r: r["date"]):
        date_games = list(date_group)
        for g in date_games:
            h, a = g["home_id"], g["away_id"]
            if len(scored[h]) >= MIN_PRIOR and len(scored[a]) >= MIN_PRIOR:
                X.append([
                    mean_tail(scored[h]), mean_tail(allowed[h]),
                    mean_tail(scored[a]), mean_tail(allowed[a]),
                    mean_tail(scored[h]) - mean_tail(allowed[h]),
                    mean_tail(scored[a]) - mean_tail(allowed[a]),
                    mean_tail(home_scored[h]), mean_tail(away_scored[a]),
                    day_gap(h, d), day_gap(a, d),
                ])
                ym.append(g["home_score"] - g["away_score"])
                yt.append(g["home_score"] + g["away_score"])
                dates.append(d)
                game_pks.append(int(g["game_pk"]))

        for g in date_games:
            h, a = g["home_id"], g["away_id"]
            scored[h].append(g["home_score"]); allowed[h].append(g["away_score"])
            scored[a].append(g["away_score"]); allowed[a].append(g["home_score"])
            home_scored[h].append(g["home_score"])
            away_scored[a].append(g["away_score"])
            last_played[h] = last_played[a] = d

    return np.array(X, float), np.array(ym, float), np.array(yt, float), names, dates, game_pks


# --------------------------------------------------------------------------
# ridge, standardized, no sklearn dependency
# --------------------------------------------------------------------------
def standardize(train: np.ndarray, other: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mu, sd = train.mean(0), train.std(0)
    sd[sd == 0] = 1.0
    return (train - mu) / sd, (other - mu) / sd


def ridge_fit(X: np.ndarray, y: np.ndarray, alpha: float) -> tuple[np.ndarray, float]:
    n, p = X.shape
    Xc, yc = X - X.mean(0), y - y.mean()
    beta = np.linalg.solve(Xc.T @ Xc + alpha * np.eye(p), Xc.T @ yc)
    return beta, float(y.mean() - X.mean(0) @ beta)


def cv_alpha(X: np.ndarray, y: np.ndarray, folds: int = 5) -> tuple[float, dict[str, float]]:
    """Forward-chaining CV. Time-ordered data must never train on its future."""
    scores: dict[float, list[float]] = {a: [] for a in ALPHAS}
    n = len(X)
    for k in range(1, folds + 1):
        cut = int(n * k / (folds + 1))
        end = int(n * (k + 1) / (folds + 1))
        Xtr, Xva = standardize(X[:cut], X[cut:end])
        ytr, yva = y[:cut], y[cut:end]
        for a in ALPHAS:
            b, i0 = ridge_fit(Xtr, ytr, a)
            scores[a].append(float(np.mean((Xva @ b + i0 - yva) ** 2)))
    mean_mse = {a: float(np.mean(v)) for a, v in scores.items()}
    best = min(mean_mse, key=mean_mse.get)
    return best, {str(a): v for a, v in mean_mse.items()}


def fold_signs(X: np.ndarray, y: np.ndarray, alpha: float, folds: int = 5) -> list[float]:
    """Fraction of folds in which each coefficient keeps its majority sign."""
    n, p = len(X), X.shape[1]
    betas = []
    for k in range(1, folds + 1):
        cut = int(n * k / (folds + 1))
        Xtr, _ = standardize(X[:cut], X[:cut])
        b, _ = ridge_fit(Xtr, y[:cut], alpha)
        betas.append(b)
    B = np.array(betas)
    return [float(max((B[:, j] > 0).mean(), (B[:, j] < 0).mean())) for j in range(p)]


def evaluate(Xtr, ytr, Xte, yte, alpha) -> dict[str, float]:
    Xtr_s, Xte_s = standardize(Xtr, Xte)
    b, i0 = ridge_fit(Xtr_s, ytr, alpha)
    pred = Xte_s @ b + i0
    base = float(np.mean((ytr.mean() - yte) ** 2))
    mse = float(np.mean((pred - yte) ** 2))
    return {
        "rmse": float(np.sqrt(mse)),
        "baseline_rmse": float(np.sqrt(base)),
        "r2_vs_mean": float(1 - mse / base) if base else 0.0,
        "mae": float(np.mean(np.abs(pred - yte))),
    }


def _model_rows(X: np.ndarray, y_margin: np.ndarray, y_total: np.ndarray, dates: list[str], game_pks: list[int]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, (date_value, game_pk) in enumerate(zip(dates, game_pks)):
        rows.append({
            "date": date_value,
            "game_pk": int(game_pk),
            "features": [float(x) for x in X[i]],
            "margin": float(y_margin[i]),
            "total": float(y_total[i]),
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2021,2022,2023,2024,2025")
    ap.add_argument("--holdout-season", default="2025",
                    help="sacred holdout; carved by date before any fitting")
    ap.add_argument("--out", default="artifacts/mlb_baseline_report.json")
    args = ap.parse_args()

    seasons = [int(s) for s in args.seasons.split(",")]
    hold = int(args.holdout_season)
    if hold not in seasons:
        print("holdout season must be present in --seasons", file=sys.stderr)
        return 2
    if any(year > hold for year in seasons):
        print("post-holdout seasons are prohibited in this research baseline", file=sys.stderr)
        return 2

    games: list[dict[str, Any]] = []
    per_season = {}
    for yr in seasons:
        rows = fetch_season(yr)
        per_season[yr] = len(rows)
        games.extend(rows)
        print(f"  {yr}: {len(rows)} final rows", flush=True)
    if not games:
        print("NO DATA RETURNED", file=sys.stderr)
        return 2

    raw_games = sorted(games, key=lambda row: (str(row["date"]), int(row["game_pk"])))
    raw_source_rows_sha = _canonical_sha256(raw_games)
    try:
        canonical_games, duplicate_normalization = _normalize_schedule_duplicates(raw_games)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    normalized_source_rows_sha = _canonical_sha256(canonical_games)
    print(
        "normalized StatsAPI rows: "
        f"{len(raw_games)} raw -> {len(canonical_games)} unique gamePk; "
        f"duplicates={duplicate_normalization['duplicate_game_pk_count']}",
        flush=True,
    )

    X, y_margin, y_total, names, dates, game_pks = build_rows(canonical_games)
    print(f"usable rows: {len(X)} (min {MIN_PRIOR} prior games per team)", flush=True)

    # Sacred holdout carved by date, before any fitting touches the data.
    is_hold = np.array([d.startswith(str(hold)) for d in dates])
    if is_hold.sum() < 200 or (~is_hold).sum() < 500:
        print("insufficient split", file=sys.stderr)
        return 2

    model_rows = _model_rows(X, y_margin, y_total, dates, game_pks)
    train_rows = [row for row, flag in zip(model_rows, is_hold) if not bool(flag)]
    holdout_rows = [row for row, flag in zip(model_rows, is_hold) if bool(flag)]
    model_rows_sha = _canonical_sha256(model_rows)
    train_rows_sha = _canonical_sha256(train_rows)
    holdout_rows_sha = _canonical_sha256(holdout_rows)

    holdout_def = {
        "rule": f"all normalized model rows with date starting {hold}",
        "n_holdout": int(is_hold.sum()),
        "n_train": int((~is_hold).sum()),
        "row_identity_sha256": _canonical_sha256([
            {"date": row["date"], "game_pk": row["game_pk"]} for row in holdout_rows
        ]),
        "model_rows_sha256": holdout_rows_sha,
    }

    report: dict[str, Any] = {
        "schema": "MLB_BASELINE_REPORT_V2",
        "status": "RESEARCH_ONLY_NOT_MODEL_P",
        "source": "MLB StatsAPI (free, unauthenticated). No odds provider used.",
        "seasons": per_season,
        "feature_names": names,
        "input_provenance": {
            "canonicalization": "CANONICAL_JSON_SORT_KEYS_COMPACT_UTF8_V1",
            "raw_statsapi_final_row_count": len(raw_games),
            "raw_statsapi_final_rows_sha256": raw_source_rows_sha,
            "normalized_unique_game_count": len(canonical_games),
            "normalized_unique_games_sha256": normalized_source_rows_sha,
            "duplicate_normalization": duplicate_normalization,
            "usable_model_row_count": len(model_rows),
            "usable_model_rows_sha256": model_rows_sha,
            "train_model_rows_sha256": train_rows_sha,
            "holdout_model_rows_sha256": holdout_rows_sha,
        },
        "sacred_holdout": holdout_def,
        "targets": {},
    }

    for label, y in (("margin", y_margin), ("total", y_total)):
        Xtr, ytr = X[~is_hold], y[~is_hold]
        Xte, yte = X[is_hold], y[is_hold]

        alpha, grid = cv_alpha(Xtr, ytr)

        # Placebo runs before the real holdout number is produced.
        rng = np.random.default_rng(0)
        shuffled = ytr.copy(); rng.shuffle(shuffled)
        placebo = evaluate(Xtr, shuffled, Xte, yte, alpha)

        Xtr_s, _ = standardize(Xtr, Xtr)
        beta, intercept = ridge_fit(Xtr_s, ytr, alpha)
        stability = fold_signs(Xtr, ytr, alpha)
        real = evaluate(Xtr, ytr, Xte, yte, alpha)

        report["targets"][label] = {
            "cv_selected_alpha": alpha,
            "alpha_assumed_by_config": 10.0,
            "cv_grid_mse": grid,
            "intercept": intercept,
            "coefficients": {
                n: {"beta": float(b), "sign_stability": s}
                for n, b, s in zip(names, beta, stability)
            },
            "coefficients_by_magnitude": [
                n for n, _ in sorted(
                    zip(names, np.abs(beta)), key=lambda t: -t[1]
                )
            ],
            "placebo_shuffled_labels": placebo,
            "holdout": real,
            "signal_verdict": (
                "NO_SIGNAL" if real["r2_vs_mean"] <= 0
                else "LEAKAGE_SUSPECTED" if placebo["r2_vs_mean"] > 0.05
                else "WEAK_SIGNAL" if real["r2_vs_mean"] < 0.03
                else "SIGNAL_PRESENT"
            ),
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")

    print("\n" + "=" * 60)
    print(f"raw source rows sha256: {raw_source_rows_sha}")
    print(f"normalized rows sha256: {normalized_source_rows_sha}")
    print(f"usable rows sha256: {model_rows_sha}")
    for label, r in report["targets"].items():
        print(f"\n{label.upper()}  alpha={r['cv_selected_alpha']} (config assumed 10.0)")
        print(f"  holdout RMSE {r['holdout']['rmse']:.3f} vs mean-baseline "
              f"{r['holdout']['baseline_rmse']:.3f}")
        print(f"  r2_vs_mean   {r['holdout']['r2_vs_mean']:+.4f}")
        print(f"  placebo r2   {r['placebo_shuffled_labels']['r2_vs_mean']:+.4f} "
              "(should be <= 0)")
        print(f"  VERDICT      {r['signal_verdict']}")
        print("  top coefficients:")
        for n in r["coefficients_by_magnitude"][:5]:
            c = r["coefficients"][n]
            print(f"    {n:<24} {c['beta']:+.4f}  sign-stable {c['sign_stability']:.0%}")
    print("\nRESEARCH ONLY / NOT Model_P / NOT Truth Gate / NOT OFFICIAL")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
