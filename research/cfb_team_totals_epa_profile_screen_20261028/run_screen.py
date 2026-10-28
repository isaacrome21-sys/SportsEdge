#!/usr/bin/env python3
"""CFB_TEAM_TOTAL_EPA_PROFILE_V2 — historical design screen (ONE run).

Implements the screen fixed by
research/successor_designs_20261028/DESIGN_CFB_TEAM_TOTAL_EPA_PROFILE_V2.md
§5 (design merged in PR #2872) against the pass criteria of
research/cfb_activation_20261027/PREREG_CFB_TEAM_TOTALS_FORWARD_V1_DRAFT.md
§4.3, carried verbatim (no leg softer). The construction is the design's
§3: points per drive is a FITTED ridge map g() over play-level efficiency
profile differentials (the estimator the v1 design named and the v1
screen's reading R2 never fit), with the §3.3 prior-games-only
starter-continuity state interacting with the EPA differential and §3.4's
projected-drives term inside g. Machinery carried from the v1 screen
(PR #2861, research/cfb_team_totals_screen_20261028/run_screen.py):
cohort funnel, shrinkage/pool discipline, sign convention, dispersion
MLE form, interval/CRPS form, bootstrap, exclusion accounting.

Inputs (hash-pinned in PINS.json beside the report; byte-identical to
PR #2861's pins — all 15 verified at build):
  SDV cfb_schedules + espn_cfb_betting CSV releases, 2021–2025;
  cfbfastR play-by-play parquets, 2021–2025 (sportsdataverse-data mirror
  release cfbfastR_cfb_pbp 2022–2025; 2021 from the cfbfastR-data git
  tree at pbp/parquet/play_by_play_2021.parquet).
Inputs are staged in a data directory (env CFB_TT_V2_DATA, default
./data beside this runner; not committed — see PINS.json).
Outputs: predictions + run record under screen_out/ beside the runner
(scratch at run time); the committed run record is screen_results.json
beside the report.

Implementer readings — recorded BEFORE the run, in the open, mirroring
the v1 screen's R1–R8 discipline. The design fixes the construction's
form, feature list, cohort, and every criterion; where it delegates a
constant or leaves a functional form unspecified, the reading taken is
declared here and was not changed after any outcome was seen:

- V2-R1 (ridge penalty). Design §3.2 fixes g as a ridge with "penalty
  fixed in the screen spec, not swept"; §5 states no numeral. This
  screen spec fixes it: features standardized on the training fold
  (mean / sample sd, sd floored to 1 when degenerate), intercept
  unpenalized (fit on centered y), penalty lambda = 1.0 per
  standardized feature, closed-form solve. One value; no sweep.
- V2-R2 (profile rate discipline). Every §3.1 profile stat is a
  per-game rate (per play or per drive within the game), averaged over
  the team's qualifying prior games and shrunk with the v1 discipline
  verbatim: w = n/(n+3) toward a pool of 0.5 x prior-season final team
  rate + 0.5 x walk-forward league rate (league fallback), n = games
  contributing a defined value of that stat. Defense-allowed rates are
  the opponent's offensive aggregates, carried on the opponent's own
  team-game rows exactly as v1 carried ppd_allowed.
- V2-R3 (play/drive derivations, uniform across the two PBP dialects).
  Scrimmage play = pass or rush flag set (cfbfastR convention; sacks
  are dropbacks). EPA per play uses the pinned files' `EPA` column
  (the design's `ep` field as the pinned bytes name it), over plays
  with EPA recorded. Success = yards gained >= 50% of distance on
  1st down, >= 70% on 2nd, >= 100% on 3rd/4th (the cfbfastR rule; the
  mirror's shipped `success` column agrees with this rule on 99.48%
  of scrimmage plays — one computed rule is used in both dialects for
  uniformity; 2021 fields are start.down / start.distance /
  statYardage, yards to goal is start.yardsToEndzone). A drive is a
  distinct published drive identifier for the offense (v1 R3, no
  filtering). A drive is an Eckel if any of its plays starts with
  yards to goal <= 40; a red-zone trip at <= 20; a red-zone TD if
  the trip's drive result is a touchdown for the possessing team.
  Drive points (points-per-Eckel only; not an argument of g) map the
  drive result to possessing-team points at the modes of the mirror's
  published drive_pts per category (TD 7, FG 3, safety -2, return/
  defensive TD -7, else 0), applied uniformly in both dialects.
- V2-R4 (matchup forms). Differentials are shrunk off rate minus
  shrunk defense-allowed rate (EPA, success, explosiveness, Eckel,
  red-zone TD rate). RZ_trip_rate(i,j) takes the v1 R2 opponent-
  adjustment form: off x def-allowed / walk-forward league rate.
  projected_drives(i,j) is v1 R1 verbatim (arithmetic mean of the two
  teams' shrunk drives-per-game, each shrunk toward the walk-forward
  league drives rate). g's arguments are exactly the design §3.2 list
  plus the §3.3 interaction continuity_i x EPA differential; §3.1's
  remaining profile components (EPA split dropback/rush, points per
  Eckel, plays per drive) are computed on every team-game row as
  profile record and are not arguments of g, whose feature list the
  design fixes. Seconds per play enters nothing: v1's pace blend —
  carried here — is drives-per-game based.
- V2-R5 (training universe). The map is fit per evaluation fold on
  machinery team-games (both teams >= 3 qualifying in-season priors,
  the v1 predict universe) from seasons strictly before the
  evaluation season, targets = realized points per drive. The
  Illinois exclusion and the FBS/Week-5/close filters define the
  SCORED cohort exactly as in v1; training fits use the machinery
  universe, as v1's dispersion fit did (its fit rows were the
  unfiltered walk-forward predictions of earlier seasons).
- V2-R6 (dispersion). §3.5's "walk-forward predictions over training
  seasons only" with a fitted map means no training row is predicted
  by a map that saw its season: per evaluation fold E, for each
  training season Y >= 2022 with Y < E, the map is fit on machinery
  rows from seasons < Y and predicts season Y; the pooled
  out-of-season predictions feed v1's bounded NB MLE verbatim, one
  pooled r per fold.
- V2-R7 (continuity state). Within-season, per §3.3: the team's
  passer sequence is its team-game rows in (week, game_id) order
  (the v1 §4.4 stratum sequence); continuity = 1 if the first-
  dropback passer of the most recent prior game equals that of the
  game before it, 0 if both are recorded and differ. Where undefined
  (missing passer or fewer than two prior games) the state takes the
  pool value: walk-forward league mean of defined continuity in
  earlier weeks of the season, else the prior season's league rate,
  else 0.5; fallback use is flagged per row and counted. Machinery
  rows always have >= 3 priors, so the raw state is defined unless a
  prior game's passer is unrecorded.
- V2-R8 (fitted ppd floor). A linear map can return a negative
  points-per-drive; predictions are floored at 0.0 (a domain bound,
  declared here before the run; bindings are counted in the record).
- Cohort-identity gate (design §7). Before any outcome statistic is
  computed, the cohort funnel must reproduce PR #2861's run of record
  exactly (1,586 games / 3,172 rows; per-season games 512/532/542;
  scoreable closes 2,781; 3,176 rows before the close filter). On any
  mismatch the runner writes a NOT_EXECUTABLE record and exits
  without fitting or scoring: inputs that cannot reproduce the
  predecessor cohort are not stable enough to screen on.
- V2-R9 (2021 dialect team identity — repairs a silent predecessor
  hole). The pinned 2021 tree file keys pos_team by ESPN team ID, not
  by name; the v1 screen's name matching therefore produced ZERO
  2021 team-games (its published dispersion fit rows decompose as
  2022-only for the 2023 fold: 1,212 = the 2022 machinery count).
  The pinned schedules carry home_id / away_id from the same source;
  this runner additionally matches pos_team against those IDs (the
  schedule's canonical name is stored for ID-matched rows). Proven
  on the pinned bytes before the run: the file covers 840 schedule
  games; in 839 the pos_team IDs are exactly a subset of
  {home_id, away_id} (one game carries a stray ID whose rows match
  neither side and are dropped, as any unmatched row is). This is
  input-layer dialect normalization of the same kind as V2-R3's
  field mappings; it changes no criterion and no evaluation row —
  2023–2025 features never read 2021 rows (in-season hist + the
  prior season's pool only) — and the cohort gate above re-verifies
  identity after it. It restores the design §4 training reach to
  2021 and makes V2-R6 executable as declared; the alternative
  (replicating the hole) would void both.
"""
from __future__ import annotations

