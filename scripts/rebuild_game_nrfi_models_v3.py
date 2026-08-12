#!/usr/bin/env python3
"""Cutoff-correct ML/RL/totals and NRFI/YRFI rebuild.

Protocol was fixed before this path's 2026 holdout is inspected:
- MLB ``officialDate`` is the canonical venue-scheduled slate date
- every same-date game is featurized from one frozen prior-day snapshot
- results from date D are applied only after every eligible game on D is featurized
- suspended/resumed games are excluded fail-closed from features and state updates
- fit 2021-2024, calibrate on 2025, untouched holdout 2026 through 2026-08-10
- sportsbook prices/probabilities are never fetched or used
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import calendar
import json
import math
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

import scripts.rebuild_game_nrfi_models as core
from sportsedge.historical_cutoff import suspended_or_resumed_reason


YEARS = (2021, 2022, 2023, 2024, 2025, 2026)


def ranges(year: int):
    if year != 2026:
        yield from core.month_ranges(year)
        return
    for month in range(3, 8):
        yield f"{year}-{month:02d}-01", f"{year}-{month:02d}-{calendar.monthrange(year, month)[1]:02d}"
    yield "2026-08-01", "2026-08-10"


@dataclass
class HistoryState:
    teams: dict[int, core.TeamState]
    league_n: int = 0
    league_runs: float = 0.0
    league_fi_events: float = 0.0


def fetch_games_cutoff(cache_dir: Path):
    """Fetch only chronology-safe finals and preserve explicit exclusions."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    by_pk: dict[int, dict] = {}
    excluded: list[dict] = []
    for year in YEARS:
        for start, end in ranges(year):
            path = cache_dir / f"schedule_{start}_{end}.json"
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
            else:
                data = core.get_json(
                    "/api/v1/schedule",
                    {"sportId": 1, "startDate": start, "endDate": end, "hydrate": "linescore,team"},
                )
                path.write_text(json.dumps(data), encoding="utf-8")
            for date_block in data.get("dates") or []:
                for game in date_block.get("games") or []:
                    if str(game.get("gameType")) != "R":
                        continue
                    if (game.get("status") or {}).get("abstractGameState") != "Final":
                        continue
                    pk = int(game.get("gamePk") or 0)
                    reason = suspended_or_resumed_reason(game)
                    if reason:
                        excluded.append({
                            "game_pk": pk,
                            "official_date": game.get("officialDate") or date_block.get("date"),
                            "reason_code": reason,
                        })
                        continue
                    official = game.get("officialDate")
                    if not isinstance(official, str) or not official:
                        excluded.append({"game_pk": pk, "official_date": None, "reason_code": "OFFICIAL_DATE_INVALID_OR_MISSING"})
                        continue
                    linescore = game.get("linescore") or {}
                    teams = game.get("teams") or {}
                    try:
                        home_runs = int(((linescore.get("teams") or {}).get("home") or {})["runs"])
                        away_runs = int(((linescore.get("teams") or {}).get("away") or {})["runs"])
                        home_id = int(((teams.get("home") or {}).get("team") or {})["id"])
                        away_id = int(((teams.get("away") or {}).get("team") or {})["id"])
                        d = date.fromisoformat(official)
                    except Exception:
                        excluded.append({"game_pk": pk, "official_date": official, "reason_code": "FINAL_GAME_FIELDS_INVALID"})
                        continue
                    first = next((x for x in (linescore.get("innings") or []) if int(x.get("num") or 0) == 1), None)
                    if not first:
                        excluded.append({"game_pk": pk, "official_date": official, "reason_code": "FIRST_INNING_RESULT_MISSING"})
                        continue
                    try:
                        away_fi = int((first.get("away") or {}).get("runs", 0))
                        home_fi = int((first.get("home") or {}).get("runs", 0))
                    except Exception:
                        excluded.append({"game_pk": pk, "official_date": official, "reason_code": "FIRST_INNING_RESULT_INVALID"})
                        continue
                    by_pk[pk] = {
                        "game_pk": pk,
                        "officialDate": d.isoformat(),
                        "date": d.isoformat(),
                        "year": d.year,
                        "month": d.month,
                        "away_id": away_id,
                        "home_id": home_id,
                        "away_runs": away_runs,
                        "home_runs": home_runs,
                        "away_fi": away_fi,
                        "home_fi": home_fi,
                    }
    games = sorted(by_pk.values(), key=lambda x: (x["officialDate"], x["game_pk"]))
    excluded.sort(key=lambda x: (x.get("official_date") or "", x.get("game_pk") or 0, x["reason_code"]))
    return games, excluded


