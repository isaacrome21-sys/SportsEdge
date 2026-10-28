#!/usr/bin/env python3
"""DESIGN SCREEN — NFL team totals + period lines activation package.

Status: DESIGN SCREEN ONLY. A screen is an entry ticket, never validation
(standing program law). All seasons screened here (2020-2025 team totals,
2023-2025 period lines) are DESIGN data: they were seen by retired NFL
constructions. Nothing in this script prices a live game, starts a clock,
or issues a verdict against a market. The market-baseline legs of the
families' validation live in their forward preregistrations, scored on
timestamped DraftKings captures after an owner freeze.

Constructions screened (exactly as specified in the sibling design docs):

  NFL_TEAM_TOTAL_DIST_V1
    For team T vs opponent O, using only games completed before the game:
      sample(T)  = T's same-season prior games, supplemented by T's most
                   recent prior-season games until the sample reaches 8
                   games (or history exhausts).
      G          = mean team score over strictly earlier weeks of the
                   season (previous season's league mean in week 1).
      off_T      = (sum of T's sample scores + K * G) / (n + K), K = 3.
      def_O      = same form on O's sample points-allowed.
      mu_T       = off_T * def_O / G.
      dist_T     = NegativeBinomial(mu_T, var = (c * mu_T)^2), Poisson
                   where var <= mu; c = pooled CV of (score / mu) over
                   the 2018-2019 training seasons only.
    Baselines: B1 = team's unshrunk sample mean (same sample, no
    opponent adjustment, no shrinkage) with the same NB form;
    B2 = league mean G with the same NB form.
    Market reference (DESIGN-ONLY, never a verdict): the implied team
    total from the nflverse closing snapshot, (total +/- spread)/2.
    nflverse closes are one untimestamped snapshot per game (gap G7):
    beating or losing to the implied split here is a design diagnostic,
    not CLV and not a market verdict. The spread sign convention is
    proven empirically inside the run, never assumed.

  NFL_PERIOD_SHARE_V1 (period means only; the distribution layer is the
  team-total distribution scaled by share, as specified in the design)
      mu_T,q = mu_T * s_T,q
      s_T,q  = (T's sample period-q points + Ks * L_q) /
               (T's sample total points + Ks),  Ks = 150 points,
      L_q    = league point-in-time period share (points in q / all
               points, strictly earlier games of the season, previous
               season's shares in week 1).
    Baselines: B0 = mu_T * L_q (league shares, no team information);
    B1 = flat split of mu_T (0.25 per quarter, 0.50 per half -- the
    unfitted convention of sportsedge/team_half_pricing.py).

Screen pass criteria (fixed before the run; recorded in the report):
  Team totals: pooled 2020-2025 candidate MAE < B1 and < B2 AND pooled
    CRPS < B1 and < B2 AND no test season with candidate MAE worse than
    B2 MAE by more than 0.25 points.
  Periods: pooled MAE across the six buckets (Q1..Q4, 1H, 2H) <
    B0 and < B1 AND candidate MAE < B0 MAE in at least 4 of 6 buckets.

Inputs (free, public; pulled by this script into a local cache and
hash-recorded in the output -- the release assets are rolling, so the
hash of the pull actually used is the provenance):
  nflverse schedules: https://github.com/nflverse/nflverse-data/
    releases/download/schedules/games.csv.gz
  nflverse play-by-play (period panel only):
    .../releases/download/pbp/play_by_play_{season}.parquet
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import urllib.request
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import stats

K_SHRINK = 3.0          # Part 2 shrinkage form, K = 3
SAMPLE_CAP = 8          # prior-season supplement cap (games)
KS_POINTS = 150.0       # period-share shrinkage, in points
TRAIN_SEASONS = (2018, 2019)
TT_TEST_SEASONS = tuple(range(2020, 2026))
PERIOD_TEST_SEASONS = (2023, 2024, 2025)
MAX_SCORE = 120

SCHEDULES_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "schedules/games.csv.gz"
)
PBP_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "pbp/play_by_play_{season}.parquet"
)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(cache_dir: str, name: str, url: str) -> tuple[str, str]:
    path = os.path.join(cache_dir, name)
    if not os.path.exists(path):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
        with open(path, "wb") as fh:
            fh.write(data)
    with open(path, "rb") as fh:
        return path, sha256_hex(fh.read())


def nb_cdf_grid(mu: float, c: float) -> np.ndarray:
    """CDF values F(k) for k = 0..MAX_SCORE of the construction's NB."""
    var = (c * mu) ** 2
    ks = np.arange(0, MAX_SCORE + 1)
    if var <= mu or mu <= 0:
        return stats.poisson.cdf(ks, max(mu, 1e-9))
    r = mu * mu / (var - mu)
    p = r / (r + mu)
    return stats.nbinom.cdf(ks, r, p)


