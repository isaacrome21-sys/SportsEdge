#!/usr/bin/env python3
"""Build and score the predeclared SportsEdge GAME/NRFI Statcast V5 lineage.

Chronology and gates are frozen in audit/STATCAST_V5_PREDECLARED_PROTOCOL_2026-08-12.md.
This script never fetches sportsbook data and never reads current historical Savant
expected-stat columns.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
import calendar, hashlib, json, math, os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression

from sportsedge.game_live_features import FI_FEATURES, RUN_FEATURES, apply_result, feature_one, new_history_state
from sportsedge.statcast_contract import GAME_STATCAST_FEATURES, NRFI_STATCAST_FEATURES, STATCAST_CONTRACT_VERSION
from sportsedge.statcast_v5_pipeline import (
    ContactState, StatcastV5Error, apply_contact_transformer, fetch_savant_events,
    fit_contact_transformer, game_identity, save_joblib_hashed, smoothed,
)

MLB_BASE = "https://statsapi.mlb.com"
YEARS = (2021, 2022, 2023, 2024, 2025)
GAME_FEATURES = tuple(RUN_FEATURES) + tuple(GAME_STATCAST_FEATURES)
FIRST_INNING_FEATURES = tuple(FI_FEATURES) + tuple(NRFI_STATCAST_FEATURES)
TEAM_PSEUDO = 75.0
PITCHER_PSEUDO = 50.0
BATTER_PSEUDO = 30.0


def _get_json(path: str, params: dict) -> dict:
    u = f"{MLB_BASE}{path}?{urlencode(params)}"
    with urlopen(Request(u, headers={"Accept": "application/json", "User-Agent": "SportsEdge/1.0"}), timeout=90) as r:
        return json.loads(r.read().decode())


def _month_ranges(year: int):
    for month in range(3, 11):
        last = calendar.monthrange(year, month)[1]
        yield f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last:02d}"


def fetch_games(cache: Path) -> list[dict]:
    cache.mkdir(parents=True, exist_ok=True)
    by_pk = {}
    for year in YEARS:
        for start, end in _month_ranges(year):
            p = cache / f"schedule_{start}_{end}.json"
            if p.exists():
                data = json.loads(p.read_text())
            else:
                data = _get_json("/api/v1/schedule", {"sportId": 1, "startDate": start, "endDate": end, "hydrate": "linescore,team"})
                p.write_text(json.dumps(data))
            for db in data.get("dates") or []:
                for g in db.get("games") or []:
                    if str(g.get("gameType")) != "R":
                        continue
                    if (g.get("status") or {}).get("abstractGameState") != "Final":
                        continue
                    ls = g.get("linescore") or {}; teams = g.get("teams") or {}
                    first = next((x for x in (ls.get("innings") or []) if int(x.get("num") or 0) == 1), None)
                    if not first:
                        continue
                    try:
                        d = date.fromisoformat(str(g.get("officialDate") or db.get("date")))
                        ar = int(((ls.get("teams") or {}).get("away") or {})["runs"])
                        hr = int(((ls.get("teams") or {}).get("home") or {})["runs"])
                        afi = int((first.get("away") or {}).get("runs", 0)); hfi = int((first.get("home") or {}).get("runs", 0))
                        aid = int(((teams.get("away") or {}).get("team") or {})["id"])
                        hid = int(((teams.get("home") or {}).get("team") or {})["id"])
                        pk = int(g["gamePk"])
                    except Exception:
                        continue
                    by_pk[pk] = {
                        "game_pk": pk, "officialDate": d.isoformat(), "year": year,
                        "away_id": aid, "home_id": hid, "away_runs": ar, "home_runs": hr,
                        "away_fi": afi, "home_fi": hfi,
                    }
    return sorted(by_pk.values(), key=lambda x: (x["officialDate"], x["game_pk"]))


def _avg_top3(ids, batter_states, prior):
    vals = [smoothed(batter_states.get(int(pid)), prior, BATTER_PSEUDO) for pid in ids]
    return {
        "xwoba": float(np.mean([v["xwoba"] for v in vals])),
        "barrel": float(np.mean([v["barrel"] for v in vals])),
    }


def build_rows(games: list[dict], raw: pd.DataFrame, contact: pd.DataFrame, prior: dict) -> dict[str, np.ndarray]:
    raw_groups = {int(k): v.copy() for k, v in raw.groupby(raw["game_pk"].astype(int), sort=False)}
    bb_groups = {int(k): v.copy() for k, v in contact.groupby(contact["game_pk"].astype(int), sort=False)}
    history = new_history_state()
    team_states: dict[str, ContactState] = {}
    pitcher_states: dict[int, ContactState] = {}
    batter_states: dict[int, ContactState] = {}
    out = defaultdict(list)

    by_date = defaultdict(list)
    for g in games:
        by_date[g["officialDate"]].append(g)

    for day in sorted(by_date):
        pending = []
        for g in sorted(by_date[day], key=lambda x: x["game_pk"]):
            pk = int(g["game_pk"])
            ge = raw_groups.get(pk)
            if ge is None or ge.empty:
                out["blocked_missing_statcast_game"].append(pk)
                continue
            try:
                ident = game_identity(ge)
                legacy_run, legacy_fi = feature_one(history, g)
                aoff = smoothed(team_states.get(ident["away_team"]), prior, TEAM_PSEUDO)
                hoff = smoothed(team_states.get(ident["home_team"]), prior, TEAM_PSEUDO)
                hsp = smoothed(pitcher_states.get(int(ident["home_sp"])), prior, PITCHER_PSEUDO)
                asp = smoothed(pitcher_states.get(int(ident["away_sp"])), prior, PITCHER_PSEUDO)
                away_sc = [aoff["xwoba"], aoff["xba"], aoff["barrel"], aoff["hard_hit"], aoff["ev"], hsp["xwoba"], hsp["xba"], hsp["barrel"], hsp["hard_hit"], hsp["ev"]]
                home_sc = [hoff["xwoba"], hoff["xba"], hoff["barrel"], hoff["hard_hit"], hoff["ev"], asp["xwoba"], asp["xba"], asp["barrel"], asp["hard_hit"], asp["ev"]]
                atop = _avg_top3(ident["away_top3"], batter_states, prior)
                htop = _avg_top3(ident["home_top3"], batter_states, prior)
                fi_sc = [atop["xwoba"], htop["xwoba"], atop["barrel"], htop["barrel"], asp["xwoba"], hsp["xwoba"], asp["hard_hit"], hsp["hard_hit"]]
                out["run_X"].extend([list(legacy_run[0]) + away_sc, list(legacy_run[1]) + home_sc])
                out["run_y"].extend([g["away_runs"], g["home_runs"]])
                out["run_year"].extend([g["year"], g["year"]]); out["run_gid"].extend([pk, pk]); out["run_side"].extend(["away", "home"])
                out["fi_X"].append(list(legacy_fi) + fi_sc); out["fi_y"].append(int(g["away_fi"] + g["home_fi"] > 0)); out["fi_year"].append(g["year"]); out["fi_gid"].append(pk)
                pending.append(g)
            except Exception as exc:
                out["blocked_identity_or_feature"].append({"game_pk": pk, "error": str(exc)})

        # Same-date outcomes and Statcast never affect another game on this date.
        for g in by_date[day]:
            apply_result(history, g)
            bb = bb_groups.get(int(g["game_pk"]))
            if bb is None or bb.empty:
                continue
            for row in bb.to_dict("records"):
                top = str(row.get("inning_topbot") or "").lower() == "top"
                team = str(row.get("away_team") if top else row.get("home_team"))
                pid = int(row["pitcher"]); bid = int(row["batter"])
                team_states.setdefault(team, ContactState()).add(row)
                pitcher_states.setdefault(pid, ContactState()).add(row)
                batter_states.setdefault(bid, ContactState()).add(row)

    arr = {}
    for k in ("run_X", "run_y", "run_year", "run_gid", "run_side", "fi_X", "fi_y", "fi_year", "fi_gid"):
        arr[k] = np.asarray(out[k])
    arr["blocked_missing_statcast_game"] = out["blocked_missing_statcast_game"]
    arr["blocked_identity_or_feature"] = out["blocked_identity_or_feature"]
    return arr


def _logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def _nb_draw(rng, mu, alpha, n):
    if alpha <= 1e-12:
        return rng.poisson(mu, size=n)
    lam = rng.gamma(shape=1 / alpha, scale=alpha * mu, size=n)
    return rng.poisson(lam)


def _sim(mu_a, mu_h, alpha, sigma, n, seed):
    rng = np.random.default_rng(seed)
    shared = rng.lognormal(-0.5 * sigma * sigma, sigma, n) if sigma > 0 else np.ones(n)
    a = _nb_draw(rng, mu_a * shared, alpha, n); h = _nb_draw(rng, mu_h * shared, alpha, n)
    return h, a, h - a, h + a


def _metric(p, y):
    p = np.asarray(p, float); y = np.asarray(y, float); n = len(y)
    pred = float(p.mean()); actual = float(y.mean())
    se = math.sqrt(max(actual * (1 - actual), 1e-9) / n)
    return {"n": n, "pred": pred, "actual": actual, "gap_pp": 100 * (pred - actual), "z": abs(pred - actual) / se, "brier": float(np.mean((p - y) ** 2))}


def _dist_rows(mu_a, mu_h, years, gids, aa, hh, alpha, sigma, n_sims, ml_cal=None):
    rows = []
    for ma, mh, yr, gid, ra, rh in zip(mu_a, mu_h, years, gids, aa, hh):
        h, a, margin, total = _sim(float(ma), float(mh), alpha, sigma, n_sims, 99173 + int(gid) % 100000)
        raw_ml = float(np.mean(h > a) + 0.5 * np.mean(h == a))
        ml = raw_ml if ml_cal is None else float(ml_cal.predict_proba(_logit([raw_ml]).reshape(-1, 1))[0, 1])
        row = {"year": int(yr), "gid": int(gid), "home_ml": ml, "raw_home_ml": raw_ml, "actual_home_ml": float(rh > ra) + 0.5 * float(rh == ra)}
        for line in (-2.5, -1.5, 1.5, 2.5):
            row[f"rl_{line:+.1f}"] = float(np.mean(margin + line > 0)); row[f"actual_rl_{line:+.1f}"] = float((rh - ra) + line > 0)
        for line in (7.5, 8.5, 9.5, 10.5):
            row[f"over_{line:.1f}"] = float(np.mean(total > line)); row[f"actual_over_{line:.1f}"] = float((rh + ra) > line)
        rows.append(row)
    return rows


def _report(rows):
    keys = ["home_ml"] + [f"rl_{x:+.1f}" for x in (-2.5, -1.5, 1.5, 2.5)] + [f"over_{x:.1f}" for x in (7.5, 8.5, 9.5, 10.5)]
    return {k: _metric([r[k] for r in rows], [r["actual_" + k] for r in rows]) for k in keys}


def _loss(rows):
    rep = _report(rows)
    return sum((v["pred"] - v["actual"]) ** 2 for v in rep.values())


def train_and_score(f, transformer_sha: str, out_dir: Path) -> dict:
    run_X = f["run_X"].astype(float); run_y = f["run_y"].astype(float); ry = f["run_year"].astype(int); sides = f["run_side"].astype(str)
    train = ry <= 2023; cal = ry == 2024; hold = ry == 2025
    model = HistGradientBoostingRegressor(loss="poisson", learning_rate=.045, max_iter=250, max_leaf_nodes=15, min_samples_leaf=80, l2_regularization=2.0, random_state=31)
    model.fit(run_X[train], run_y[train]); raw_pred = model.predict(run_X)
    scale_a = float(run_y[cal & (sides == "away")].sum() / raw_pred[cal & (sides == "away")].sum())
    scale_h = float(run_y[cal & (sides == "home")].sum() / raw_pred[cal & (sides == "home")].sum())
    pred = raw_pred * np.where(sides == "home", scale_h, scale_a)

    def paired(mask):
        by = {}
        for i, gid in enumerate(f["run_gid"].astype(int)):
            if mask[i]: by.setdefault(gid, {})[sides[i]] = (pred[i], run_y[i], ry[i])
        rows = []
        for gid, v in by.items():
            if "away" in v and "home" in v: rows.append((v["away"][0], v["home"][0], v["home"][2], gid, v["away"][1], v["home"][1]))
        return tuple(np.asarray([r[i] for r in rows]) for i in range(6))

    calarr = paired(cal); holdarr = paired(hold)
    grid = []
    for alpha in (.10, .18, .26, .34, .42):
        for sigma in (0.0, .08, .16, .24):
            rows = _dist_rows(*calarr, alpha, sigma, 700)
            grid.append((_loss(rows), alpha, sigma))
    grid.sort(); _, alpha, sigma = grid[0]
    cal_raw = _dist_rows(*calarr, alpha, sigma, 3000)
    ml_cal = LogisticRegression(C=100.0, solver="lbfgs").fit(_logit([r["raw_home_ml"] for r in cal_raw]).reshape(-1, 1), np.asarray([r["actual_home_ml"] for r in cal_raw]))
    cal_rows = _dist_rows(*calarr, alpha, sigma, 5000, ml_cal=ml_cal)
    hold_rows = _dist_rows(*holdarr, alpha, sigma, 7000, ml_cal=ml_cal)
    game_hold = _report(hold_rows)

    fy = f["fi_year"].astype(int); ft = fy <= 2023; fc = fy == 2024; fh = fy == 2025
    fi_model = HistGradientBoostingClassifier(learning_rate=.04, max_iter=220, max_leaf_nodes=15, min_samples_leaf=100, l2_regularization=3.0, random_state=41)
    fi_model.fit(f["fi_X"].astype(float)[ft], f["fi_y"].astype(int)[ft])
    raw = fi_model.predict_proba(f["fi_X"].astype(float))[:, 1]
    platt = LogisticRegression(C=100.0, solver="lbfgs").fit(_logit(raw[fc]).reshape(-1, 1), f["fi_y"].astype(int)[fc])
    p = platt.predict_proba(_logit(raw).reshape(-1, 1))[:, 1]
    fi_hold = _metric(p[fh], f["fi_y"].astype(int)[fh])
    buckets = []
    for lo, hi in ((0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.000001)):
        m = fh & (p >= lo) & (p < hi)
        if int(m.sum()) >= 30: buckets.append({"lo": lo, "hi": hi, **_metric(p[m], f["fi_y"].astype(int)[m])})

    ml_pass = game_hold["home_ml"]["z"] <= 2.5
    rl_pass = max(v["z"] for k, v in game_hold.items() if k.startswith("rl_")) <= 2.5
    total_pass = max(v["z"] for k, v in game_hold.items() if k.startswith("over_")) <= 2.5
    nrfi_pass = fi_hold["z"] <= 2.5 and max([b["z"] for b in buckets] or [0.0]) <= 3.0
    n_hold_games = len(holdarr[0]); n_hold_fi = int(fh.sum())
    enough = n_hold_games >= 1000 and n_hold_fi >= 1000

    game_artifact = {
        "version": "GAME_SCORE_V5_STATCAST", "run_model": model, "run_features": GAME_FEATURES,
        "away_scale": scale_a, "home_scale": scale_h, "alpha": alpha, "shared_sigma": sigma,
        "ml_calibrator": ml_cal, "statcast_contract_version": STATCAST_CONTRACT_VERSION,
        "statcast_consumed_by_model": True, "statcast_features": tuple(GAME_STATCAST_FEATURES),
        "contact_transformer_sha256": transformer_sha, "train": "2021-2023", "calibration": "2024", "holdout": "2025",
    }
    fi_artifact = {
        "version": "NRFI_V5_STATCAST", "model": fi_model, "calibrator": platt, "features": FIRST_INNING_FEATURES,
        "statcast_contract_version": STATCAST_CONTRACT_VERSION, "statcast_consumed_by_model": True,
        "statcast_features": tuple(NRFI_STATCAST_FEATURES), "contact_transformer_sha256": transformer_sha,
        "positive_class": "YRFI", "train": "2021-2023", "calibration": "2024", "holdout": "2025",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    game_path = out_dir / "sportsedge_game_score_v5_statcast.joblib"; fi_path = out_dir / "sportsedge_nrfi_v5_statcast.joblib"
    game_sha = save_joblib_hashed(game_artifact, game_path); fi_sha = save_joblib_hashed(fi_artifact, fi_path)
    validation = {
        "schema_version": "statcast_v5_holdout_v1", "source": "MLB_STATSAPI_PLUS_RAW_BASEBALL_SAVANT_NO_SPORTSBOOK_FEATURES",
        "contact_transformer_sha256": transformer_sha,
        "n_2025_game_rows": n_hold_games, "n_2025_first_inning_rows": n_hold_fi,
        "selected_on_2024": {"alpha": alpha, "shared_sigma": sigma, "away_scale": scale_a, "home_scale": scale_h},
        "game_holdout_2025": game_hold, "first_inning_holdout_2025": fi_hold, "first_inning_buckets_2025": buckets,
        "markets": {
            "MONEYLINE": {"pass": bool(ml_pass and enough)}, "RUN_LINE": {"pass": bool(rl_pass and enough)},
            "TOTALS": {"pass": bool(total_pass and enough)}, "NRFI": {"pass": bool(nrfi_pass and enough)}, "YRFI": {"pass": bool(nrfi_pass and enough)},
        },
        "artifacts": {"game": {"path": str(game_path), "sha256": game_sha}, "nrfi": {"path": str(fi_path), "sha256": fi_sha}},
        "blocked_missing_statcast_games": len(f["blocked_missing_statcast_game"]), "blocked_identity_or_feature": len(f["blocked_identity_or_feature"]),
    }
    (out_dir / "statcast_v5_validation.json").write_text(json.dumps(validation, indent=2, sort_keys=True))
    return validation


def main():
    cache = Path(os.getenv("SPORTSEDGE_STATCAST_V5_CACHE", ".cache/sportsedge/statcast-v5"))
    out_dir = Path(os.getenv("SPORTSEDGE_STATCAST_V5_OUT", "artifacts/statcast-v5"))
    games = fetch_games(cache / "schedule")
    frames = []
    for year in YEARS:
        frames.append(fetch_savant_events(date(year, 3, 1), date(year, 11, 15), cache / "savant" / str(year)))
    raw = pd.concat(frames, ignore_index=True)
    train_raw = raw[pd.to_datetime(raw["game_date"]).dt.year <= 2023].copy()
    transformer = fit_contact_transformer(train_raw)
    transformer_path = out_dir / "sportsedge_contact_x_v1.joblib"
    transformer_sha = save_joblib_hashed(transformer, transformer_path)
    contact = apply_contact_transformer(raw, transformer)
    f = build_rows(games, raw, contact, transformer["global_prior"])
    validation = train_and_score(f, transformer_sha, out_dir)
    manifest_paths = [transformer_path, out_dir / "sportsedge_game_score_v5_statcast.joblib", out_dir / "sportsedge_nrfi_v5_statcast.joblib", out_dir / "statcast_v5_validation.json"]
    manifest = {"schema_version": 1, "files": []}
    for p in manifest_paths:
        b = p.read_bytes(); manifest["files"].append({"path": str(p), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(json.dumps(validation, indent=2, sort_keys=True))
    failed = [m for m, v in validation["markets"].items() if not v["pass"]]
    if failed:
        raise SystemExit("STATCAST_V5_HOLDOUT_FAILED:" + ",".join(failed))
    print("STATCAST_V5_HOLDOUT_PASS")


if __name__ == "__main__":
    main()