import gzip
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize_scalar

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(REPO))
from artifacts.free_models import IL_COLLEGE_NAMES  # design §3.7 source

DATA = Path(os.environ.get("CFB_TT_V2_DATA", ROOT / "data"))
OUT = ROOT / "screen_out"
OUT.mkdir(parents=True, exist_ok=True)
SEASONS = [2021, 2022, 2023, 2024, 2025]
EVAL_SEASONS = [2023, 2024, 2025]
POOL_K = 3.0  # v1 design §2.3 constant, fixed, carried verbatim
RIDGE_LAMBDA = 1.0  # V2-R1: fixed by this screen spec; not swept
BOOT_SEED = 20261028  # v1 screen's bootstrap seed, carried
BOOT_N = 2000

FEATURES = ["epa_diff", "success_diff", "explosive_diff", "eckel_diff",
            "rz_trip_mu", "rz_td_diff", "proj_drives", "cont_x_epa"]
PROFILE_STATS = ["epa_per_play", "epa_db", "epa_rush", "success_rate",
                 "explosive_rate", "eckel_rate", "pp_eckel",
                 "rz_trip_rate", "rz_td_rate"]
# possession-team points by drive result (V2-R3)
DRIVE_PTS = {"TD": 7.0, "FG": 3.0, "SF": -2.0, "INT TD": -7.0,
             "FUMBLE RETURN TD": -7.0, "FUMBLE TD": -7.0, "PUNT TD": -7.0,
             "PUNT RETURN TD": -7.0, "MISSED FG TD": -7.0,
             "DOWNS TD": -7.0, "END OF HALF TD": 7.0}