def crps_from_cdf(cdf: np.ndarray, x: int) -> float:
    ks = np.arange(0, MAX_SCORE + 1)
    return float(np.sum((cdf - (x <= ks)) ** 2))


class WalkForward:
    """Point-in-time team scoring state over the schedules file."""

    def __init__(self, games: pd.DataFrame) -> None:
        reg = games[(games["game_type"] == "REG")
                    & games["home_score"].notna()
                    & games["away_score"].notna()].copy()
        reg = reg.sort_values(["season", "week", "gameday", "game_id"])
        self.games = reg.reset_index(drop=True)
        # team -> list of (season, score_for, score_against), chronological
        self.history: dict[str, list[tuple[int, int, int]]] = {}
        # season -> list of team scores in completed weeks of that season
        self.season_scores: dict[int, list[int]] = {}
        self.season_league_mean: dict[int, float] = {}
        self.mu_by_game_team: dict[tuple[str, str], float] = {}

    def league_mean(self, season: int, week: int) -> float:
        prior = self.season_scores.get(season, [])
        if prior:
            return float(np.mean(prior))
        # week-1 fallback: previous season's full league mean (Part 2 form)
        prev = self.season_league_mean.get(season - 1)
        if prev is None:
            prev = float(np.mean([sf for _, sf, _ in
                                  sum(self.history.values(), [])])) \
                if self.history else 22.0
        return float(prev)

    def sample(self, team: str, season: int) -> list[tuple[int, int, int]]:
        hist = self.history.get(team, [])
        same = [h for h in hist if h[0] == season]
        if len(same) >= SAMPLE_CAP:
            return same[-SAMPLE_CAP:]
        prior = [h for h in hist if h[0] < season]
        need = SAMPLE_CAP - len(same)
        return prior[-need:] + same if need > 0 else same

    def shrunk_mean(self, values: list[float], g: float) -> float:
        n = len(values)
        return (sum(values) + K_SHRINK * g) / (n + K_SHRINK)

    def mu_for(self, team: str, opp: str, season: int, week: int) -> tuple[float, float, float]:
        g = self.league_mean(season, week)
        s_t = self.sample(team, season)
        s_o = self.sample(opp, season)
        off = self.shrunk_mean([h[1] for h in s_t], g)
        dfn = self.shrunk_mean([h[2] for h in s_o], g)
        return off * dfn / g, off, g

    def record_game(self, row) -> None:
        season, week = int(row.season), int(row.week)
        hs, as_ = int(row.home_score), int(row.away_score)
        self.history.setdefault(row.home_team, []).append((season, hs, as_))
        self.history.setdefault(row.away_team, []).append((season, as_, hs))
        self.season_scores.setdefault(season, []).extend([hs, as_])


