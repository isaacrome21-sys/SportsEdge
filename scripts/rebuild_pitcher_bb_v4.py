#!/usr/bin/env python3
"""Cutoff-correct pitcher-walk threshold rebuild from official MLB boxscores.

Predeclared protocol before the 2026 holdout is inspected:
- MLB officialDate is canonical slate date
- all same-date starters/opponents use one frozen prior-day history
- same-date boxscores update pitcher/team/league history only after the full date is featurized
- suspended/resumed games fail closed and never enter features or state
- train 2021-2024, Platt-calibrate on 2025, untouched holdout through 2026-08-10
- no sportsbook data is fetched or used
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import calendar
import json
import math
import os
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression

import scripts.rebuild_pitcher_bb_v3 as old
from sportsedge.historical_cutoff import suspended_or_resumed_reason


YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
THRESHOLDS = old.THRESHOLDS
FEATURES = old.FEATURES


def month_ranges(year: int):
    if year != 2026:
        yield from old.month_ranges(year)
        return
    for month in range(3, 8):
        yield f"{year}-{month:02d}-01", f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    yield "2026-08-01", "2026-08-10"


def fetch_schedule_cutoff(cache: Path):
    cache.mkdir(parents=True, exist_ok=True)
    by = {}
    excluded = []
    for year in YEARS:
        for start, end in month_ranges(year):
            path = cache / f"schedule_{start}_{end}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = old.get("/api/v1/schedule", {"sportId": 1, "startDate": start, "endDate": end, "hydrate": "team"})
                path.write_text(json.dumps(data), encoding="utf-8")
            for block in data.get("dates") or []:
                for game in block.get("games") or []:
                    if game.get("gameType") != "R" or (game.get("status") or {}).get("abstractGameState") != "Final":
                        continue
                    pk = int(game.get("gamePk") or 0)
                    reason = suspended_or_resumed_reason(game)
                    if reason:
                        excluded.append({"game_pk": pk, "official_date": game.get("officialDate") or block.get("date"), "reason_code": reason})
                        continue
                    official = game.get("officialDate")
                    if not isinstance(official, str) or not official:
                        excluded.append({"game_pk": pk, "official_date": None, "reason_code": "OFFICIAL_DATE_INVALID_OR_MISSING"})
                        continue
                    try:
                        dt = date.fromisoformat(official)
                        away_id = int(game["teams"]["away"]["team"]["id"])
                        home_id = int(game["teams"]["home"]["team"]["id"])
                    except Exception:
                        excluded.append({"game_pk": pk, "official_date": official, "reason_code": "SCHEDULE_FIELDS_INVALID"})
                        continue
                    by[pk] = {
                        "game_pk": pk,
                        "officialDate": dt.isoformat(),
                        "date": dt.isoformat(),
                        "year": dt.year,
                        "away_id": away_id,
                        "home_id": home_id,
                    }
    games = sorted(by.values(), key=lambda x: (x["officialDate"], x["game_pk"]))
    excluded.sort(key=lambda x: (x.get("official_date") or "", x.get("game_pk") or 0, x["reason_code"]))
    return games, excluded


def wilson_interval(successes: int, n: int, z: float = 1.96):
    if n <= 0:
        return [None, None]
    p = successes / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, center - half), min(1.0, center + half)]


def metric_with_ci(p, y):
    result = old.metric(p, y)
    y = np.asarray(y, dtype=int)
    result["actual_wilson95"] = wilson_interval(int(y.sum()), len(y))
    return result


def build_cutoff(games, boxdir: Path):
    pitcher_state = defaultdict(old.PState)
    team_state = defaultdict(old.TState)
    league_bf = 0.0
    league_bb = 0.0
    league_er = 0.0
    X = []
    walks = []
    years = []
    ids = []

    i = 0
    while i < len(games):
        day = games[i]["officialDate"]
        same_day = []
        while i < len(games) and games[i]["officialDate"] == day:
            same_day.append(games[i])
            i += 1

        # Freeze all priors for the entire date. No state mutation is permitted while
        # any feature row for this date is still being generated.
        league_p_w = (league_bb + old.PRIOR_W * 12000) / (league_bf + 12000)
        league_p_er = (league_er + old.PRIOR_ER * 12000) / (league_bf + 12000)
        pending = []

        for game in same_day:
            path = boxdir / f"{game['game_pk']}.json"
            if not path.exists():
                continue
            try:
                box = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            teams = box.get("teams") or {}
            d = date.fromisoformat(game["officialDate"])
            doy = d.timetuple().tm_yday
            sin_doy = math.sin(2 * math.pi * doy / 365.25)
            cos_doy = math.cos(2 * math.pi * doy / 365.25)
            starter_updates = []
            feature_rows = []

            for side, opp_side, team_id, opp_id in (
                ("away", "home", game["away_id"], game["home_id"]),
                ("home", "away", game["home_id"], game["away_id"]),
            ):
                team = teams.get(side) or {}
                pitcher_id, stats = old.starter(team)
                if pitcher_id is None or stats is None:
                    continue
                bf = old.safe(stats, "battersFaced")
                bb = old.safe(stats, "baseOnBalls")
                er = old.safe(stats, "earnedRuns")
                hits = old.safe(stats, "hits")
                if bf <= 0:
                    continue
                pitcher = pitcher_state[pitcher_id]
                opponent = team_state[opp_id]
                feats = [
                    old.rate(pitcher.bb, pitcher.bf, league_p_w, old.PITCHER_PRIOR_BF),
                    old.rate(pitcher.er, pitcher.bf, league_p_er, old.PITCHER_PRIOR_BF),
                    old.rate(pitcher.hits, pitcher.bf, old.PRIOR_H, old.PITCHER_PRIOR_BF),
                    (pitcher.bf / pitcher.starts if pitcher.starts else 22.0),
                    float(pitcher.starts),
                    old.rate(opponent.bb, opponent.pa, old.PRIOR_W, old.TEAM_PRIOR_PA),
                    old.rate(opponent.runs, opponent.pa, old.PRIOR_R, old.TEAM_PRIOR_PA),
                    old.rate(opponent.hits, opponent.pa, old.PRIOR_H, old.TEAM_PRIOR_PA),
                    league_p_w,
                    league_p_er,
                    float(d.month),
                    sin_doy,
                    cos_doy,
                ]
                feature_rows.append((feats, bb, game["year"], (game["game_pk"], pitcher_id, opp_id)))
                starter_updates.append((pitcher_id, bf, bb, er, hits))

            batting_updates = []
            for side, team_id in (("away", game["away_id"]), ("home", game["home_id"])):
                batting = ((teams.get(side) or {}).get("teamStats") or {}).get("batting") or {}
                batting_updates.append((
                    team_id,
                    old.safe(batting, "plateAppearances"),
                    old.safe(batting, "baseOnBalls"),
                    old.safe(batting, "runs"),
                    old.safe(batting, "hits"),
                ))
            pending.append((feature_rows, batting_updates, starter_updates))

        # Emit all feature rows first; then and only then apply every final from this date.
        for feature_rows, _, _ in pending:
            for feats, bb, year, identity in feature_rows:
                X.append(feats)
                walks.append(bb)
                years.append(year)
                ids.append(identity)

        for _, batting_updates, starter_updates in pending:
            for team_id, pa, bb, runs, hits in batting_updates:
                team = team_state[team_id]
                team.pa += pa
                team.bb += bb
                team.runs += runs
                team.hits += hits
            for pitcher_id, bf, bb, er, hits in starter_updates:
                pitcher = pitcher_state[pitcher_id]
                pitcher.starts += 1
                pitcher.bf += bf
                pitcher.bb += bb
                pitcher.er += er
                pitcher.hits += hits
                league_bf += bf
                league_bb += bb
                league_er += er

    return np.asarray(X, float), np.asarray(walks, float), np.asarray(years, int), ids


def diagnostic_buckets(p, y):
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=int)
    output = []
    for lo, hi in ((0.0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.000001)):
        mask = (p >= lo) & (p < hi)
        if int(mask.sum()) >= 30:
            output.append({"lo": lo, "hi": hi, **metric_with_ci(p[mask], y[mask])})
    return output


def main():
    root = Path(os.getenv("SPORTSEDGE_BB_REBUILD_CACHE", ".cache/sportsedge/bb-rebuild"))
    games, excluded = fetch_schedule_cutoff(root / "schedule")
    old.ensure_boxes(games, root / "boxscores")
    X, walks, years, ids = build_cutoff(games, root / "boxscores")

    train = years <= 2024
    calibration = years == 2025
    holdout = years == 2026
    models = {}
    report = {}
    all_pass = True

    for line in THRESHOLDS:
        y = (walks > line).astype(int)
        model = HistGradientBoostingClassifier(
            learning_rate=.045, max_iter=250, max_leaf_nodes=15,
            min_samples_leaf=100, l2_regularization=3.0, random_state=19,
        )
        model.fit(X[train], y[train])
        raw = model.predict_proba(X)[:, 1]
        calibrator = LogisticRegression(C=100.0, solver="lbfgs").fit(
            old.logit(raw[calibration]).reshape(-1, 1), y[calibration]
        )
        probability = calibrator.predict_proba(old.logit(raw).reshape(-1, 1))[:, 1]
        hold_metric = metric_with_ci(probability[holdout], y[holdout])
        cal_metric = metric_with_ci(probability[calibration], y[calibration])
        buckets = diagnostic_buckets(probability[holdout], y[holdout])
        passed = hold_metric["z"] <= 2.5 and max([b["z"] for b in buckets] or [0.0]) <= 3.0
        all_pass &= passed
        report[str(line)] = {
            "pass": bool(passed),
            "calibration_2025": cal_metric,
            "final_holdout_2026": hold_metric,
            "holdout_buckets": buckets,
        }
        models[str(line)] = {"model": model, "calibrator": calibrator}

    metadata = {
        "version": "PITCHER_BB_V4_CUTOFF_CORRECT",
        "source": "MLB_STATSAPI_BOXSCORING_ONLY",
        "chronology_policy": "OFFICIAL_DATE_PRIOR_DAY_SNAPSHOT_APPLY_RESULTS_AFTER_DAY",
        "suspended_resumed_policy": "FAIL_CLOSED_EXCLUDE_FROM_FEATURES_AND_STATE",
        "train": "2021-2024",
        "calibration": "2025",
        "final_holdout": "2026-03-01_to_2026-08-10",
        "features": FEATURES,
        "definitions": {
            "pit_bb_hist": "smoothed prior-date starter BB/battersFaced",
            "pit_er_hist": "smoothed prior-date starter ER/battersFaced",
            "pit_h_hist": "smoothed prior-date starter H/battersFaced",
            "bf_mean": "prior-date mean battersFaced per start",
            "prior_starts": "prior-date MLB starts observed",
            "opp_bb_hist": "smoothed opponent prior-date team batting BB/PA",
            "opp_r_hist": "smoothed opponent prior-date team runs/PA",
            "opp_h_hist": "smoothed opponent prior-date team hits/PA",
            "lg_p_w": "prior-date league starter BB/BF",
            "lg_p_er": "prior-date league starter ER/BF",
            "month": "venue-scheduled officialDate calendar month",
            "sin_doy": "sin officialDate day-of-year",
            "cos_doy": "cos officialDate day-of-year",
        },
        "threshold_report": report,
        "all_thresholds_pass": bool(all_pass),
        "rows": int(len(X)),
        "holdout_rows": int(holdout.sum()),
        "excluded_games": excluded,
    }

    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    joblib.dump({"metadata": metadata, "models": models}, artifacts / "sportsedge_pitcher_bb_v4.joblib")
    (artifacts / "pitcher_bb_v4_validation.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "rows": len(X),
        "holdout": int(holdout.sum()),
        "excluded_games": len(excluded),
        "passes": {k: v["pass"] for k, v in report.items()},
    }, indent=2, sort_keys=True))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