# PR #2861 run of record (research/cfb_team_totals_screen_20261028/
# screen_results.json): the cohort-identity gate values.
EXPECTED = {
    "published_betting_rows_eval_seasons": 2835,
    "scoreable_closes_eval_seasons": 2781,
    "cohort_rows_before_close_filter": 3176,
    "rows_dropped_no_close": 4,
    "cohort_games": 1586,
    "cohort_rows": 3172,
    "games_per_season": {2023: 512, 2024: 532, 2025: 542},
}


def norm(name) -> str:
    return " ".join(str(name or "").strip().lower().replace(".", "").split())


def _idstr(v) -> str:
    """Canonical string for an ESPN team id (int-like -> its digits)."""
    try:
        return str(int(float(v)))
    except (TypeError, ValueError):
        return str(v).strip()


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


def build_closes(sched_all: pd.DataFrame) -> pd.DataFrame:
    """Collector exclusion discipline (scripts/collect_cfb_sdv_closes.py).
    Verbatim from the v1 screen runner (PR #2861)."""
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


# ---------------------------------------------------------------- data build
def as_flag(s: pd.Series) -> pd.Series:
    return s.astype(float).fillna(0.0) >= 0.5


def success_value(df: pd.DataFrame) -> pd.Series:
    """cfbfastR success rule (V2-R3); NaN where inputs are undefined."""
    down, dist, yds = df["down"], df["distance"], df["yards"]
    need = np.where(down == 1, 0.5 * dist,
                    np.where(down == 2, 0.7 * dist,
                             np.where(down >= 3, dist, np.nan)))
    ok = down.notna() & dist.notna() & yds.notna()
    return pd.Series(np.where(ok, (yds >= need).astype(float), np.nan),
                     index=df.index)


def load_plays(season: int, scope_ids: set) -> pd.DataFrame:
    """One season of PBP normalized across the two pinned dialects."""
    raw = pd.read_parquet(DATA / f"play_by_play_{season}.parquet")
    if "drive_id" in raw.columns:  # sportsdataverse-data mirror dialect
        df = pd.DataFrame({
            "game_id": raw["game_id"].astype(int),
            "pos_team": raw["pos_team"],
            "drive_key": raw["drive_id"],
            "play_seq": pd.to_numeric(raw["id_play"], errors="coerce"),
            "passer": raw["passer_player_name"],
            "epa": pd.to_numeric(raw["EPA"], errors="coerce"),
            "is_pass": as_flag(raw["pass"]),
            "is_rush": as_flag(raw["rush"]),
            "down": pd.to_numeric(raw["down"], errors="coerce"),
            "distance": pd.to_numeric(raw["distance"], errors="coerce"),
            "yards": pd.to_numeric(raw["yards_gained"], errors="coerce"),
            "ytg": pd.to_numeric(raw["yards_to_goal"], errors="coerce"),
            "drive_result": raw["drive_result"],
        })
    else:  # 2021 cfbfastR-data git-tree dialect
        df = pd.DataFrame({
            "game_id": raw["game_id"].astype(int),
            "pos_team": raw["pos_team"],
            "drive_key": raw["drive.id"],
            "play_seq": pd.to_numeric(raw["sequenceNumber"],
                                      errors="coerce"),
            "passer": raw["passer_player_name"],
            "epa": pd.to_numeric(raw["EPA"], errors="coerce"),
            "is_pass": as_flag(raw["pass"]),
            "is_rush": as_flag(raw["rush"]),
            "down": pd.to_numeric(raw["start.down"], errors="coerce"),
            "distance": pd.to_numeric(raw["start.distance"],
                                      errors="coerce"),
            "yards": pd.to_numeric(raw["statYardage"], errors="coerce"),
            "ytg": pd.to_numeric(raw["start.yardsToEndzone"],
                                 errors="coerce"),
            "drive_result": raw["drive.result"],
        })
    df = df[df["game_id"].isin(scope_ids)]
    return df.sort_values(["game_id", "play_seq"]).reset_index(drop=True)