def run_team_total_screen(wf: WalkForward) -> dict:
    rows = []
    train_ratios = []
    # Process every game in order; predictions use only prior state.
    for row in wf.games.itertuples():
        season, week = int(row.season), int(row.week)
        for team, opp, score in (
            (row.home_team, row.away_team, int(row.home_score)),
            (row.away_team, row.home_team, int(row.away_score)),
        ):
            mu, _off, g = wf.mu_for(team, opp, season, week)
            if season in TRAIN_SEASONS:
                train_ratios.append(score / mu if mu > 0 else np.nan)
            if season in TT_TEST_SEASONS:
                s_t = wf.sample(team, season)
                b1 = float(np.mean([h[1] for h in s_t])) if s_t else g
                rows.append({
                    "season": season, "week": week, "game_id": row.game_id,
                    "team": team, "score": score, "mu": mu, "b1": b1, "b2": g,
                    "spread_line": row.spread_line, "total_line": row.total_line,
                    "is_home": team == row.home_team,
                })
            if (row.game_id, team) not in wf.mu_by_game_team:
                wf.mu_by_game_team[(row.game_id, team)] = mu
        wf.record_game(row)
        if week == int(wf.games[wf.games.season == season].week.max()):
            sc = wf.season_scores.get(season, [])
            if sc:
                wf.season_league_mean[season] = float(np.mean(sc))

    c = float(np.nanstd(np.array(train_ratios), ddof=0))
    df = pd.DataFrame(rows)
    # Empirical spread-sign proof: realized home margin vs spread_line.
    gdf = wf.games[wf.games.season.isin(TT_TEST_SEASONS)].copy()
    gdf = gdf.dropna(subset=["spread_line", "total_line"])
    margin = gdf["home_score"] - gdf["away_score"]
    corr = float(np.corrcoef(gdf["spread_line"], margin)[0, 1])
    sign = 1.0 if corr > 0 else -1.0
    implied = {}
    for r in gdf.itertuples():
        imp_margin = sign * float(r.spread_line)
        implied[(r.game_id, r.home_team)] = (float(r.total_line) + imp_margin) / 2
        implied[(r.game_id, r.away_team)] = (float(r.total_line) - imp_margin) / 2
    df["implied"] = [implied.get((gid, t)) for gid, t in zip(df.game_id, df.team)]

    def metrics(d: pd.DataFrame) -> dict:
        out = {"n": int(len(d))}
        for col in ("mu", "b1", "b2"):
            out[f"mae_{col}"] = float(np.mean(np.abs(d[col] - d["score"])))
        sub = d.dropna(subset=["implied"])
        out["n_implied"] = int(len(sub))
        out["mae_implied"] = float(np.mean(np.abs(sub["implied"] - sub["score"])))
        cr = {"mu": [], "b1": [], "b2": []}
        pit = []
        inside90 = []
        for r in d.itertuples():
            for col in ("mu", "b1", "b2"):
                cr[col].append(crps_from_cdf(
                    nb_cdf_grid(getattr(r, col), c), r.score))
            cdf = nb_cdf_grid(r.mu, c)
            pit.append(float(cdf[min(r.score, MAX_SCORE)]))
            lo = int(np.searchsorted(cdf, 0.05))
            hi = int(np.searchsorted(cdf, 0.95))
            inside90.append(lo <= r.score <= hi)
        for col in ("mu", "b1", "b2"):
            out[f"crps_{col}"] = float(np.mean(cr[col]))
        out["pit_mean"] = float(np.mean(pit))
        out["inside90_share"] = float(np.mean(inside90))
        return out

    pooled = metrics(df)
    per_season = {int(s): metrics(d) for s, d in df.groupby("season")}
    passed = (
        pooled["mae_mu"] < pooled["mae_b1"]
        and pooled["mae_mu"] < pooled["mae_b2"]
        and pooled["crps_mu"] < pooled["crps_b1"]
        and pooled["crps_mu"] < pooled["crps_b2"]
        and all(per_season[s]["mae_mu"] <= per_season[s]["mae_b2"] + 0.25
                for s in per_season)
    )
    return {
        "construction": "NFL_TEAM_TOTAL_DIST_V1",
        "pooled_cv_c": c,
        "spread_sign_empirical": {"corr_spread_vs_home_margin": corr,
                                  "sign_applied": sign},
        "pooled": pooled,
        "per_season": per_season,
        "screen_pass": bool(passed),
    }