def _feature_one(state: HistoryState, game: dict):
    d = date.fromisoformat(game["officialDate"])
    a = state.teams.get(game["away_id"], core.TeamState())
    h = state.teams.get(game["home_id"], core.TeamState())
    if state.league_n:
        league_run = (state.league_runs + core.PRIOR_GAMES * 2 * core.RUN_PRIOR) / (2 * state.league_n + core.PRIOR_GAMES * 2)
        league_fi = (state.league_fi_events + core.PRIOR_GAMES * 2 * core.FI_PRIOR) / (2 * state.league_n + core.PRIOR_GAMES * 2)
    else:
        league_run = core.RUN_PRIOR
        league_fi = core.FI_PRIOR
    ms = math.sin(2 * math.pi * d.timetuple().tm_yday / 365.25)
    mc = math.cos(2 * math.pi * d.timetuple().tm_yday / 365.25)
    af = core.smooth(a.rf, a.n, core.RUN_PRIOR)
    aa = core.smooth(a.ra, a.n, core.RUN_PRIOR)
    hf = core.smooth(h.rf, h.n, core.RUN_PRIOR)
    ha = core.smooth(h.ra, h.n, core.RUN_PRIOR)
    run_rows = [
        [af, ha, a.ewm_rf, h.ewm_ra, league_run, 0.0, core.rest(a, d), float(a.n), ms, mc],
        [hf, aa, h.ewm_rf, a.ewm_ra, league_run, 1.0, core.rest(h, d), float(h.n), ms, mc],
    ]
    aff = core.smooth(a.fi_for, a.n, core.FI_PRIOR)
    afa = core.smooth(a.fi_against, a.n, core.FI_PRIOR)
    hff = core.smooth(h.fi_for, h.n, core.FI_PRIOR)
    hfa = core.smooth(h.fi_against, h.n, core.FI_PRIOR)
    fi_row = [
        aff, hff, hfa, afa,
        a.ewm_fi_for, h.ewm_fi_for, h.ewm_fi_against, a.ewm_fi_against,
        af, hf, ha, aa, league_fi, core.rest(a, d), core.rest(h, d), ms, mc,
    ]
    return run_rows, fi_row


def _apply_result(state: HistoryState, game: dict):
    d = date.fromisoformat(game["officialDate"])
    a = state.teams.setdefault(game["away_id"], core.TeamState())
    h = state.teams.setdefault(game["home_id"], core.TeamState())
    away_runs = game["away_runs"]
    home_runs = game["home_runs"]
    away_event = int(game["away_fi"] > 0)
    home_event = int(game["home_fi"] > 0)
    for st, rf, ra, ff, fa in (
        (a, away_runs, home_runs, away_event, home_event),
        (h, home_runs, away_runs, home_event, away_event),
    ):
        st.n += 1
        st.rf += rf
        st.ra += ra
        st.fi_for += ff
        st.fi_against += fa
        st.ewm_rf = 0.94 * st.ewm_rf + 0.06 * rf
        st.ewm_ra = 0.94 * st.ewm_ra + 0.06 * ra
        st.ewm_fi_for = 0.94 * st.ewm_fi_for + 0.06 * ff
        st.ewm_fi_against = 0.94 * st.ewm_fi_against + 0.06 * fa
        st.last_date = d
    state.league_n += 1
    state.league_runs += away_runs + home_runs
    state.league_fi_events += away_event + home_event


def build_features_cutoff(games):
    state = HistoryState(teams={})
    run_X = []
    run_y = []
    run_year = []
    run_gid = []
    run_side = []
    fi_X = []
    fi_y = []
    fi_year = []
    fi_gid = []

    i = 0
    while i < len(games):
        day = games[i]["officialDate"]
        same_day = []
        while i < len(games) and games[i]["officialDate"] == day:
            same_day.append(games[i])
            i += 1

        # Freeze-by-order invariant: no state mutation occurs in this loop.
        pending = []
        for game in same_day:
            run_rows, fi_row = _feature_one(state, game)
            pending.append((game, run_rows, fi_row))

        for game, run_rows, fi_row in pending:
            run_X.extend(run_rows)
            run_y.extend([game["away_runs"], game["home_runs"]])
            run_year.extend([game["year"], game["year"]])
            run_gid.extend([game["game_pk"], game["game_pk"]])
            run_side.extend(["away", "home"])
            fi_X.append(fi_row)
            fi_y.append(int(game["away_fi"] + game["home_fi"] > 0))
            fi_year.append(game["year"])
            fi_gid.append(game["game_pk"])

        # Only after every same-date feature exists do results enter history.
        for game, _, _ in pending:
            _apply_result(state, game)

    return {k: np.asarray(v) for k, v in {
        "run_X": run_X,
        "run_y": run_y,
        "run_year": run_year,
        "run_gid": run_gid,
        "run_side": run_side,
        "fi_X": fi_X,
        "fi_y": fi_y,
        "fi_year": fi_year,
        "fi_gid": fi_gid,
    }.items()}