def aggregate_game_plays(df: pd.DataFrame) -> pd.DataFrame:
    """Per (game_id, pos_team): §3.1 profile aggregates + drive facts."""
    scr = df[df["is_pass"] | df["is_rush"]].copy()
    scr["succ"] = success_value(scr)
    g = scr.groupby(["game_id", "pos_team"])
    agg = pd.DataFrame({
        "scr_n": g.size(),
        "epa_n": g["epa"].count(), "epa_sum": g["epa"].sum(),
        "succ_n": g["succ"].count(), "succ_sum": g["succ"].sum(),
    })
    for name, sub in (("db", scr[scr["is_pass"]]),
                      ("ru", scr[scr["is_rush"]])):
        gg = sub.groupby(["game_id", "pos_team"])["epa"]
        agg[f"epa_{name}_n"] = gg.count()
        agg[f"epa_{name}_sum"] = gg.sum()
    agg["expl_sum"] = (scr[scr["epa"] >= 1.0]
                       .groupby(["game_id", "pos_team"]).size())
    agg = agg.fillna(0.0)

    dv = df.dropna(subset=["drive_key"])
    dg = dv.groupby(["game_id", "pos_team", "drive_key"])
    drives = pd.DataFrame({
        "min_ytg": dg["ytg"].min(),
        "result": dg["drive_result"].first(),
    }).reset_index()
    drives["pts"] = drives["result"].map(DRIVE_PTS).fillna(0.0)
    drives["eckel"] = drives["min_ytg"] <= 40
    drives["rz"] = drives["min_ytg"] <= 20
    drives["rz_td"] = drives["rz"] & (drives["result"] == "TD")
    drives["eckel_pts"] = np.where(drives["eckel"], drives["pts"], 0.0)
    dgg = drives.groupby(["game_id", "pos_team"])
    dagg = pd.DataFrame({
        "drives": dgg.size(), "eckel_n": dgg["eckel"].sum(),
        "eckel_pts": dgg["eckel_pts"].sum(), "rz_n": dgg["rz"].sum(),
        "rz_td_n": dgg["rz_td"].sum(),
    })
    out = dagg.join(agg, how="left").fillna(0.0).reset_index()

    pas = df[df["passer"].notna()].sort_values(
        ["game_id", "drive_key", "play_seq"])
    first_qb = (pas.groupby(["game_id", "pos_team"])["passer"]
                .first().rename("qb_first").reset_index())
    return out.merge(first_qb, on=["game_id", "pos_team"], how="left")


def _rate(num: float, den: float) -> float:
    return float(num) / float(den) if den else float("nan")