def build_period_panel(cache_dir: str, hashes: dict) -> pd.DataFrame:
    frames = []
    cols = ["game_id", "season", "week", "season_type", "qtr", "posteam",
            "home_team", "away_team", "posteam_score_post",
            "defteam_score_post", "play_id"]
    for season in PERIOD_TEST_SEASONS:
        path, h = fetch(cache_dir, f"pbp_{season}.parquet",
                        PBP_URL.format(season=season))
        hashes[f"pbp_{season}"] = h
        d = pd.read_parquet(path, columns=cols)
        frames.append(d[d["season_type"] == "REG"])
    pbp = pd.concat(frames, ignore_index=True)
    pbp = pbp[pbp["qtr"].isin([1, 2, 3, 4])].copy()
    # Running scores are non-decreasing within a game, so a quarter's end
    # state is the max cumulative score among that quarter's rows. (The
    # literal last row of a quarter is often a marker row with null
    # score-post fields; the scoring play itself always carries the
    # post-score, so the max is the true quarter-end state.)
    is_home = pbp["posteam"] == pbp["home_team"]
    pbp["home_cum"] = np.where(is_home, pbp["posteam_score_post"],
                               pbp["defteam_score_post"])
    pbp["away_cum"] = np.where(is_home, pbp["defteam_score_post"],
                               pbp["posteam_score_post"])
    last = pbp.groupby(["game_id", "qtr"]).agg(
        season=("season", "first"), week=("week", "first"),
        home_team=("home_team", "first"), away_team=("away_team", "first"),
        home_cum=("home_cum", "max"), away_cum=("away_cum", "max"),
    ).reset_index()
    recs = []
    for r in last.itertuples():
        recs.append({"game_id": r.game_id, "season": int(r.season),
                     "week": int(r.week), "qtr": int(r.qtr),
                     "home_team": r.home_team, "away_team": r.away_team,
                     "home_cum": float(r.home_cum),
                     "away_cum": float(r.away_cum)})
    cum = pd.DataFrame(recs)
    out = []
    for gid, grp in cum.groupby("game_id"):
        grp = grp.sort_values("qtr")
        home_team = grp.home_team.iloc[0]
        away_team = grp.away_team.iloc[0]
        season = int(grp.season.iloc[0])
        week = int(grp.week.iloc[0])
        prev_h = prev_a = 0.0
        qpts = {}
        for r in grp.itertuples():
            qpts[int(r.qtr)] = (r.home_cum - prev_h, r.away_cum - prev_a)
            prev_h, prev_a = r.home_cum, r.away_cum
        for q in (1, 2, 3, 4):
            if q not in qpts:
                qpts[q] = (0.0, 0.0)
        out.append({"game_id": gid, "season": season, "week": week,
                    "team": home_team,
                    **{f"q{q}": qpts[q][0] for q in (1, 2, 3, 4)}})
        out.append({"game_id": gid, "season": season, "week": week,
                    "team": away_team,
                    **{f"q{q}": qpts[q][1] for q in (1, 2, 3, 4)}})
    panel = pd.DataFrame(out)
    for q in (1, 2, 3, 4):
        panel[f"q{q}"] = panel[f"q{q}"].astype(float)
    return panel