def wilson_interval(successes: int, n: int, z: float = 1.96):
    if n <= 0:
        return [None, None]
    p = successes / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [max(0.0, center - half), min(1.0, center + half)]


def metric_with_ci(p, y):
    base = core.metric(p, y)
    y = np.asarray(y, dtype=int)
    base["actual_wilson95"] = wilson_interval(int(y.sum()), len(y))
    return base


def diagnostic_buckets(p, y):
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=int)
    out = []
    for lo, hi in ((0.0, .35), (.35, .45), (.45, .55), (.55, .65), (.65, 1.000001)):
        mask = (p >= lo) & (p < hi)
        if int(mask.sum()) >= 30:
            out.append({"lo": lo, "hi": hi, **metric_with_ci(p[mask], y[mask])})
    return out


def main():
    games, excluded = fetch_games_cutoff(Path(".cache/sportsedge/game-rebuild-v3/schedule"))
    f = build_features_cutoff(games)

    ry = f["run_year"].astype(int)
    train = ry <= 2024
    cal = ry == 2025
    hold = ry == 2026
    sides = f["run_side"].astype(str)

    run_model = HistGradientBoostingRegressor(
        loss="poisson", learning_rate=.045, max_iter=250, max_leaf_nodes=15,
        min_samples_leaf=80, l2_regularization=2.0, random_state=31,
    )
    run_model.fit(f["run_X"][train], f["run_y"][train])
    raw_mu = run_model.predict(f["run_X"])
    away_scale = float(f["run_y"][cal & (sides == "away")].sum() / raw_mu[cal & (sides == "away")].sum())
    home_scale = float(f["run_y"][cal & (sides == "home")].sum() / raw_mu[cal & (sides == "home")].sum())
    mu = raw_mu * np.where(sides == "home", home_scale, away_scale)

    def arrays(mask):
        by = {}
        for idx, gid in enumerate(f["run_gid"].astype(int)):
            if mask[idx]:
                by.setdefault(gid, {})[sides[idx]] = (mu[idx], f["run_y"][idx], ry[idx])
        ma, mh, yrs, gids, aa, hh = [], [], [], [], [], []
        for gid in sorted(by):
            value = by[gid]
            if {"away", "home"} <= set(value):
                ma.append(value["away"][0]); mh.append(value["home"][0])
                aa.append(value["away"][1]); hh.append(value["home"][1])
                yrs.append(value["home"][2]); gids.append(gid)
        return tuple(np.asarray(x) for x in (ma, mh, yrs, gids, aa, hh))

    cal_arr = arrays(cal)
    hold_arr = arrays(hold)
    grid = []
    for alpha in (.10, .18, .26, .34, .42):
        for sigma in (0.0, .08, .16, .24):
            rows = core.score_distribution(*cal_arr, alpha, sigma, 800)
            grid.append((core.loss(rows), alpha, sigma))
    grid.sort()
    _, alpha, sigma = grid[0]
    cal_rows = core.score_distribution(*cal_arr, alpha, sigma, 5000)
    hold_rows = core.score_distribution(*hold_arr, alpha, sigma, 7000)

    cal_ml_p = np.asarray([r["home_ml"] for r in cal_rows])
    cal_ml_y = np.asarray([r["actual_home_ml"] for r in cal_rows])
    hold_ml_p = np.asarray([r["home_ml"] for r in hold_rows])
    hold_ml_y = np.asarray([r["actual_home_ml"] for r in hold_rows])
    ml_calibrator = LogisticRegression(C=100.0, solver="lbfgs").fit(core.logit(cal_ml_p).reshape(-1, 1), cal_ml_y)
    hold_ml_cal = ml_calibrator.predict_proba(core.logit(hold_ml_p).reshape(-1, 1))[:, 1]

    hold_report = core.report_rows(hold_rows)
    ml_metric = metric_with_ci(hold_ml_cal, hold_ml_y)
    ml_buckets = diagnostic_buckets(hold_ml_cal, hold_ml_y)
    ml_pass = ml_metric["z"] <= 2.5 and max([b["z"] for b in ml_buckets] or [0.0]) <= 3.0
    rl_pass = max(hold_report[k]["z"] for k in hold_report if k.startswith("rl_")) <= 2.5
    totals_pass = max(hold_report[k]["z"] for k in hold_report if k.startswith("over_")) <= 2.5

    fy = f["fi_year"].astype(int)
    fi_train = fy <= 2024
    fi_cal = fy == 2025
    fi_hold = fy == 2026
    fi_model = HistGradientBoostingClassifier(
        learning_rate=.04, max_iter=220, max_leaf_nodes=15, min_samples_leaf=100,
        l2_regularization=3.0, random_state=41,
    )
    fi_model.fit(f["fi_X"][fi_train], f["fi_y"][fi_train])
    fi_raw = fi_model.predict_proba(f["fi_X"])[:, 1]
    fi_calibrator = LogisticRegression(C=100.0, solver="lbfgs").fit(
        core.logit(fi_raw[fi_cal]).reshape(-1, 1), f["fi_y"][fi_cal]
    )
    fi_hold_p = fi_calibrator.predict_proba(core.logit(fi_raw[fi_hold]).reshape(-1, 1))[:, 1]
    fi_metric = metric_with_ci(fi_hold_p, f["fi_y"][fi_hold])
    fi_buckets = diagnostic_buckets(fi_hold_p, f["fi_y"][fi_hold])
    fi_pass = fi_metric["z"] <= 2.5 and max([b["z"] for b in fi_buckets] or [0.0]) <= 3.0

    validation = {
        "schema_version": "core_game_markets_rebuild_v3_cutoff_correct",
        "source": "MLB_STATSAPI_ONLY_NO_SPORTSBOOK_FEATURES",
        "chronology_policy": "OFFICIAL_DATE_PRIOR_DAY_SNAPSHOT_APPLY_RESULTS_AFTER_DAY",
        "suspended_resumed_policy": "FAIL_CLOSED_EXCLUDE_FROM_FEATURES_AND_STATE",
        "train": "2021-2024",
        "calibration": "2025",
        "final_holdout": "2026-03-01_to_2026-08-10",
        "excluded_games": excluded,
        "markets": {
            "MONEYLINE": {"pass": ml_pass, "metrics": ml_metric, "holdout_buckets": ml_buckets},
            "RUN_LINE": {"pass": rl_pass, "metrics": {k: v for k, v in hold_report.items() if k.startswith("rl_")}},
            "TOTALS": {"pass": totals_pass, "metrics": {k: v for k, v in hold_report.items() if k.startswith("over_")}},
            "NRFI_YRFI": {"pass": fi_pass, "metrics": fi_metric, "holdout_buckets": fi_buckets},
        },
        "selected_on_2025": {
            "alpha": alpha,
            "shared_sigma": sigma,
            "away_scale": away_scale,
            "home_scale": home_scale,
        },
        "holdout_games": len(hold_rows),
    }

    artifacts = Path("artifacts")
    artifacts.mkdir(exist_ok=True)
    joblib.dump({
        "version": "GAME_SCORE_V4_CUTOFF_CORRECT",
        "run_model": run_model,
        "run_features": core.RUN_FEATURES,
        "away_scale": away_scale,
        "home_scale": home_scale,
        "alpha": alpha,
        "shared_sigma": sigma,
        "ml_calibrator": ml_calibrator,
        "feature_policy": "officialDate_prior_day_team_history",
    }, artifacts / "sportsedge_game_score_v4.joblib")
    joblib.dump({
        "version": "NRFI_V4_CUTOFF_CORRECT",
        "model": fi_model,
        "calibrator": fi_calibrator,
        "features": core.FI_FEATURES,
        "feature_policy": "officialDate_prior_day_team_first_inning_history",
    }, artifacts / "sportsedge_nrfi_v4.joblib")
    (artifacts / "core_game_markets_validation_v3.json").write_text(
        json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "holdout_games": len(hold_rows),
        "excluded_games": len(excluded),
        "passes": {k: v["pass"] for k, v in validation["markets"].items()},
        "selected": validation["selected_on_2025"],
    }, indent=2, sort_keys=True))
    return 0 if all(v["pass"] for v in validation["markets"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