def build_team_games(sched_all: pd.DataFrame) -> pd.DataFrame:
    """Per (game, team): points, drives, §3.1 profile rates (off + the
    defense-allowed mirror from the opponent's aggregates), first passer.
    Scope and row discipline verbatim from the v1 screen (games with at
    least one FBS team; PBP rows restricted to those games)."""
    sched = sched_all[(sched_all["home_division"] == "fbs")
                      | (sched_all["away_division"] == "fbs")]
    game_rows = {int(g["game_id"]): g for _, g in sched.iterrows()}
    scope_ids = set(game_rows)
    frames = []
    for y in SEASONS:
        frames.append(aggregate_game_plays(load_plays(y, scope_ids)))
    tg0 = pd.concat(frames, ignore_index=True)
    rows = []
    for _, t in tg0.iterrows():
        g = game_rows.get(int(t["game_id"]))
        if g is None:
            continue
        # name match (all name-keyed dialects; v1 verbatim) or the
        # 2021 dialect's ESPN team-ID match (V2-R9)
        name_home = norm(g["home_team"]) == norm(t["pos_team"])
        name_away = norm(g["away_team"]) == norm(t["pos_team"])
        pt_id = _idstr(t["pos_team"])
        home = name_home or pt_id == _idstr(g["home_id"])
        away = name_away or pt_id == _idstr(g["away_id"])
        if home == away:  # unmatched, or ambiguous both-side match
            continue
        team_name = t["pos_team"] if (name_home or name_away) else (
            g["home_team"] if home else g["away_team"])
        pts = float(g["home_points"] if home else g["away_points"])
        total_pts = float(g["home_points"]) + float(g["away_points"])
        rows.append({
            "season": int(g["season"]), "week": int(g["week"]),
            "game_id": int(t["game_id"]), "team": team_name,
            "opponent": g["away_team"] if home else g["home_team"],
            "is_home": bool(home),
            "team_division": g["home_division"] if home else g["away_division"],
            "opp_division": g["away_division"] if home else g["home_division"],
            "points": pts, "points_allowed": total_pts - pts,
            "drives": float(t["drives"]), "qb_first": t["qb_first"],
            "home_team": g["home_team"], "away_team": g["away_team"],
            "epa_per_play": _rate(t["epa_sum"], t["epa_n"]),
            "epa_db": _rate(t["epa_db_sum"], t["epa_db_n"]),
            "epa_rush": _rate(t["epa_ru_sum"], t["epa_ru_n"]),
            "success_rate": _rate(t["succ_sum"], t["succ_n"]),
            "explosive_rate": _rate(t["expl_sum"], t["epa_n"]),
            "eckel_rate": _rate(t["eckel_n"], t["drives"]),
            "pp_eckel": _rate(t["eckel_pts"], t["eckel_n"]),
            "rz_trip_rate": _rate(t["rz_n"], t["drives"]),
            "rz_td_rate": _rate(t["rz_td_n"], t["rz_n"]),
            "plays_per_drive": _rate(t["scr_n"], t["drives"]),
        })
    out = pd.DataFrame(rows)
    out["ppd"] = out["points"] / out["drives"]
    # defense-allowed mirror: the partner row's offensive profile
    partner = {(int(r.game_id), norm(r.team)): r
               for r in out.itertuples()}
    for s in PROFILE_STATS:
        out[f"def_{s}"] = [
            getattr(partner[(int(r.game_id), norm(r.opponent))], s)
            if (int(r.game_id), norm(r.opponent)) in partner else np.nan
            for r in out.itertuples()]
    out["team_key"] = out["team"].map(norm)
    out["opp_key"] = out["opponent"].map(norm)
    return out.sort_values(
        ["season", "week", "game_id", "team"]).reset_index(drop=True)


# ------------------------------------------------------------------- features
def shrink_rate(rate_sum: float, n: int, pool_rate: float) -> float:
    """v1 §2.3 discipline verbatim: w = n/(n+3) on the team's observed
    rate, (1-w) on the pool."""
    if n <= 0:
        return pool_rate
    w = n / (n + POOL_K)
    return w * (rate_sum / n) + (1 - w) * pool_rate


def _season_pools(tg: pd.DataFrame) -> dict:
    """Prior-season final rates per team (the pool source, v1 R5 form):
    full-season means of the per-game rates, offense and defense."""
    pools = {}
    for y in sorted(tg["season"].unique()):
        sub = tg[tg["season"] == y]
        pools[y] = {
            "off": sub.groupby("team_key")[PROFILE_STATS].mean()
                      .to_dict("index"),
            "def": sub.groupby("team_key")[[f"def_{s}" for s in PROFILE_STATS]]
                      .mean().to_dict("index"),
            "cont": float(sub["cont_raw"].mean()),
        }
    return pools