def run_period_screen(wf: WalkForward, panel: pd.DataFrame) -> dict:
    # Point-in-time period shares: rebuild state chronologically from the
    # panel itself (period points are final at each game's end; a game's
    # own periods never enter its own prediction).
    panel = panel.sort_values(["season", "week", "game_id", "team"])
    team_periods: dict[str, list[tuple[int, np.ndarray]]] = {}
    season_period_pts: dict[int, np.ndarray] = {}
    season_total_pts: dict[int, float] = {}
    prev_season_share: dict[int, np.ndarray] = {}

    def league_share(season: int) -> np.ndarray:
        pts = season_period_pts.get(season)
        tot = season_total_pts.get(season, 0.0)
        if pts is not None and tot > 0:
            return pts / tot
        if (season - 1) in prev_season_share:
            return prev_season_share[season - 1]
        return np.array([0.25, 0.25, 0.25, 0.25])

    buckets = ["Q1", "Q2", "Q3", "Q4", "1H", "2H"]
    errs = {b: {"cand": [], "b0": [], "b1": []} for b in buckets}
    n_used = 0
    games_by_week = panel.groupby(["season", "week"])
    for (season, week), wk in games_by_week:
        l_share = league_share(int(season))
        for r in wk.itertuples():
            mu = wf.mu_by_game_team.get((r.game_id, r.team))
            if mu is None:
                continue
            hist = team_periods.get(r.team, [])
            same = [h for h in hist if h[0] == season]
            prior = [h for h in hist if h[0] < season]
            sample = (prior[-(SAMPLE_CAP - len(same)):] + same) \
                if len(same) < SAMPLE_CAP else same[-SAMPLE_CAP:]
            if sample:
                arr = np.array([h[1] for h in sample])
                s = (arr.sum(axis=0) + KS_POINTS * l_share) / \
                    (arr.sum() + KS_POINTS)
            else:
                s = l_share
            realized = np.array([r.q1, r.q2, r.q3, r.q4])
            cand = mu * s
            b0 = mu * l_share
            b1 = mu * np.array([0.25, 0.25, 0.25, 0.25])
            vals = {
                "Q1": (cand[0], b0[0], b1[0], realized[0]),
                "Q2": (cand[1], b0[1], b1[1], realized[1]),
                "Q3": (cand[2], b0[2], b1[2], realized[2]),
                "Q4": (cand[3], b0[3], b1[3], realized[3]),
                "1H": (cand[:2].sum(), b0[:2].sum(), b1[:2].sum(),
                       realized[:2].sum()),
                "2H": (cand[2:].sum(), b0[2:].sum(), b1[2:].sum(),
                       realized[2:].sum()),
            }
            for b, (cv, v0, v1, rv) in vals.items():
                errs[b]["cand"].append(abs(cv - rv))
                errs[b]["b0"].append(abs(v0 - rv))
                errs[b]["b1"].append(abs(v1 - rv))
            n_used += 1
        # only after the whole week is predicted do its games enter state
        for r in wk.itertuples():
            arr = np.array([r.q1, r.q2, r.q3, r.q4])
            team_periods.setdefault(r.team, []).append((int(season), arr))
            season_period_pts[int(season)] = \
                season_period_pts.get(int(season), np.zeros(4)) + arr
            season_total_pts[int(season)] = \
                season_total_pts.get(int(season), 0.0) + float(arr.sum())
        wk_games = wk.drop_duplicates("game_id")
        if len(wk_games):
            last_week = int(panel[panel.season == season].week.max())
            if int(week) == last_week:
                tot = season_total_pts.get(int(season), 0.0)
                if tot > 0:
                    prev_season_share[int(season)] = \
                        season_period_pts[int(season)] / tot

    out = {"n_team_games": n_used, "buckets": {}}
    pooled = {"cand": [], "b0": [], "b1": []}
    wins = 0
    for b in buckets:
        m = {k: float(np.mean(v)) for k, v in errs[b].items()}
        out["buckets"][b] = m
        pooled["cand"].extend(errs[b]["cand"])
        pooled["b0"].extend(errs[b]["b0"])
        pooled["b1"].extend(errs[b]["b1"])
        if m["cand"] < m["b0"]:
            wins += 1
    out["pooled_mae"] = {k: float(np.mean(v)) for k, v in pooled.items()}
    out["buckets_beating_b0"] = wins
    out["screen_pass"] = bool(
        out["pooled_mae"]["cand"] < out["pooled_mae"]["b0"]
        and out["pooled_mae"]["cand"] < out["pooled_mae"]["b1"]
        and wins >= 4
    )
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), ".screen_cache"))
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    os.makedirs(args.cache, exist_ok=True)
    hashes: dict[str, str] = {}
    gpath, gh = fetch(args.cache, "games.csv.gz", SCHEDULES_URL)
    hashes["games_csv_gz"] = gh
    games = pd.read_csv(gpath, low_memory=False)
    wf = WalkForward(games)
    tt = run_team_total_screen(wf)
    panel = build_period_panel(args.cache, hashes)
    per = run_period_screen(wf, panel)
    report = {
        "kind": "DESIGN_SCREEN",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs_sha256": hashes,
        "note": ("Design screen on seen seasons; entry ticket only, "
                 "never validation. See sibling design docs."),
        "team_totals": tt,
        "periods": per,
    }
    text = json.dumps(report, indent=1, default=float)
    out_path = args.out or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "screen_results_v1.json")
    with open(out_path, "w") as fh:
        fh.write(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
