#!/usr/bin/env python3
"""CFB_TEAM_TOTAL_POSSESSION_V1 — historical design screen (ONE run).

Implements the screen fixed by PREREG_CFB_TEAM_TOTALS_FORWARD_V1_DRAFT.md §4
(draft PR #2846) against the construction in DESIGN_CFB_TEAM_TOTALS_V1.md.
Criteria, cohort, arms, and readings were fixed before this run; see
SCREEN_REPORT.md §4 for the recorded implementer readings (R1–R8).

Inputs (hash-pinned in PINS.json beside the report):
  SDV cfb_schedules + espn_cfb_betting CSV releases, 2021–2025;
  cfbfastR play-by-play parquets, 2021–2025 (sportsdataverse-data mirror
  release cfbfastR_cfb_pbp; 2021 from the cfbfastR-data git tree).
Outputs: predictions + summary JSON under screen_out/ beside the runner
(scratch at run time); the committed run record is screen_results.json
beside the report. At run time the pinned inputs were staged in a
data/ directory beside the runner (not committed; see PINS.json).
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize_scalar

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
OUT = ROOT / "screen_out"
OUT.mkdir(parents=True, exist_ok=True)
SEASONS = [2021, 2022, 2023, 2024, 2025]
EVAL_SEASONS = [2023, 2024, 2025]
POOL_K = 3.0  # design 2.3 constant, fixed

IL_COLLEGE_NAMES = {
    "illinois", "illinois fighting illini", "university of illinois",
    "illinois state", "illinois state redbirds", "northern illinois",
    "northern illinois huskies", "southern illinois",
    "southern illinois salukis", "western illinois",
    "western illinois leathernecks", "eastern illinois",
    "eastern illinois panthers", "northwestern", "northwestern wildcats",
    "loyola chicago", "uic flames", "illinois chicago",
    "chicago state", "chicago state cougars", "chicago st",
}
PBP_COLS = ["game_id", "pos_team", "drive_id", "play_id", "play_type",
            "passer_player_name"]


def norm(name) -> str:
    return " ".join(str(name or "").strip().lower().replace(".", "").split())


def load_csv_gz(path: Path) -> pd.DataFrame:
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        return pd.read_csv(fh, low_memory=False)


def as_bool(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.lower().isin(
        ["true", "1", "t", "yes", "y"])


def load_schedules() -> pd.DataFrame:
    sched = pd.concat(
        [load_csv_gz(DATA / f"cfb_schedules_{y}.csv.gz") for y in SEASONS],
        ignore_index=True)
    sched["game_id"] = sched["game_id"].astype(int)
    return sched


# ---------------------------------------------------------------- data build
def build_team_games(sched_all: pd.DataFrame) -> pd.DataFrame:
    """Per (game, team): points, drives (PBP), first recorded passer."""
    # scope: games with at least one FBS team (the cfbfastR package cut)
    sched = sched_all[(sched_all["home_division"] == "fbs")
                      | (sched_all["away_division"] == "fbs")]
    game_rows = {int(g["game_id"]): g for _, g in sched.iterrows()}
    frames = []
    for y in SEASONS:
        raw = pd.read_parquet(DATA / f"play_by_play_{y}.parquet")
        # input-layer dialect normalization (recorded in the report):
        # mirror files name the play key id_play; the 2021 tree file names
        # the drive key drive.id and the play key sequenceNumber.
        df = pd.DataFrame({
            "game_id": raw["game_id"].astype(int),
            "pos_team": raw["pos_team"],
            "drive_id": raw["drive_id"] if "drive_id" in raw else raw["drive.id"],
            "play_seq": (raw["id_play"] if "id_play" in raw
                         else pd.to_numeric(raw["sequenceNumber"], errors="coerce")),
            "passer_player_name": raw["passer_player_name"],
        })
        df = df[df["game_id"].isin(game_rows)]
        df = df.sort_values(["game_id", "drive_id", "play_seq"])
        drv = (df.dropna(subset=["drive_id"])
               .groupby(["game_id", "pos_team"])["drive_id"].nunique()
               .rename("drives").reset_index())
        # a dropback is any play with a recorded passer (uniform across
        # dialects); the recorded primary passer is the first of the game
        pas = df[df["passer_player_name"].notna()]
        first_qb = (pas.groupby(["game_id", "pos_team"])["passer_player_name"]
                    .first().rename("qb_first").reset_index())
        tg = drv.merge(first_qb, on=["game_id", "pos_team"], how="left")
        frames.append(tg)
    tg = pd.concat(frames, ignore_index=True)
    rows = []
    for _, t in tg.iterrows():
        g = game_rows.get(int(t["game_id"]))
        if g is None:
            continue
        home = norm(g["home_team"]) == norm(t["pos_team"])
        away = norm(g["away_team"]) == norm(t["pos_team"])
        if not (home or away):
            continue
        rows.append({
            "season": int(g["season"]), "week": int(g["week"]),
            "game_id": int(t["game_id"]), "team": t["pos_team"],
            "opponent": g["away_team"] if home else g["home_team"],
            "is_home": bool(home),
            "team_division": g["home_division"] if home else g["away_division"],
            "opp_division": g["away_division"] if home else g["home_division"],
            "points": float(g["home_points"] if home else g["away_points"]),
            "drives": float(t["drives"]), "qb_first": t["qb_first"],
            "home_team": g["home_team"], "away_team": g["away_team"],
        })
    out = pd.DataFrame(rows)
    out["points_allowed"] = (out.groupby(["season", "game_id"])["points"]
                             .transform("sum") - out["points"])
    out["ppd"] = out["points"] / out["drives"]
    out["ppd_allowed"] = out["points_allowed"] / out["drives"]
    return out.sort_values(["season", "week", "game_id", "team"]).reset_index(drop=True)


def build_closes(sched_all: pd.DataFrame) -> pd.DataFrame:
    """Collector exclusion discipline (scripts/collect_cfb_sdv_closes.py)."""
    bet = pd.concat(
        [load_csv_gz(DATA / f"betting_{y}.csv.gz") for y in SEASONS],
        ignore_index=True)
    bet["game_id"] = bet["game_id"].astype(int)
    m = bet.merge(sched_all, on="game_id", how="inner", suffixes=("", "_s"))
    m["excl"] = ""
    m.loc[m["odds_source"] == "default", "excl"] = "E1_PLACEHOLDER_DEFAULT_SOURCE"
    m.loc[(m.excl == "") & m["home_team_spread"].isna(), "excl"] = "E2_NO_SPREAD_VALUE"
    m.loc[(m.excl == "") & m["over_under"].isna(), "excl"] = "E3_NO_TOTAL_VALUE"
    m.loc[(m.excl == "") & ~as_bool(m["game_spread_available"]),
          "excl"] = "E4_SPREAD_FLAGGED_UNAVAILABLE"
    notdone = (~as_bool(m["completed"])) | m["home_points"].isna() | m["away_points"].isna()
    m.loc[(m.excl == "") & notdone, "excl"] = "E5_NOT_COMPLETED"
    m["scoreable"] = m.excl == ""
    return m


# ------------------------------------------------------------------- screen
def shrink_rate(rate_sum: float, n: int, pool_rate: float) -> float:
    if n <= 0:
        return pool_rate
    w = n / (n + POOL_K)
    return w * (rate_sum / n) + (1 - w) * pool_rate


def predict_all(tg: pd.DataFrame) -> pd.DataFrame:
    """Walk-forward predictions for every season (machinery eligibility:
    >=3 prior games per team within the season, R8 week keying)."""
    pools = {}
    for y in sorted(tg["season"].unique()):
        sub = tg[tg["season"] == y]
        pools[y] = {
            "off_ppd": sub.groupby("team")["ppd"].mean().to_dict(),
            "def_ppd": sub.groupby("team")["ppd_allowed"].mean().to_dict(),
        }
    preds = []
    for season in SEASONS:
        season_games = tg[tg["season"] == season]
        pool_src = pools.get(season - 1, {})
        for (week, game_id), game in season_games.groupby(["week", "game_id"]):
            if len(game) != 2:
                continue
            hist = tg[(tg["season"] == season) & (tg["week"] < week)]
            if len(hist) == 0:
                continue
            lg_drv = float(hist["drives"].mean())
            lg_ppd = float(hist["ppd"].mean())
            lg_pts = hist["points"].mean()
            recs = {}
            ok = True
            for _, t in game.iterrows():
                th = hist[hist["team"] == t["team"]]
                oh = hist[hist["team"] == t["opponent"]]
                if len(th) < 3 or len(oh) < 3:
                    ok = False
                    break
                pool_off = 0.5 * pool_src.get("off_ppd", {}).get(t["team"], lg_ppd) \
                    + 0.5 * lg_ppd
                pool_def = 0.5 * pool_src.get("def_ppd", {}).get(t["opponent"], lg_ppd) \
                    + 0.5 * lg_ppd
                off_ppd = shrink_rate(th["ppd"].sum(), len(th), pool_off)
                def_ppd = shrink_rate(oh["ppd_allowed"].sum(), len(oh), pool_def)
                off_drv = shrink_rate(th["drives"].sum(), len(th), lg_drv)
                def_drv = shrink_rate(oh["drives"].sum(), len(oh), lg_drv)
                proj_drives = 0.5 * (off_drv + def_drv)          # R1
                ppd = off_ppd * def_ppd / lg_ppd if lg_ppd > 0 else lg_ppd  # R2
                recs[t["team"]] = {
                    "season": season, "week": int(week),
                    "game_id": int(game_id), "team": t["team"],
                    "opponent": t["opponent"], "is_home": bool(t["is_home"]),
                    "actual": float(t["points"]), "mean": float(proj_drives * ppd),
                    "b1": float(th["points"].mean()), "b2": float(lg_pts),
                    "qb_first": t["qb_first"], "home_team": t["home_team"],
                    "away_team": t["away_team"],
                    "team_division": t["team_division"],
                    "opp_division": t["opp_division"],
                }
            if ok:
                preds.extend(recs.values())
    return pd.DataFrame(preds)


def fit_dispersion(train: pd.DataFrame) -> tuple[float, int]:
    mu = np.clip(train["mean"].to_numpy(), 1e-6, None)
    yv = train["actual"].to_numpy()

    def nll(log_r):
        r = np.exp(log_r)
        return -float(np.sum(stats.nbinom.logpmf(yv, r, r / (r + mu))))

    res = minimize_scalar(nll, bounds=(np.log(0.5), np.log(500.0)),
                          method="bounded")
    return float(np.exp(res.x)), int(len(train))


def run_screen(tg: pd.DataFrame, closes: pd.DataFrame,
               sched_all: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    preds_all = predict_all(tg)
    scoreable = closes[closes["scoreable"]][
        ["game_id", "home_team_spread", "over_under"]]
    close_map = {int(r.game_id): (float(r.home_team_spread), float(r.over_under))
                 for r in scoreable.itertuples()}

    def implied(row):
        c = close_map.get(int(row["game_id"]))
        if c is None:
            return np.nan
        spread, total = c
        s_close = -spread  # sign convention proven at pin time (report S3)
        return (total + s_close) / 2 if row["is_home"] else (total - s_close) / 2

    # QB stratum: recorded primary passer vs the team's prior game (R: PBP)
    tg_sorted = tg.sort_values(["season", "week", "game_id"])
    prev_qb, qb_changed = {}, {}
    for _, t in tg_sorted.iterrows():
        key = (int(t["season"]), t["team"])
        qb_changed[(int(t["game_id"]), t["team"])] = (
            key in prev_qb and pd.notna(t["qb_first"])
            and pd.notna(prev_qb[key]) and t["qb_first"] != prev_qb[key])
        prev_qb[key] = t["qb_first"]

    df = preds_all[preds_all["season"].isin(EVAL_SEASONS)].copy()
    df["bmkt"] = df.apply(implied, axis=1)
    df["qb_changed"] = [qb_changed.get((g, t), False)
                        for g, t in zip(df["game_id"], df["team"])]

    season_of_game = dict(zip(sched_all["game_id"].astype(int),
                              sched_all["season"].astype(int)))
    closes = closes.copy()
    closes["game_season"] = closes["game_id"].map(season_of_game)
    bet_eval = closes[closes["game_season"].isin(EVAL_SEASONS)]
    excl = {
        "published_betting_rows_eval_seasons": int(len(bet_eval)),
        "excl_by_code_eval_seasons": {k: int(v) for k, v in
                                      bet_eval.loc[bet_eval.excl != "", "excl"]
                                      .value_counts().items()},
        "scoreable_closes_eval_seasons": int(bet_eval["scoreable"].sum()),
        "completed_schedule_rows_all_div": int(as_bool(sched_all["completed"]).sum()),
    }
    fbs = sched_all[(sched_all["home_division"] == "fbs")
                    & (sched_all["away_division"] == "fbs")]
    excl["fbs_vs_fbs_results"] = int(len(fbs))
    il_mask = fbs["home_team"].map(norm).isin(IL_COLLEGE_NAMES) \
        | fbs["away_team"].map(norm).isin(IL_COLLEGE_NAMES)
    excl["illinois_college_games"] = int(il_mask.sum())
    excl["fbs_before_week5_after_il"] = int((fbs[~il_mask]["week"] < 5).sum())

    keep = (
        (df["team_division"] == "fbs") & (df["opp_division"] == "fbs")
        & (df["week"] >= 5)
        & ~df["home_team"].map(norm).isin(IL_COLLEGE_NAMES)
        & ~df["away_team"].map(norm).isin(IL_COLLEGE_NAMES))
    df = df[keep].copy()
    excl["cohort_rows_before_close_filter"] = int(len(df))
    excl["rows_dropped_no_close"] = int(df["bmkt"].isna().sum())
    df = df.dropna(subset=["bmkt"]).reset_index(drop=True)
    excl["cohort_games"] = int(df["game_id"].nunique())
    excl["cohort_rows"] = int(len(df))

    # dispersion per eval season: MLE on walk-forward predictions from
    # strictly earlier seasons only (design 2.1 / R6)
    disp, fit_rows = {}, {}
    for season in EVAL_SEASONS:
        train = preds_all[preds_all["season"] < season]
        disp[season], fit_rows[season] = fit_dispersion(train)
    df["disp_r"] = df["season"].map(disp)

    def nb_crps(mu, r, y):
        hi = int(max(y, mu + 8 * np.sqrt(mu + mu * mu / r))) + 40
        ks = np.arange(0, hi)
        cdf = stats.nbinom.cdf(ks, r, r / (r + mu))
        obs = (ks >= y).astype(float)
        return float(np.sum((cdf - obs) ** 2))

    df["crps_m"] = [nb_crps(m, r, y) for m, r, y in
                    zip(df["mean"], df["disp_r"], df["actual"])]
    p = df["disp_r"] / (df["disp_r"] + df["mean"])
    df["lo80"] = stats.nbinom.ppf(0.10, df["disp_r"], p)
    df["hi80"] = stats.nbinom.ppf(0.90, df["disp_r"], p)
    df["cover80"] = ((df["actual"] >= df["lo80"])
                     & (df["actual"] <= df["hi80"])).astype(float)
    df.to_csv(OUT / "predictions.csv", index=False)
    return df, {"exclusions": excl,
                "dispersion": {int(k): v for k, v in disp.items()},
                "dispersion_fit_rows": {int(k): v for k, v in fit_rows.items()}}


def summarize(df: pd.DataFrame) -> dict:
    def beta_of(d):
        x = (d["mean"] - d["bmkt"]).to_numpy()
        yv = (d["actual"] - d["bmkt"]).to_numpy()
        X = np.column_stack([np.ones_like(x), x])
        coef, *_ = np.linalg.lstsq(X, yv, rcond=None)
        return float(coef[1])

    def block(d):
        return {
            "games": int(d["game_id"].nunique()), "rows": int(len(d)),
            "beta": beta_of(d),
            "mae_m": float((d["mean"] - d["actual"]).abs().mean()),
            "mae_bmkt": float((d["bmkt"] - d["actual"]).abs().mean()),
            "mae_b1": float((d["b1"] - d["actual"]).abs().mean()),
            "mae_b2": float((d["b2"] - d["actual"]).abs().mean()),
            "crps_m": float(d["crps_m"].mean()),
            "coverage80": float(d["cover80"].mean()),
        }

    pooled = block(df)
    per = {int(y): block(d) for y, d in df.groupby("season")}
    rng = np.random.default_rng(20261028)
    games = df["game_id"].unique()
    gd = {g: d for g, d in df.groupby("game_id")}
    deltas, betas = [], []
    for _ in range(2000):
        samp = rng.choice(games, size=len(games), replace=True)
        dd = pd.concat([gd[g] for g in samp], ignore_index=True)
        deltas.append(float((dd["mean"] - dd["actual"]).abs().mean()
                            - (dd["bmkt"] - dd["actual"]).abs().mean()))
        betas.append(beta_of(dd))
    pooled["delta_mae_m_minus_bmkt"] = float(
        (df["mean"] - df["actual"]).abs().mean()
        - (df["bmkt"] - df["actual"]).abs().mean())
    pooled["delta_mae_ci95"] = [float(np.percentile(deltas, 2.5)),
                                float(np.percentile(deltas, 97.5))]
    pooled["beta_ci95"] = [float(np.percentile(betas, 2.5)),
                           float(np.percentile(betas, 97.5))]
    qs = df[df["qb_changed"]]
    pooled["qb_stratum"] = {
        "rows": int(len(qs)),
        "beta": beta_of(qs) if len(qs) > 10 else None,
        "mae_m": float((qs["mean"] - qs["actual"]).abs().mean()) if len(qs) else None,
        "mae_bmkt": float((qs["bmkt"] - qs["actual"]).abs().mean()) if len(qs) else None,
    }
    crit = {
        "leg1_beta_ge_0.10": bool(pooled["beta"] >= 0.10),
        "leg2_beta_pos_2of3": bool(sum(1 for v in per.values() if v["beta"] > 0) >= 2),
        "leg3_mae": bool(pooled["mae_m"] <= pooled["mae_bmkt"] + 0.5
                         and pooled["mae_m"] < pooled["mae_b1"]
                         and pooled["mae_m"] < pooled["mae_b2"]),
        "leg4_100_games_per_season": bool(all(v["games"] >= 100 for v in per.values())),
        "leg5_coverage_band": bool(0.72 <= pooled["coverage80"] <= 0.88),
    }
    return {"pooled": pooled, "per_season": per, "criteria": crit,
            "verdict": "SCREEN_PASS" if all(crit.values()) else "SCREEN_FAIL"}


def main():
    sched_all = load_schedules()
    tg = build_team_games(sched_all)
    closes = build_closes(sched_all)
    df, meta = run_screen(tg, closes, sched_all)
    summary = summarize(df)
    record = {"engine": "CFB_TEAM_TOTAL_POSSESSION_V1", **summary, **meta}
    (OUT / "final_screen_summary.json").write_text(json.dumps(record, indent=1))
    print(json.dumps({"verdict": summary["verdict"],
                      "criteria": summary["criteria"],
                      "pooled": {k: summary["pooled"][k] for k in
                                 ("games", "rows", "beta", "mae_m", "mae_bmkt",
                                  "mae_b1", "mae_b2", "crps_m", "coverage80",
                                  "qb_stratum")},
                      "per_season": summary["per_season"],
                      "dispersion": meta["dispersion"],
                      "exclusions": meta["exclusions"]}, indent=1))


if __name__ == "__main__":
    main()