def _passer_sequences(tg: pd.DataFrame) -> pd.DataFrame:
    """§3.3 raw continuity + the v1 §4.4 stratum flag, from the team's
    own team-game sequence within the season ((week, game_id) order)."""
    tg = tg.copy()
    prev1, prev2, cont_raw, qb_changed = {}, {}, {}, {}
    for _, t in tg.iterrows():
        key = (int(t["season"]), t["team_key"])
        p1 = prev1.get(key)
        p2 = prev2.get(key)
        qb = t["qb_first"]
        row_key = (int(t["game_id"]), t["team_key"])
        qb_changed[row_key] = bool(
            key in prev1 and pd.notna(qb) and pd.notna(p1) and qb != p1)
        if pd.notna(qb) and pd.notna(p1) and pd.notna(p2):
            cont_raw[row_key] = 1.0 if p1 == p2 else 0.0
        else:
            cont_raw[row_key] = np.nan
        prev2[key] = p1
        prev1[key] = qb
    tg["cont_raw"] = [cont_raw[(int(g), k)] for g, k in
                      zip(tg["game_id"], tg["team_key"])]
    tg["qb_changed"] = [qb_changed[(int(g), k)] for g, k in
                        zip(tg["game_id"], tg["team_key"])]
    return tg


def _shrunk(hist_team: pd.DataFrame, stats: list, pool_src: dict,
            team_key: str, league: dict, prefix: str) -> dict:
    """Shrink one side's per-game rates over hist_team toward the pool
    (0.5 x prior-season team rate + 0.5 x walk-forward league rate)."""
    out = {}
    prior = pool_src.get(team_key, {})
    for s in stats:
        col = s if prefix == "off" else f"def_{s}"
        vals = hist_team[col].dropna()
        lg = league[s]
        base = prior.get(col, lg)
        if not np.isfinite(base):
            base = lg
        pool = 0.5 * base + 0.5 * lg
        out[s] = shrink_rate(float(vals.sum()), int(len(vals)), pool)
    return out


def build_features(tg: pd.DataFrame) -> pd.DataFrame:
    """Walk-forward §3 features for every machinery team-game (both
    teams >= 3 qualifying in-season priors; R8 week keying). Mirrors
    the v1 screen's predict_all loop; adds the §3.2 feature vector."""
    tg = _passer_sequences(tg)
    pools = _season_pools(tg)
    recs = []
    for season in SEASONS:
        season_games = tg[tg["season"] == season]
        pool_src = pools.get(season - 1, {"off": {}, "def": {},
                                          "cont": np.nan})
        for (week, game_id), game in season_games.groupby(["week",
                                                           "game_id"]):
            if len(game) != 2:
                continue
            hist = tg[(tg["season"] == season) & (tg["week"] < week)]
            if len(hist) == 0:
                continue
            lg_off = {s: float(hist[s].mean()) for s in PROFILE_STATS}
            lg_def = {s: float(hist[f"def_{s}"].mean())
                      for s in PROFILE_STATS}
            lg_drv = float(hist["drives"].mean())
            lg_pts = float(hist["points"].mean())
            cont_fb = hist["cont_raw"].mean()
            if pd.isna(cont_fb):
                cont_fb = pool_src.get("cont", np.nan)
            if pd.isna(cont_fb):
                cont_fb = 0.5
            game_recs = {}
            ok = True
            for _, t in game.iterrows():
                th = hist[hist["team_key"] == t["team_key"]]
                oh = hist[hist["team_key"] == t["opp_key"]]
                if len(th) < 3 or len(oh) < 3:
                    ok = False
                    break
                off = _shrunk(th, PROFILE_STATS, pool_src.get("off", {}),
                              t["team_key"], lg_off, "off")
                dfn = _shrunk(oh, PROFILE_STATS, pool_src.get("def", {}),
                              t["opp_key"], lg_def, "def")
                off_drv = shrink_rate(float(th["drives"].sum()), len(th),
                                      lg_drv)  # v1 R1 pool, verbatim
                def_drv = shrink_rate(float(oh["drives"].sum()), len(oh),
                                      lg_drv)
                proj_drives = 0.5 * (off_drv + def_drv)  # v1 R1
                lg_rz = lg_off["rz_trip_rate"]
                rz_mu = (off["rz_trip_rate"] * dfn["rz_trip_rate"] / lg_rz
                         if lg_rz and np.isfinite(lg_rz) and lg_rz > 0
                         else off["rz_trip_rate"])  # v1 R2 guard form
                cont = t["cont_raw"]
                cont_fb_used = bool(pd.isna(cont))
                if cont_fb_used:
                    cont = cont_fb
                epa_diff = off["epa_per_play"] - dfn["epa_per_play"]
                game_recs[t["team_key"]] = {
                    "season": season, "week": int(week),
                    "game_id": int(game_id), "team": t["team"],
                    "opponent": t["opponent"], "is_home": bool(t["is_home"]),
                    "actual": float(t["points"]),
                    "ppd_actual": float(t["ppd"]),
                    "epa_diff": epa_diff,
                    "success_diff": off["success_rate"] - dfn["success_rate"],
                    "explosive_diff": (off["explosive_rate"]
                                       - dfn["explosive_rate"]),
                    "eckel_diff": off["eckel_rate"] - dfn["eckel_rate"],
                    "rz_trip_mu": rz_mu,
                    "rz_td_diff": off["rz_td_rate"] - dfn["rz_td_rate"],
                    "proj_drives": float(proj_drives),
                    "continuity": float(cont),
                    "cont_fallback": cont_fb_used,
                    "cont_x_epa": float(cont) * epa_diff,
                    "b1": float(th["points"].mean()),
                    "b2": float(lg_pts),
                    "qb_first": t["qb_first"],
                    "qb_changed": bool(t["qb_changed"]),
                    "home_team": t["home_team"], "away_team": t["away_team"],
                    "team_division": t["team_division"],
                    "opp_division": t["opp_division"],
                    "n_prior_team": int(len(th)),
                    "n_prior_opp": int(len(oh)),
                }
            if ok:
                recs.extend(game_recs.values())
    return pd.DataFrame(recs)


# ------------------------------------------------------------------- the map
def fit_ridge(train: pd.DataFrame) -> dict:
    """V2-R1: standardized ridge, lambda fixed, intercept unpenalized."""
    X = train[FEATURES].to_numpy(dtype=float)
    y = train["ppd_actual"].to_numpy(dtype=float)
    mu = X.mean(axis=0)
    sd = X.std(axis=0, ddof=1)
    sd = np.where(np.isfinite(sd) & (sd > 0), sd, 1.0)
    Xs = (X - mu) / sd
    y_mean = float(y.mean())
    beta = np.linalg.solve(
        Xs.T @ Xs + RIDGE_LAMBDA * np.eye(len(FEATURES)),
        Xs.T @ (y - y_mean))
    return {"mu": mu, "sd": sd, "beta": beta, "y_mean": y_mean,
            "coef_raw": beta / sd, "n_train": int(len(train))}


def predict_ppd(model: dict, df: pd.DataFrame) -> np.ndarray:
    X = df[FEATURES].to_numpy(dtype=float)
    Xs = (X - model["mu"]) / model["sd"]
    return model["y_mean"] + Xs @ model["beta"]


def fit_dispersion(train: pd.DataFrame) -> tuple[float, int]:
    """v1 R6 bounded NB MLE, verbatim."""
    mu = np.clip(train["mean"].to_numpy(), 1e-6, None)
    yv = train["actual"].to_numpy()

    def nll(log_r):
        r = np.exp(log_r)
        return -float(np.sum(stats.nbinom.logpmf(yv, r, r / (r + mu))))

    res = minimize_scalar(nll, bounds=(np.log(0.5), np.log(500.0)),
                          method="bounded")
    return float(np.exp(res.x)), int(len(train))


# ------------------------------------------------------------------- screen
def run_screen(tg: pd.DataFrame, closes: pd.DataFrame,
               sched_all: pd.DataFrame):
    feat = build_features(tg)
    if not np.isfinite(feat[FEATURES].to_numpy(dtype=float)).all():
        raise RuntimeError("non-finite feature in the machinery universe")
    scoreable = closes[closes["scoreable"]][
        ["game_id", "home_team_spread", "over_under"]]
    close_map = {int(r.game_id): (float(r.home_team_spread),
                                   float(r.over_under))
                 for r in scoreable.itertuples()}

    def implied(row):
        c = close_map.get(int(row["game_id"]))
        if c is None:
            return np.nan
        spread, total = c
        s_close = -spread  # sign convention proven at pin time (v1 §3)
        return (total + s_close) / 2 if row["is_home"] else (total - s_close) / 2

    df = feat[feat["season"].isin(EVAL_SEASONS)].copy()
    df["bmkt"] = df.apply(implied, axis=1)

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
    excl["games_per_season"] = {int(y): int(g["game_id"].nunique())
                                for y, g in df.groupby("season")}

    # ---- cohort-identity gate (design §7): fail closed, before any
    # outcome statistic exists.
    gate_fail = {k: {"expected": EXPECTED[k], "found": excl[k]}
                 for k in EXPECTED if k != "games_per_season"
                 and excl.get(k) != EXPECTED[k]}
    if excl["games_per_season"] != EXPECTED["games_per_season"]:
        gate_fail["games_per_season"] = {
            "expected": EXPECTED["games_per_season"],
            "found": excl["games_per_season"]}
    if gate_fail:
        return None, {"cohort_gate": "FAIL", "gate_failures": gate_fail,
                      "exclusions": excl}

    # ---- fold fits: map on seasons strictly before the eval season
    models, disp, fit_rows, loso_detail = {}, {}, {}, {}
    df["mean"] = np.nan
    df["ppd_pred_raw"] = np.nan
    for season in EVAL_SEASONS:
        train = feat[feat["season"] < season]
        model = fit_ridge(train)
        models[season] = model
        rows = df["season"] == season
        raw = predict_ppd(model, df[rows])
        df.loc[rows, "ppd_pred_raw"] = raw
        df.loc[rows, "mean"] = np.maximum(raw, 0.0) * df.loc[rows,
                                                             "proj_drives"]
        # V2-R6 dispersion: out-of-season predictions inside the
        # training window only (fit on seasons < Y, predict season Y)
        loso = []
        for y in range(2022, season):
            m_y = fit_ridge(feat[feat["season"] < y])
            te = feat[feat["season"] == y].copy()
            te["mean"] = (np.maximum(predict_ppd(m_y, te), 0.0)
                          * te["proj_drives"])
            loso.append(te[["mean", "actual"]])
        loso_df = pd.concat(loso, ignore_index=True)
        disp[season], fit_rows[season] = fit_dispersion(loso_df)
        loso_detail[season] = {int(y): int((feat["season"] == y).sum())
                               for y in range(2022, season)}
    df["floor_bindings"] = (df["ppd_pred_raw"] < 0).astype(int)
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
    meta = {"exclusions": excl, "cohort_gate": "PASS",
            "dispersion": {int(k): v for k, v in disp.items()},
            "dispersion_fit_rows": {int(k): v for k, v in fit_rows.items()},
            "dispersion_loso_seasons": {int(k): v for k, v in
                                        loso_detail.items()},
            "models": {int(s): {
                "n_train": m["n_train"], "y_mean_train": m["y_mean"],
                "beta_std": {f: float(b) for f, b in
                             zip(FEATURES, m["beta"])},
                "coef_raw": {f: float(c) for f, c in
                             zip(FEATURES, m["coef_raw"])},
                "feature_mu": {f: float(v) for f, v in
                               zip(FEATURES, m["mu"])},
                "feature_sd": {f: float(v) for f, v in
                               zip(FEATURES, m["sd"])},
            } for s, m in models.items()},
            "floor_bindings_total": int(df["floor_bindings"].sum()),
            "cont_fallback_rows_cohort": int(df["cont_fallback"].sum())}
    return df, meta


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
    rng = np.random.default_rng(BOOT_SEED)
    games = df["game_id"].unique()
    gd = {g: d for g, d in df.groupby("game_id")}
    deltas, betas = [], []
    for _ in range(BOOT_N):
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
    cs = df[df["continuity"] == 0.0]
    pooled["continuity_zero_stratum_reporting_only"] = {
        "rows": int(len(cs)),
        "beta": beta_of(cs) if len(cs) > 10 else None,
        "mae_m": float((cs["mean"] - cs["actual"]).abs().mean()) if len(cs) else None,
        "mae_bmkt": float((cs["bmkt"] - cs["actual"]).abs().mean()) if len(cs) else None,
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
    if df is None:
        record = {"engine": "CFB_TEAM_TOTAL_EPA_PROFILE_V2",
                  "verdict": "NOT_EXECUTABLE", **meta}
        (OUT / "not_executable.json").write_text(json.dumps(record,
                                                            indent=1))
        print(json.dumps(record, indent=1))
        raise SystemExit(3)
    summary = summarize(df)
    record = {"engine": "CFB_TEAM_TOTAL_EPA_PROFILE_V2", **summary, **meta}
    (OUT / "final_screen_summary.json").write_text(json.dumps(record,
                                                              indent=1))
    print(json.dumps({"verdict": summary["verdict"],
                      "criteria": summary["criteria"],
                      "pooled": {k: summary["pooled"][k] for k in
                                 ("games", "rows", "beta", "mae_m",
                                  "mae_bmkt", "mae_b1", "mae_b2", "crps_m",
                                  "coverage80", "qb_stratum")},
                      "per_season": summary["per_season"],
                      "dispersion": meta["dispersion"],
                      "exclusions": meta["exclusions"]}, indent=1))


if __name__ == "__main__":
    main()
