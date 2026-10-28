#!/usr/bin/env python3
"""DESIGN SCREEN - NFL_PERIOD_DRIVE_STATE_V2 (drive-level, game-state
conditioned period construction), per
research/successor_designs_20261028/DESIGN_NFL_PERIOD_DRIVE_STATE_V2.md.

Status: DESIGN SCREEN ONLY. A screen is an entry ticket, never
validation (standing program law). Every season screened (2023-2025)
is DESIGN data, seen by the failed predecessor NFL_PERIOD_SHARE_V1
and the retired constructions. Nothing here prices a live game,
opens a clock, or issues a verdict against a market. No market line
of any kind is an input. PAPER / research only.

The design (section numbers below are the design doc's):

  Construction (design sections 3.1-3.3): a game is simulated drive
  by drive, play by play, under a game clock. State = (score
  differential from the possessing team's perspective, time
  remaining) in the FIXED buckets of design section 3.2 - no bucket
  added, split, or merged. State modulates exactly three league-level
  channels, estimated on training seasons only: (1) pace
  (seconds-per-play distributions by state cell and play family),
  (2) play selection (pass probability by state cell), (3) scoring
  environment (per-play gain scale by state cell). Team identity
  enters only through point-in-time rates (design section 3.3):
  per-play gain factors (rush/pass, offense and defense), completion
  / sack / turnover rate factors, penalty rate factor, drive-start
  field-position distribution, base pace ratio, red-zone finishing
  factor - each from the team's sample under the sibling sample rule
  (same-season priors supplemented by prior-season games to 8),
  shrunk toward point-in-time league rates. Drives continue across
  quarter boundaries; a score belongs to the quarter in which it
  occurs. Regulation only - no overtime is simulated or scored.
  Output per game: the joint distribution of both teams' points by
  quarter over R = 10,000 replications; period means are replication
  means (the screen scores means, design section 3.1).

  Arms (design section 5): M = this construction's period means;
  B0 = NFL_TEAM_TOTAL_DIST_V1 sibling mean x point-in-time league
  shares; B1 = sibling mean x flat split (0.25/quarter, 0.50/half).
  B0/B1 and the period panel are computed with the activation pack's
  own machinery (screen_nfl_activation_v1.py, imported, unmodified),
  so the baselines are the predecessor screen's baselines, not a
  re-implementation. Buckets: Q1, Q2, Q3, Q4, 1H, 2H (regulation;
  2H is a diagnostic bucket, out of family scope, as in v1).

  Pass criteria (design section 5 - v1's legs, one added, one
  added, none softened):
    L1 pooled MAE(M) < MAE(B0) AND pooled MAE(M) < MAE(B1).
    L2 M beats B0 in at least 4 of the 6 buckets.
    L3 (new) Q4 leg: MAE(M) < MAE(B0) in Q4 specifically.
    L4 (new) stability: in no evaluation season is pooled MAE(M)
       worse than that season's pooled MAE(B0) by more than 0.25.
  SCREEN_PASS requires every leg under BOTH pre-declared seeds.
  A verdict that flips with the seed is recorded
  NOT_EXECUTABLE / contested, never averaged (design section 5).
  Any leg failing under both seeds is SCREEN_FAIL, recorded with
  its numbers; the construction is then retired.

  Pre-declared seeds (fixed here, before any run): SEED_A = 20261028,
  SEED_B = 20261029. Per-game replication streams derive
  deterministically from (master seed, game index in the panel's
  chronological order). R = 10,000, fixed by the design.

BUILD READINGS (design section 7 - recorded BEFORE any outcome
statistic was computed; the run below follows them exactly):

  RD-1 (drive generation form; the ambiguity the design names):
    PLAY-BY-PLAY generation. Each drive advances play by play;
    state is re-evaluated on every play, so a drive that crosses a
    quarter boundary or a state-bucket boundary is re-conditioned
    mid-drive. The alternative (drive-aggregate) was not used.

  RD-2 (state-function training window): "estimated on training
    seasons only" (section 3.2) is read as PRIOR SEASONS ONLY: for
    evaluation season S, every league-level function (state cells,
    gain/pace/selection tables, fourth-down decisions, field-goal
    curve, punt net table, conversion rates, base gain pools) is fit
    on nflverse PBP regular seasons 2022..S-1 and frozen for the
    whole of S. 2022 PBP is pulled for this purpose and for RD-3's
    prior-season supplementation; it is the same source as the
    design's section-4 table (nflverse PBP), one season earlier,
    and no other source is used. The section-9 stability diagnostic
    fits the same functions on each of 2023 / 2024 / 2025 singly
    and reports them side by side; it gates nothing (the design
    fixes no numeric stability threshold, so none is invented).

  RD-3 (team-rate sample): the section-3.3 sample rule is the
    sibling's, applied to PBP team-game aggregates with the same
    chronological discipline as the v1 WalkForward: same-season
    prior games, supplemented by the most recent prior-season games
    until the sample reaches 8 (or history exhausts). The 2022 PBP
    pull is what makes prior-season supplementation possible for
    2023 games; early-2023 samples are short and shrink hard to
    league, exactly as the discipline intends. Shrinkage follows
    the sibling's points-scale discipline: rate estimates carry a
    league prior weighted as 3 games of plays (the sibling's
    K = 3 games on means), drives as 3 games of drives (~36).

  RD-4 (league shrinkage targets): point-in-time expanding league
    aggregates over all PBP regular-season games strictly before
    the priced game (2022 onward), mirroring the v1 period
    screen's season-to-date / prior-season-fallback league shares.

  RD-5 (opening possession): design section 3.1 says the opening
    coin-flip order is "fixed from the schedule record". The
    schedules file (games.csv.gz, header inspected for this run)
    carries NO coin-toss field, and the priced game's own PBP is
    realized data the construction may not touch (section 3.4).
    Reading: opening possession is drawn per replication
    (Bernoulli 1/2, from the game's seeded stream); the second-half
    kickoff goes to the other team, as the rules dictate.

  RD-6 (timeouts): section 3.2 lists timeouts in the state "where
    the PBP records them". nflverse PBP does not record timeouts
    remaining per play. Timeouts are therefore not a separate state
    variable; their realized effects are inside the fitted pace
    distributions (which are fit on realized PBP, timeouts and
    all). No timeout effect is invented.

  RD-7 (scoring-environment channel, aggregate form): the state
    cell's gain scale is the cell's yards-per-play ratio to the
    play family's global training mean, shrunk toward 1 with a
    200-play prior and clipped to [0.70, 1.30]; it multiplies drawn
    gains. Explosive-play suppression/emergence enters through this
    scale (the design lists gain and explosive rates as one
    channel's two faces).

  RD-8 (play clocks): seconds consumed by a play are drawn from
    the empirical distribution of realized seconds between
    consecutive plays, by state cell and play family (run family
    includes qb_kneel; pass family includes qb_spike), attributed
    to the earlier play, clipped to [0, 90], then scaled by the
    possessing team's shrunk base-pace ratio (clipped [0.80,
    1.25]). A score's timestamp is the clock after its play,
    clamped at a half boundary (a score as a half expires belongs
    to the expiring quarter).

  RD-9 (fourth down, kicks, conversions - league tables, training
    fit): fourth-down decision probabilities by (field bucket,
    yards-to-go bucket, late-close flag) from what offenses
    actually did; field-goal make probability by attempt-distance
    bucket (distance = yards-to-goal + 17), shrunk toward the
    pooled curve; missed-FG takeover at the kick spot (7 yards
    behind the line) or the 20 if the spot is inside it; punt
    outcomes as the receiving team's start-position distribution
    by punt-origin bucket; after a touchdown, the two-point
    decision rate by (differential-after bucket, late flag) and
    league kick/2pt success rates; kickoff and free-kick starts
    from the receiving team's shrunk drive-start distribution,
    kickoff clock cost 5 seconds (the realized median is inside
    the pace noise of the following drive and is not separately
    fitted). Safeties: a per-play draw at the training rate for
    scrimmage plays starting inside a team's own 5 (the fitted
    share of such plays recorded as safeties); a safety scores 2
    for the defense and possession flips with a free-kick start
    drawn from the scoring team's drive-start distribution. A
    play whose drawn gain would otherwise carry the ball behind
    the goal line without the safety draw is floored at the 1
    (tackled at the 1): the crossing rule alone was build-tested
    and produced ~8x the realized safety frequency, because
    continuous drawn gains cross the line far more readily than
    real tackles in the end zone occur - the fitted-rate draw is
    the empirically anchored channel. A turnover is returned
    for a defensive touchdown at the fitted share of turnover
    drives (the panel's points include defensive scores, and
    design section 3.1's drive outcomes end in TD - a return TD
    is the defense's): the defense scores 6 plus the conversion
    sequence, and the scored-upon team receives the ensuing
    kickoff. Other turnovers: no return yards (the new drive
    starts at the turnover spot, mirrored);
    interception/fumble rates are the fitted channel instead.

  RD-11 (play accounting identity): every fitted rate's
    denominator is the same event partition the simulator draws
    from, so fitted and simulated accounting coincide by
    construction. In this nflverse pull, pass_attempt == 1 is set
    on EVERY pass play, sacks included (verified arithmetically:
    completions per pass play = completions per "attempt" =
    0.598, and the identity -0.46 sack + 0.598 x 10.92 = 6.07
    reproduces the realized yards per pass play exactly). A pass
    play therefore resolves as sack | attempt, with the
    completion and interception rates fitted per NON-SACK pass
    play - the partition the simulator draws. (An earlier build
    fitted the completion rate over pass plays but applied it
    after removing sacks, silently losing ~9% of completions,
    ~0.45 yards per pass play; build testing against the
    training record's base rates caught it.) Fumbles lost are
    fitted per play family and drawn on those plays: run-family
    plays, completed pass plays, and sacks (strip-sacks are a
    real fumble class). Scrambles need no channel: in this pull
    qb_scramble is unpopulated (all zeros) and quarterback runs
    are coded as run plays, already inside the run gain pool.
    Base gain pools are conditioned on (down, yards-to-go
    bucket) - the fundamental conditioning of play outcomes,
    without which a memoryless chain cannot reproduce drive
    lengths or finishing rates - with the pooled family
    distribution as the fallback for thin cells; team factors
    and state scales multiply the conditioned draws exactly as
    they did the pooled ones. The identity and the conditioning
    are verified by the base-rate reproduction diagnostic in
    the screen record.

  RD-10 (penalties): per scrimmage play, offensive- and
    defensive-penalty draws at league rates, each side's draw
    scaled by that side's own penalty-rate factor. In the PBP
    record most penalty events are standalone no_play rows
    between scrimmage plays, so a drawn penalty applies its
    effect and the step's scrimmage play still happens (5
    seconds of clock): an offensive penalty costs the fitted
    yardage (5/10/15 mix) and adds it to yards-to-go, down
    unchanged; a defensive penalty gains the fitted yardage
    and awards a first down when the yardage covers the
    yards-to-go or on the fitted automatic-first-down share.
    Offsetting penalties do not exist in the model. Penalty
    yardage mixes are training-fit.

Nothing in this module modifies the frozen sibling
(NFL_TEAM_TOTAL_DIST_V1): its engine, runner, config, prereg, and
pins are read-only inputs, used exactly as merged.

BUILD NOTES (Oct 28, 2026, all BEFORE any screen statistic was
computed):

  FG-FIX: fg_prob originally keyed its distance lookup on
    (att // 5) * 5 - multiples of 5 - while the fitted curve is
    keyed on buckets [18+5k, 23+5k). The lookup therefore missed
    the fitted buckets for nearly every attempt and silently
    returned the pooled make rate, contradicting RD-9 (FG make
    probability BY attempt-distance bucket, shrunk toward the
    pooled curve). The lookup now keys on the fitted edges.
    Caught by code inspection during the pre-screen performance
    pass; all build diagnostics were re-run after the fix.

  OPT: the simulator's hot paths were vectorized for runtime
    (dense FG lookup table, present-cell iteration for the pace
    and gain draws with per-step precomputed cell masks, vector
    quarter/bucket arithmetic, optional multiprocessing across
    games). No fitted value, seed, replication count, bucket,
    reading, or criterion changed; per-game streams still derive
    deterministically from SeedSequence([seed, game index in
    chronological panel order]), so results are identical for
    any worker count.

  DIAGNOSTIC DECISION: the base-rate build diagnostic (bands
    fixed in code before it was run: points within 1.0, plays
    within 3.0, TD share within 0.02, punt share within 0.03)
    accepts the 2023 fit outright (points gap 0.82 after FG-FIX;
    0.74 before it). The 2024 and 2025 fits pass plays, TD
    share, and punt share but miss the points band: gaps 1.22
    and 1.23 after FG-FIX (1.35 / 1.42 before it) - the chain
    produces ~2.5 fewer scrimmage plays per team-game than the
    training record at similar drive counts, i.e. slightly
    shorter drives. The design fixes NO diagnostic threshold
    and NO level-correction channel; adding one after seeing
    build diagnostics would be an undeclared construction
    change. DECISION: the screen runs on the construction
    exactly as designed, with this residual points shortfall
    disclosed in SCREEN_REPORT.md as a build limitation. The
    bands are NOT softened, and the diagnostic is NOT reported
    as passed for the 2024/2025 fits.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ------------------------------------------------------------------
# Fixed screen constants (design section 5; seeds pre-declared above)
# ------------------------------------------------------------------
R_REPS = 10_000
SEED_A = 20261028
SEED_B = 20261029
SAMPLE_CAP = 8
K_PRIOR_PLAYS = 195.0     # 3 games of plays (RD-3)
K_PRIOR_DRIVES = 36.0     # 3 games of drives (RD-3)
EVAL_SEASONS = (2023, 2024, 2025)
TRAIN_BASE_SEASON = 2022  # earliest PBP season pulled (RD-2/RD-3)
BUCKETS = ["Q1", "Q2", "Q3", "Q4", "1H", "2H"]
STABILITY_SLACK = 0.25    # design section 5, leg 4

# Design section 3.2 state buckets - FIXED, never re-cut.
# Cut points: the bucket increments when the differential reaches
# the cut (bucket = number of cuts <= diff).
DIFF_EDGES = [-16, -8, -2, 3, 9, 17]  # -> 7 buckets:
#   <=-17 | -16..-9 | -8..-3 | -2..+2 | +3..+8 | +9..+16 | >=+17
TIME_LABELS = ["1H", "Q3", "Q4>5", "Q4<=5", "Q4<=2"]

PBP_URL = ("https://github.com/nflverse/nflverse-data/releases/download/"
           "pbp/play_by_play_{season}.parquet")

_HERE = os.path.dirname(os.path.abspath(__file__))
_V1_PATH = os.path.join(
    _HERE, "..", "nfl_activation_20261027", "screen_nfl_activation_v1.py")


def load_v1_module():
    """Import the activation pack's screen machinery UNMODIFIED, so
    the panel, the sibling means, and arms B0/B1 are the predecessor
    screen's own, not a re-implementation."""
    spec = importlib.util.spec_from_file_location(
        "screen_nfl_activation_v1", os.path.normpath(_V1_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def diff_bucket(diff: float) -> int:
    """Section 3.2 differential buckets (possessing team's view)."""
    return int(np.searchsorted(DIFF_EDGES, diff, side="right"))


def time_bucket(gsr: float) -> int:
    """Section 3.2 time buckets from game seconds remaining."""
    if gsr > 1800:
        return 0  # first half
    if gsr > 900:
        return 1  # Q3
    if gsr > 300:
        return 2  # Q4 > 5:00
    if gsr > 120:
        return 3  # Q4 <= 5:00
    return 4      # Q4 <= 2:00


def quarter_of(gsr_after: float) -> int:
    """Quarter (0..3) in which a score at this clock value lands.
    Elapsed = 3600 - gsr; a score at exactly a quarter boundary
    (elapsed 900 / 1800 / 2700) belongs to the expiring quarter -
    which is also where the halftime clamp (gsr = 1800) must land:
    Q2, index 1."""
    if gsr_after >= 2700:
        return 0
    if gsr_after >= 1800:
        return 1
    if gsr_after >= 900:
        return 2
    return 3


# ------------------------------------------------------------------
# PBP preparation
# ------------------------------------------------------------------
_PBP_COLS = [
    "game_id", "play_id", "season", "week", "season_type", "qtr",
    "home_team", "away_team", "posteam", "defteam", "yardline_100",
    "game_seconds_remaining", "down", "ydstogo", "play_type",
    "yards_gained", "complete_pass", "interception", "fumble_lost",
    "sack", "penalty", "penalty_team", "penalty_yards",
    "first_down_penalty", "touchdown", "field_goal_result",
    "extra_point_result", "two_point_conv_result", "safety",
    "fixed_drive", "fixed_drive_result",
    "posteam_score_post", "defteam_score_post",
    "goal_to_go", "pass_attempt", "rush_attempt", "qb_scramble",
    "total_home_score", "total_away_score",
]

SCRIMMAGE_TYPES = ("run", "pass", "qb_kneel", "qb_spike")


def load_pbp(cache_dir: str, seasons, hashes: dict) -> pd.DataFrame:
    """Load (and if needed fetch) nflverse PBP for the given seasons;
    hashes of the bytes actually used are recorded by the caller."""
    v1 = load_v1_module()
    frames = []
    for season in seasons:
        path, h = v1.fetch(cache_dir, f"pbp_{season}.parquet",
                           PBP_URL.format(season=season))
        hashes[f"pbp_{season}"] = h
        d = pd.read_parquet(path, columns=_PBP_COLS)
        frames.append(d[d["season_type"] == "REG"])
    pbp = pd.concat(frames, ignore_index=True)
    return pbp.sort_values(["game_id", "play_id"]).reset_index(drop=True)


def prepare_plays(pbp: pd.DataFrame) -> pd.DataFrame:
    """Derive the play-level analysis frame: scrimmage plays with the
    state they were played in, realized seconds consumed (RD-8), and
    the drive table's start positions."""
    d = pbp.copy()
    # The state a play was played in is the score BEFORE it. Total
    # home/away scores are post-play; shift within the game (marker
    # rows forward-filled) for the pre-play totals, then sign by the
    # possessing team. (posteam_score_post cannot be shifted
    # directly: its perspective flips when possession changes.)
    for col, pre in (("total_home_score", "home_pre"),
                     ("total_away_score", "away_pre")):
        d[pre] = d.groupby("game_id")[col].shift(1)
        d[pre] = d.groupby("game_id")[pre].ffill().fillna(0.0)
    is_home = d["posteam"] == d["home_team"]
    d["pre_diff"] = np.where(is_home, d["home_pre"] - d["away_pre"],
                             d["away_pre"] - d["home_pre"])
    d.loc[d["posteam"].isna(), "pre_diff"] = np.nan
    # Realized seconds consumed by each play: own clock minus the next
    # play's clock in the same game (RD-8), clipped to [0, 90]; plays
    # after which the half/game state resets are excluded by the clip
    # and by requiring the next row to be the same half.
    d["next_gsr"] = d.groupby("game_id")["game_seconds_remaining"].shift(-1)
    d["next_qtr"] = d.groupby("game_id")["qtr"].shift(-1)
    d["sec_consumed"] = d["game_seconds_remaining"] - d["next_gsr"]
    same_half = ((d["qtr"] <= 2) & (d["next_qtr"] <= 2)) | \
                ((d["qtr"] >= 3) & (d["next_qtr"] >= 3))
    ok = same_half & d["sec_consumed"].between(0, 90)
    d.loc[~ok, "sec_consumed"] = np.nan
    d["is_scrimmage"] = d["play_type"].isin(SCRIMMAGE_TYPES)
    d["family"] = np.where(d["play_type"].isin(["pass", "qb_spike"]), 1,
                           np.where(d["play_type"].isin(["run", "qb_kneel"]),
                                    0, -1))  # 0 = run family, 1 = pass family
    d["diff_b"] = [diff_bucket(v) if pd.notna(v) else -1
                   for v in d["pre_diff"]]
    d["time_b"] = [time_bucket(v) if pd.notna(v) else -1
                   for v in d["game_seconds_remaining"]]
    d["x_start"] = 100.0 - d["yardline_100"]  # yards from own goal
    return d


def drive_starts(plays: pd.DataFrame) -> pd.DataFrame:
    """First scrimmage/kick play position of every fixed drive:
    (game_id, fixed_drive, posteam) -> x_start (yards from own goal)."""
    scr = plays[plays["is_scrimmage"] & plays["yardline_100"].notna()
                & plays["posteam"].notna()]
    idx = scr.groupby(["game_id", "fixed_drive"])["play_id"].idxmin()
    first = scr.loc[idx, ["game_id", "fixed_drive", "posteam", "x_start"]]
    return first.rename(columns={"posteam": "team"})


def team_game_aggregates(plays: pd.DataFrame,
                         starts: pd.DataFrame) -> pd.DataFrame:
    """One row per (game_id, team): the section-3.3 rate ingredients,
    from that team's offensive plays plus its defensive plays."""
    rows = []
    scr = plays[plays["is_scrimmage"] & plays["posteam"].notna()].copy()
    for (gid, team), g in scr.groupby(["game_id", "posteam"]):
        run = g[g["family"] == 0]
        pas = g[g["play_type"] == "pass"]
        rows.append({
            "game_id": gid, "team": team, "side": "off",
            "season": int(g["season"].iloc[0]), "week": int(g["week"].iloc[0]),
            "n_scrim": len(g),
            "n_run": len(run), "run_yards": float(run["yards_gained"].sum()),
            "n_pass_att": int((g["pass_attempt"] == 1).sum()),
            "pass_yards": float(pas["yards_gained"].sum()),
            "n_complete": int((pas["complete_pass"] == 1).sum()),
            "n_sack": int((pas["sack"] == 1).sum()),
            "int_thrown": int((g["interception"] == 1).sum()),
            "fum_lost": int((g["fumble_lost"] == 1).sum()),
            "pen_plays": int((g["penalty"] == 1).sum()),
            "sec_neutral": float(g.loc[(g["diff_b"] == 3),
                                       "sec_consumed"].sum()),
            "n_sec_neutral": int(g.loc[(g["diff_b"] == 3),
                                       "sec_consumed"].notna().sum()),
        })
    off = pd.DataFrame(rows)
    # Defense view: same plays, credited to defteam.
    drows = []
    for (gid, team), g in scr.groupby(["game_id", "defteam"]):
        run = g[g["family"] == 0]
        pas = g[g["play_type"] == "pass"]
        drows.append({
            "game_id": gid, "team": team, "side": "def",
            "n_run_faced": len(run),
            "run_yards_allowed": float(run["yards_gained"].sum()),
            "n_pass_faced": int((g["pass_attempt"] == 1).sum()),
            "pass_yards_allowed": float(pas["yards_gained"].sum()),
            "sacks_made": int((pas["sack"] == 1).sum()),
            "takeaways": int((g["interception"] == 1).sum()
                             + (g["fumble_lost"] == 1).sum()),
        })
    dfn = pd.DataFrame(drows)
    agg = off.merge(dfn, on=["game_id", "team"], how="left")
    # Drive starts and red-zone finishing per team-game.
    st = starts.copy()
    st["n_drives"] = 1
    stg = st.groupby(["game_id", "team"]).agg(
        n_drives=("n_drives", "sum"),
        starts_list=("x_start", lambda s: tuple(float(v) for v in s)),
    ).reset_index()
    agg = agg.merge(stg, on=["game_id", "team"], how="left")
    rz = plays[plays["is_scrimmage"] & plays["posteam"].notna()
               & (plays["yardline_100"] <= 20)]
    rz_trip = rz.groupby(["game_id", "posteam", "fixed_drive"]).size() \
        .reset_index()[["game_id", "posteam", "fixed_drive"]].rename(
            columns={"posteam": "team"})
    rz_trips = rz_trip.groupby(["game_id", "team"]).size() \
        .rename("rz_trips").reset_index()
    td_drives = plays[(plays["touchdown"] == 1) & plays["posteam"].notna()] \
        .groupby(["game_id", "posteam", "fixed_drive"]).size() \
        .reset_index()[["game_id", "posteam", "fixed_drive"]].rename(
            columns={"posteam": "team"})
    rz_td_joined = td_drives.merge(
        rz_trip.drop_duplicates(), on=["game_id", "team", "fixed_drive"],
        how="inner")
    rz_tds = rz_td_joined.groupby(["game_id", "team"]).size() \
        .rename("rz_tds").reset_index()
    agg = agg.merge(rz_trips, on=["game_id", "team"], how="left")
    agg = agg.merge(rz_tds, on=["game_id", "team"], how="left")
    agg[["rz_trips", "rz_tds"]] = agg[["rz_trips", "rz_tds"]].fillna(0)
    return agg


# ------------------------------------------------------------------
# Shrinkage helpers (RD-3: league prior weighted as 3 games)
# ------------------------------------------------------------------
def shrunk_rate(num: float, den: float, league: float,
                prior: float = K_PRIOR_PLAYS) -> float:
    """(num + prior*league) / (den + prior): a rate shrunk to league."""
    if den <= 0:
        return float(league)
    return (num + prior * league) / (den + prior)


def shrunk_mean(total: float, n: float, league: float,
                prior: float = K_PRIOR_PLAYS) -> float:
    return shrunk_rate(total, n, league, prior)


def quantile_grid(values, n_points: int = 101) -> np.ndarray:
    v = np.asarray([x for x in values if pd.notna(x)], dtype=float)
    if len(v) == 0:
        return np.array([0.0])
    if len(v) == 1:
        return np.repeat(v, n_points)
    return np.quantile(v, np.linspace(0.0, 1.0, n_points))


def draw_from_grid(rng: np.random.Generator, grid: np.ndarray,
                   size: int) -> np.ndarray:
    u = rng.random(size)
    return np.interp(u, np.linspace(0.0, 1.0, len(grid)), grid)


# ------------------------------------------------------------------
# League fit (design section 3.2 state functions + league tables).
# Fit ONLY on the seasons handed in (RD-2: prior seasons only).
# ------------------------------------------------------------------
class LeagueFit:
    def __init__(self, plays: pd.DataFrame, starts: pd.DataFrame):
        scr = plays[plays["is_scrimmage"] & plays["posteam"].notna()
                    & plays["diff_b"].between(0, 6)
                    & plays["time_b"].between(0, 4)].copy()
        self.n_plays = int(len(scr))
        # --- base pools (training-wide) ---
        run = scr[scr["family"] == 0]
        pas = scr[scr["play_type"] == "pass"]
        comp = pas[pas["complete_pass"] == 1]
        self.run_gains = run["yards_gained"].dropna().to_numpy()
        self.pass_gains = comp["yards_gained"].dropna().to_numpy()
        self.sack_losses = pas.loc[pas["sack"] == 1,
                                   "yards_gained"].dropna().to_numpy()
        # (down, ytg-bucket)-conditioned gain pools (RD-11), with
        # the pooled family arrays above as thin-cell fallback.
        self.run_gains_cond: dict[tuple[int, int], np.ndarray] = {}
        self.pass_gains_cond: dict[tuple[int, int], np.ndarray] = {}
        run_c = run[(run["play_type"] == "run")
                    & run["down"].notna() & run["ydstogo"].notna()]
        comp_c = comp[comp["down"].notna() & comp["ydstogo"].notna()]
        for dn in (1, 2, 3, 4):
            for yb in range(4):
                rsub = run_c[(run_c["down"] == dn)
                             & (run_c["ydstogo"].map(ytg_bucket) == yb)]
                psub = comp_c[(comp_c["down"] == dn)
                              & (comp_c["ydstogo"].map(ytg_bucket)
                                 == yb)]
                if len(rsub) >= 100:
                    self.run_gains_cond[(dn, yb)] = \
                        rsub["yards_gained"].dropna().to_numpy()
                if len(psub) >= 100:
                    self.pass_gains_cond[(dn, yb)] = \
                        psub["yards_gained"].dropna().to_numpy()
        self.sack_fum_rate = float(
            pas.loc[pas["sack"] == 1, "fumble_lost"].mean())
        # Pre-built per-cell draw arrays for the simulator's inner
        # loop (falls back to the pooled array per cell).
        self._run_pool_by_cell = {}
        self._pass_pool_by_cell = {}
        for dn in (1, 2, 3, 4):
            for yb in range(4):
                self._run_pool_by_cell[(dn, yb)] = \
                    self.run_gains_cond.get((dn, yb), self.run_gains)
                self._pass_pool_by_cell[(dn, yb)] = \
                    self.pass_gains_cond.get((dn, yb), self.pass_gains)
        # Play accounting identity (RD-11): in this pull
        # pass_attempt == 1 on every pass play, sacks included, so
        # completion / interception rates are fitted per NON-SACK
        # pass play - the partition the simulator draws.
        nonsack = pas[pas["sack"] != 1]
        comp_pas = pas[pas["complete_pass"] == 1]
        runfam = scr[scr["family"] == 0]
        self.base = {
            "pass_share_of_att": float((scr["pass_attempt"] == 1).mean()),
            "comp_rate": float((nonsack["complete_pass"] == 1).mean()),
            "sack_rate": float((pas["sack"] == 1).mean()),
            "int_rate": float(nonsack["interception"].mean()),
            "fum_rate_run": float(runfam["fumble_lost"].mean()),
            "fum_rate_pass": float(comp_pas["fumble_lost"].mean())
            if len(comp_pas) else 0.0,
            "fum_rate": float(scr["fumble_lost"].mean()),
            "rush_ypp": float(run["yards_gained"].mean()),
            "pass_ypp_att": float(pas["yards_gained"].mean()),
            "sec_per_play_neutral": float(
                scr.loc[scr["diff_b"] == 3, "sec_consumed"].mean()),
            "pen_rate": float(
                ((plays["penalty"] == 1)
                 & plays["play_type"].isin(
                     list(SCRIMMAGE_TYPES) + ["no_play"])).sum()
                / max(len(scr), 1)),
            "safety_rate_own5": float(
                scr.loc[scr["yardline_100"] >= 95, "safety"].mean())
            if (scr["yardline_100"] >= 95).any() else 0.0,
            "pat_kick_good": float(
                plays.loc[plays["extra_point_result"].isin(
                    ["good", "failed", "blocked"]),
                    "extra_point_result"].eq("good").mean()),
            "two_pt_success": float(
                plays.loc[plays["two_point_conv_result"].isin(
                    ["success", "failure"]),
                    "two_point_conv_result"].eq("success").mean()),
        }
        # penalty yardage mixes (offense / defense), RD-10
        pen = plays[(plays["penalty"] == 1) & plays["posteam"].notna()]
        off_pen = pen[pen["penalty_team"] == pen["posteam"]]
        def_pen = pen[pen["penalty_team"] == pen["defteam"]]
        self.pen_off_yards = off_pen["penalty_yards"].dropna().to_numpy()
        self.pen_def_yards = def_pen["penalty_yards"].dropna().to_numpy()
        self.pen_def_autofd = float(
            def_pen["first_down_penalty"].mean()) if len(def_pen) else 0.0
        self.pen_share_off = float(
            len(off_pen) / max(len(off_pen) + len(def_pen), 1))
        # --- state cells: pass prob, gain scale, pace grids ---
        self.pass_prob = np.zeros((7, 5))
        self.gain_scale = np.ones((7, 5, 2))
        self.pace_grids: dict[tuple[int, int, int], np.ndarray] = {}
        fam_global_mean = {0: float(run["yards_gained"].mean()),
                           1: float(pas["yards_gained"].mean())}
        fam_pace_pool = {f: scr.loc[scr["family"] == f, "sec_consumed"]
                         .dropna().to_numpy() for f in (0, 1)}
        for db in range(7):
            for tb in range(5):
                cell = scr[(scr["diff_b"] == db) & (scr["time_b"] == tb)]
                tb_all = scr[scr["time_b"] == tb]
                pool = cell if len(cell) >= 100 else tb_all
                self.pass_prob[db, tb] = float(
                    (pool["pass_attempt"] == 1).mean())
                for fam in (0, 1):
                    csub = cell[cell["family"] == fam]
                    base_pool = pas if fam == 1 else run
                    sub = csub if len(csub) >= 200 else base_pool
                    m = float(sub["yards_gained"].mean())
                    n = len(csub)
                    ratio = m / fam_global_mean[fam] if n else 1.0
                    shrunk = (n * ratio + 200.0) / (n + 200.0)
                    self.gain_scale[db, tb, fam] = float(
                        np.clip(shrunk, 0.70, 1.30))
                    psub = cell.loc[cell["family"] == fam, "sec_consumed"]
                    if len(psub) < 200:
                        psub = tb_all.loc[tb_all["family"] == fam,
                                           "sec_consumed"]
                    vals = psub.dropna().to_numpy()
                    if len(vals) < 50:
                        vals = fam_pace_pool[fam]
                    self.pace_grids[(db, tb, fam)] = quantile_grid(vals)
        # --- fourth-down decisions (RD-9) ---
        # Punt and field-goal rows carry down == 4 themselves, and a
        # scrimmage snap on 4th down IS the go decision, so the table
        # reads directly off every down==4 play, in its own pre-state.
        fd_all = plays[(plays["down"] == 4) & plays["posteam"].notna()
                       & plays["diff_b"].between(0, 6)
                       & plays["time_b"].between(0, 4)]
        decisions = []
        for r in fd_all.itertuples():
            if pd.isna(r.yardline_100) or pd.isna(r.ydstogo):
                continue
            if r.play_type == "punt":
                dec = "punt"
            elif r.play_type == "field_goal":
                dec = "fg"
            elif r.play_type in SCRIMMAGE_TYPES:
                dec = "go"
            else:
                continue
            decisions.append((r, dec))
        self.fd_table: dict[tuple[int, int, int], np.ndarray] = {}
        self.fd_marginal: dict[tuple[int, int], np.ndarray] = {}
        glob = np.zeros(3)
        for (r, dec) in decisions:
            fb = field_bucket(r.yardline_100)
            yb = ytg_bucket(r.ydstogo)
            late = 1 if (r.time_b >= 3 and abs(r.pre_diff) <= 8) else 0
            j = {"punt": 0, "fg": 1, "go": 2}[dec]
            glob[j] += 1
            for key, table in (((fb, yb, late), self.fd_table),
                               ((fb, yb), self.fd_marginal)):
                arr = table.setdefault(key, np.zeros(3))
                arr[j] += 1
        for table in (self.fd_table, self.fd_marginal):
            for k in table:
                table[k] = table[k] / table[k].sum()
        self.fd_global = glob / glob.sum()
        self.n_fd_decisions = int(len(decisions))
        # --- field-goal make curve by attempt distance ---
        fg = plays[plays["field_goal_result"].isin(
            ["made", "missed", "blocked"])].copy()
        fg["att_dist"] = fg["yardline_100"] + 17
        self.fg_curve: dict[int, float] = {}
        overall = float((fg["field_goal_result"] == "made").mean())
        for lo in range(18, 70, 5):
            sub = fg[(fg["att_dist"] >= lo) & (fg["att_dist"] < lo + 5)]
            if len(sub):
                p = float((sub["field_goal_result"] == "made").mean())
                self.fg_curve[lo] = shrunk_rate(
                    p * len(sub), len(sub), overall, prior=40.0)
        self.fg_overall = overall
        # Dense per-bucket lookup for the simulator's vectorized
        # FG draw: _fg_by_lo[lo] equals the fitted curve value at
        # bucket edge lo (fg_prob's semantics, FG-FIX).
        self._fg_by_lo = np.full(69, overall)
        for _lo, _p in self.fg_curve.items():
            if 0 <= int(_lo) < 69:
                self._fg_by_lo[int(_lo)] = _p
        # --- punt outcomes: receiver start by punt origin bucket ---
        punt_rows = plays[plays["play_type"] == "punt"].copy()
        start_map = starts.set_index(["game_id", "fixed_drive"])
        self.punt_grids: dict[int, np.ndarray] = {}
        punt_vals: dict[int, list] = {}
        for r in punt_rows.itertuples():
            key = (r.game_id, r.fixed_drive + 1)
            if key in start_map.index:
                rec = start_map.loc[key]
                if isinstance(rec, pd.DataFrame):
                    rec = rec.iloc[0]
                b = min(int(r.yardline_100 // 10), 9)
                punt_vals.setdefault(b, []).append(float(rec["x_start"]))
        all_punt = [v for vs in punt_vals.values() for v in vs]
        self.punt_grid_all = quantile_grid(all_punt)
        for b, vs in punt_vals.items():
            self.punt_grids[b] = quantile_grid(vs) if len(vs) >= 40 \
                else self.punt_grid_all
        # --- two-point decision rate after a TD ---
        td_plays = plays[plays["touchdown"] == 1].copy()
        conv = plays[plays["play_type"] == "extra_point"].copy()
        conv_by_game = conv.groupby("game_id")
        two_decisions = []
        for r in td_plays.itertuples():
            later = plays[(plays["game_id"] == r.game_id)
                          & (plays["play_id"] > r.play_id)
                          & (plays["play_id"] <= r.play_id + 60)]
            att2 = later[later["two_point_conv_result"].isin(
                ["success", "failure"])]
            kick = later[later["extra_point_result"].isin(
                ["good", "failed", "blocked"])]
            if len(att2) or len(kick):
                diff_after = abs(r.pre_diff + 6.0)
                two_decisions.append(
                    (1 if len(att2) else 0, r.time_b, diff_after))
        self.two_pt_rate = {}
        for tb in range(5):
            for band, lo, hi in (("close", 0, 4), ("mid", 4, 12),
                                 ("big", 12, 99)):
                sub = [x for x in two_decisions
                       if x[1] == tb and lo <= x[2] < hi]
                allsub = [x for x in two_decisions if lo <= x[2] < hi]
                pool = sub if len(sub) >= 30 else allsub
                self.two_pt_rate[(tb, band)] = float(
                    np.mean([x[0] for x in pool])) if pool else 0.03
        # Dense form for the simulator: [time bucket][band index
        # 0=close, 1=mid, 2=big] (same values as two_pt_rate).
        self.two_pt_arr = np.array(
            [[self.two_pt_rate[(t, b)]
              for b in ("close", "mid", "big")] for t in range(5)])
        # --- defensive TD share of turnover drives (RD-9) ---
        drv_res = plays.dropna(subset=["fixed_drive"]).groupby(
            ["game_id", "fixed_drive"])["fixed_drive_result"].first()
        n_opp = int((drv_res == "Opp touchdown").sum())
        n_to = int((drv_res == "Turnover").sum())
        self.opp_td_rate = n_opp / max(n_opp + n_to, 1)
        # --- league drive-start grid (all drives) ---
        self.league_start_grid = quantile_grid(starts["x_start"])

    def fg_prob(self, att_dist: float) -> float:
        # The fitted curve's buckets are [18+5k, 23+5k); the
        # lookup keys on the same edges (FG-FIX, module header).
        lo = int(min(max(18 + 5 * int((att_dist - 18) // 5), 18), 68))
        return float(self.fg_curve.get(lo, self.fg_overall))

    def state_summary(self) -> dict:
        """Key cells for the section-9 stability diagnostic."""
        out = {}
        for name, db, tb in (("q4le2_trail_big", 0, 4),
                             ("q4le2_trail_small", 2, 4),
                             ("q4le2_close", 3, 4),
                             ("q4le2_lead_small", 4, 4),
                             ("q4le2_lead_big", 6, 4),
                             ("q4le5_trail_small", 2, 3),
                             ("q3_close", 3, 1),
                             ("1h_close", 3, 0)):
            out[name] = {
                "pass_prob": float(self.pass_prob[db, tb]),
                "pace_run": float(np.mean(self.pace_grids[(db, tb, 0)])),
                "pace_pass": float(np.mean(self.pace_grids[(db, tb, 1)])),
                "gain_scale_run": float(self.gain_scale[db, tb, 0]),
                "gain_scale_pass": float(self.gain_scale[db, tb, 1]),
            }
        return out


def field_bucket(yardline_100: float) -> int:
    if yardline_100 <= 20:
        return 0
    if yardline_100 <= 30:
        return 1
    if yardline_100 <= 40:
        return 2
    if yardline_100 <= 50:
        return 3
    return 4


def ytg_bucket(ydstogo: float) -> int:
    if ydstogo <= 2:
        return 0
    if ydstogo <= 5:
        return 1
    if ydstogo <= 9:
        return 2
    return 3


# ------------------------------------------------------------------
# Point-in-time team rates (design section 3.3; RD-3/RD-4)
# ------------------------------------------------------------------
_LEAGUE_KEYS = ("n_run", "run_yards", "n_pass_att", "pass_yards",
               "n_complete", "n_sack", "int_thrown", "fum_lost",
               "n_run_faced", "run_yards_allowed", "n_pass_faced",
               "pass_yards_allowed", "sacks_made", "takeaways",
               "n_scrim", "pen_plays", "sec_neutral", "n_sec_neutral",
               "rz_trips", "rz_tds")


def _blank_agg() -> dict:
    return {k: 0.0 for k in _LEAGUE_KEYS}


def _add_agg(dst: dict, row: dict) -> None:
    for k in _LEAGUE_KEYS:
        dst[k] += float(row.get(k) or 0.0)


def league_rates(agg: dict) -> dict:
    """League per-play rates from an aggregate dict."""
    def rate(num, den):
        return num / den if den > 0 else 0.0
    return {
        "rush_ypp": rate(agg["run_yards"], agg["n_run"]),
        "pass_ypp_att": rate(agg["pass_yards"], agg["n_pass_att"]),
        "comp_rate": rate(agg["n_complete"], agg["n_pass_att"]),
        "sack_rate_att": rate(agg["n_sack"], agg["n_pass_att"]),
        "int_rate_att": rate(agg["int_thrown"], agg["n_pass_att"]),
        "fum_rate_scrim": rate(agg["fum_lost"], agg["n_scrim"]),
        "rush_ypp_allowed": rate(agg["run_yards_allowed"],
                                 agg["n_run_faced"]),
        "pass_ypp_allowed": rate(agg["pass_yards_allowed"],
                                 agg["n_pass_faced"]),
        "sack_rate_made": rate(agg["sacks_made"], agg["n_pass_faced"]),
        "takeaway_rate_faced": rate(agg["takeaways"], agg["n_scrim"]),
        "pen_rate": rate(agg["pen_plays"], agg["n_scrim"]),
        "sec_neutral": rate(agg["sec_neutral"], agg["n_sec_neutral"]),
        "rz_td_rate": rate(agg["rz_tds"], agg["rz_trips"]),
    }


class TeamRateBook:
    """Chronological team-game history + expanding league aggregates.
    A game's rates are read BEFORE the game is recorded (strictly
    prior games only), mirroring the v1 WalkForward discipline."""

    def __init__(self, agg: pd.DataFrame, game_order: pd.DataFrame):
        # game_order: game_id -> (season, week, gameday) chronological
        self.agg = agg.set_index(["game_id", "team"])
        self.order = game_order
        self.history: dict[str, list[dict]] = {}
        self.league_agg = _blank_agg()
        self.starts_league: list[float] = []

    def _sample(self, team: str, season: int) -> list[dict]:
        hist = self.history.get(team, [])
        same = [h for h in hist if h["season"] == season]
        if len(same) >= SAMPLE_CAP:
            return same[-SAMPLE_CAP:]
        prior = [h for h in hist if h["season"] < season]
        need = SAMPLE_CAP - len(same)
        return prior[-need:] + same if need > 0 else same

    def bundle(self, team: str, season: int) -> dict:
        """The section-3.3 rate bundle for `team` pricing a game in
        `season`, from strictly prior games only."""
        lg = league_rates(self.league_agg)
        sample = self._sample(team, season)
        s = _blank_agg()
        n_drives = 0.0
        starts: list[float] = []
        for h in sample:
            _add_agg(s, h)
            n_drives += float(h.get("n_drives") or 0.0)
            starts.extend(h.get("starts_list") or ())
        sr = league_rates(s)

        def factor(num_key_rate, league_val, sample_rate, den):
            """Shrunk rate ratio (sample vs league), prior 3 games."""
            if league_val <= 0:
                return 1.0
            shrunk = shrunk_rate(sample_rate * den, den, league_val)
            return float(np.clip(shrunk / league_val, 0.6, 1.6))

        return {
            "rush_factor": factor("rush", lg["rush_ypp"], sr["rush_ypp"],
                                  s["n_run"]),
            "pass_factor": factor("pass", lg["pass_ypp_att"],
                                  sr["pass_ypp_att"], s["n_pass_att"]),
            "comp_factor": factor("comp", lg["comp_rate"], sr["comp_rate"],
                                  s["n_pass_att"]),
            "sack_factor": factor("sack", lg["sack_rate_att"],
                                  sr["sack_rate_att"], s["n_pass_att"]),
            "int_factor": factor("int", lg["int_rate_att"],
                                 sr["int_rate_att"], s["n_pass_att"]),
            "fum_factor": factor("fum", lg["fum_rate_scrim"],
                                 sr["fum_rate_scrim"], s["n_scrim"]),
            "rush_allowed_factor": factor(
                "ra", lg["rush_ypp_allowed"], sr["rush_ypp_allowed"],
                s["n_run_faced"]),
            "pass_allowed_factor": factor(
                "pa", lg["pass_ypp_allowed"], sr["pass_ypp_allowed"],
                s["n_pass_faced"]),
            "sack_made_factor": factor("sm", lg["sack_rate_made"],
                                       sr["sack_rate_made"],
                                       s["n_pass_faced"]),
            "takeaway_factor": factor("tk", lg["takeaway_rate_faced"],
                                      sr["takeaway_rate_faced"],
                                      s["n_scrim"]),
            "pen_factor": factor("pen", lg["pen_rate"], sr["pen_rate"],
                                 s["n_scrim"]),
            "pace_ratio": float(np.clip(
                shrunk_mean(s["sec_neutral"], s["n_sec_neutral"],
                            lg["sec_neutral"]) / lg["sec_neutral"]
                if lg["sec_neutral"] > 0 else 1.0, 0.80, 1.25)),
            "rz_factor": float(np.clip(
                shrunk_rate(s["rz_tds"], s["rz_trips"], lg["rz_td_rate"],
                            prior=K_PRIOR_DRIVES)
                / lg["rz_td_rate"] if lg["rz_td_rate"] > 0 else 1.0,
                0.7, 1.4)),
            "starts": tuple(starts),
            "n_sample_games": len(sample),
            "league": lg,
        }

    def record_game(self, game_id: str) -> None:
        sub = self.agg.xs(game_id, level="game_id")
        for team, row in sub.iterrows():
            rec = row.to_dict()
            rec["season"] = int(row["season"])
            self.history.setdefault(team, []).append(rec)
            _add_agg(self.league_agg, rec)
            self.starts_league.extend(rec.get("starts_list") or ())


# ------------------------------------------------------------------
# Simulator (design section 3.1; RD-1 play-by-play; R = 10,000)
# ------------------------------------------------------------------
def _empirical_draw(rng, arr: np.ndarray, size: int) -> np.ndarray:
    if len(arr) == 0:
        return np.zeros(size)
    return arr[rng.integers(0, len(arr), size)]


def _cond_draw(rng, pools_by_cell: dict, down: np.ndarray,
               ytg: np.ndarray, mask: np.ndarray,
               cell_idx: np.ndarray | None = None) -> np.ndarray:
    """Draw gains from the (down, ytg-bucket)-conditioned pools
    (RD-11) for the masked replications. Cells are drawn in
    (down, ytg-bucket) ascending order - the same order and sizes
    as the original nested loop, so the RNG stream is unchanged.
    `cell_idx` may carry a caller-precomputed (down-1)*4+ytg_bucket
    index per replication."""
    out = np.zeros(len(mask))
    if not mask.any():
        return out
    if cell_idx is None:
        yb = np.select([ytg <= 2, ytg <= 5, ytg <= 9], [0, 1, 2],
                       default=3)
        dn = np.clip(down, 1, 4)
        cell_idx = (dn - 1) * 4 + yb
    for ci in np.unique(cell_idx[mask]):
        m = mask & (cell_idx == ci)
        out[m] = _empirical_draw(
            rng, pools_by_cell[(int(ci) // 4 + 1, int(ci) % 4)],
            int(m.sum()))
    return out


def _start_draw(rng, bundle: dict, league_grid: np.ndarray,
                size: int) -> np.ndarray:
    """Drive-start position (yards from own goal): the team's shrunk
    empirical starts mixed with the league grid (RD-3/RD-9)."""
    starts = bundle["starts"]
    if len(starts):
        w = len(starts) / (len(starts) + K_PRIOR_DRIVES)
        from_team = rng.random(size) < w
        team_draw = _empirical_draw(rng, np.asarray(starts), size)
        league_draw = draw_from_grid(rng, league_grid, size)
        return np.where(from_team, team_draw, league_draw)
    return draw_from_grid(rng, league_grid, size)


def simulate_game(fit: LeagueFit, home_b: dict, away_b: dict,
                  rng: np.random.Generator) -> dict:
    """Simulate one game R times. Returns per-replication quarter
    points for both teams plus build diagnostics. All state is
    per-replication; draws come only from `rng`."""
    R = R_REPS
    gsr = np.full(R, 3600.0)
    sh = np.zeros(R)
    sa = np.zeros(R)
    qh = np.zeros((R, 4))
    qa = np.zeros((R, 4))
    # Opening possession drawn per replication (RD-5); the other
    # team receives the second-half kickoff.
    home_ball = rng.random(R) < 0.5
    recv2h_home = ~home_ball
    half2 = np.zeros(R, dtype=bool)
    x = np.where(home_ball,
                 _start_draw(rng, home_b, fit.league_start_grid, R),
                 _start_draw(rng, away_b, fit.league_start_grid, R))
    down = np.ones(R, dtype=int)
    ytg = np.minimum(10.0, 100.0 - x)
    gsr = gsr - 5.0  # opening kickoff clock cost (RD-9)
    n_safeties = 0
    outcomes = {"td": 0, "fg_made": 0, "fg_missed": 0, "punt": 0,
                "turnover": 0, "def_td": 0, "downs": 0, "safety": 0,
                "expiry": 0}
    n_scrimmage = 0
    possessions = R  # the opening kickoff starts one per replication

    def bundle_arr(key, hb):
        return np.where(hb, home_b[key], away_b[key])

    def add_points(mask, pts, home_flags, ts_gsr):
        """Credit `pts` to the team flagged per replication in
        `home_flags` (True = home), in the quarter of `ts_gsr`."""
        rows = np.nonzero(mask)[0]
        if len(rows) == 0:
            return
        # Vectorized quarter_of (identical boundaries).
        tv = ts_gsr[rows]
        qs = (3 - (tv >= 900).astype(int) - (tv >= 1800).astype(int)
              - (tv >= 2700).astype(int))
        is_h = np.asarray(home_flags)[rows]
        if is_h.any():
            np.add.at(qh, (rows[is_h], qs[is_h]), pts)
        if (~is_h).any():
            np.add.at(qa, (rows[~is_h], qs[~is_h]), pts)

    def kickoff(mask, new_home_ball, sec_used):
        """Possession flips to new_home_ball with a drawn start."""
        nonlocal x, down, ytg, home_ball, gsr, possessions
        starts = np.where(
            new_home_ball,
            _start_draw(rng, home_b, fit.league_start_grid, R),
            _start_draw(rng, away_b, fit.league_start_grid, R))
        x = np.where(mask, starts, x)
        home_ball = np.where(mask, new_home_ball, home_ball)
        down = np.where(mask, 1, down)
        ytg = np.where(mask, np.minimum(10.0, 100.0 - x), ytg)
        new_gsr = np.where(mask, gsr - sec_used - 5.0, gsr)
        possessions += int((mask & (new_gsr > 0)).sum())
        gsr = new_gsr

    # Dense fourth-down table with hierarchical fallback (RD-9).
    fd_probs = np.tile(fit.fd_global, (5, 4, 2, 1)).astype(float)
    for (fb, yb), p in fit.fd_marginal.items():
        fd_probs[fb, yb, :, :] = p
    for (fb, yb, late), p in fit.fd_table.items():
        fd_probs[fb, yb, late, :] = p

    steps = 0
    while bool((gsr > 0).any()) and steps < 800:
        steps += 1
        # Halftime: reps that crossed into the second half reset to
        # the 2H kickoff (drive truncated by expiry, design 3.1).
        h2 = (gsr <= 1800) & (~half2) & (gsr > 0)
        if h2.any():
            gsr = np.where(h2, 1800.0, gsr)
            kickoff(h2, recv2h_home, 0.0)
            half2 = half2 | h2
        active = gsr > 0
        if not active.any():
            break
        diff = np.where(home_ball, sh - sa, sa - sh)
        db = np.searchsorted(DIFF_EDGES, diff, side="right").astype(int)
        tb = np.select([gsr > 1800, gsr > 900, gsr > 300, gsr > 120],
                       [0, 1, 2, 3], default=4).astype(int)
        off = {k: bundle_arr(k, home_ball) for k in (
            "rush_factor", "pass_factor", "comp_factor", "sack_factor",
            "int_factor", "fum_factor", "pen_factor", "pace_ratio",
            "rz_factor")}
        dfn = {k: bundle_arr(k, ~home_ball) for k in (
            "rush_allowed_factor", "pass_allowed_factor",
            "sack_made_factor", "takeaway_factor", "pen_factor")}
        resolved = ~active

        # Present (diff, time) cells among active replications,
        # computed once per step; pace_draw iterates exactly these
        # in (diff, time) ascending order - the same draw calls,
        # sizes, and order as the original full 7x5 loop.
        cell_masks = []
        for d_ in range(7):
            for t_ in range(5):
                m_ = active & (db == d_) & (tb == t_)
                if m_.any():
                    cell_masks.append((d_, t_, m_))

        def pace_draw(fam):
            out = np.zeros(R)
            for d_, t_, m in cell_masks:
                out[m] = draw_from_grid(
                    rng, fit.pace_grids[(d_, t_, fam)], int(m.sum()))
            return out * off["pace_ratio"]

        def ts_clamp(sec_used):
            raw = gsr - sec_used
            return np.where((gsr > 1800) & (raw < 1800), 1800.0,
                            np.maximum(raw, 0.0))

        # ---------- fourth-down decisions ----------
        fd_mask = active & (down == 4)
        if fd_mask.any():
            yl = 100.0 - x
            fb = np.select([yl <= 20, yl <= 30, yl <= 40, yl <= 50],
                           [0, 1, 2, 3], default=4).astype(int)
            yb = np.select([ytg <= 2, ytg <= 5, ytg <= 9],
                           [0, 1, 2], default=3).astype(int)
            late = ((tb >= 3) & (np.abs(diff) <= 8)).astype(int)
            probs = fd_probs[fb, yb, late]
            u = rng.random(R)
            punt_m = fd_mask & (u < probs[:, 0])
            fg_m = fd_mask & ~punt_m & (u < probs[:, 0] + probs[:, 1])
            if punt_m.any():
                sec = pace_draw(0)
                opp_start = np.zeros(R)
                for b in range(10):
                    m = punt_m & (np.minimum((100.0 - x) // 10, 9) == b)
                    if m.any():
                        opp_start[m] = draw_from_grid(
                            rng, fit.punt_grids.get(b, fit.punt_grid_all),
                            int(m.sum()))
                outcomes["punt"] += int(punt_m.sum())
                possessions += int(punt_m.sum())
                x = np.where(punt_m, opp_start, x)
                home_ball = np.where(punt_m, ~home_ball, home_ball)
                down = np.where(punt_m, 1, down)
                ytg = np.where(punt_m, np.minimum(10.0, 100.0 - x), ytg)
                gsr = np.where(punt_m, np.maximum(gsr - sec, 0.0), gsr)
                resolved = resolved | punt_m
            if fg_m.any():
                att = (100.0 - x) + 17.0
                lo_arr = np.clip(
                    18 + 5 * ((att - 18) // 5).astype(int), 18, 68)
                p_make = fit._fg_by_lo[lo_arr]
                made = fg_m & (rng.random(R) < p_make)
                missed = fg_m & ~made
                if made.any():
                    outcomes["fg_made"] += int(made.sum())
                    add_points(made, 3.0, home_ball, ts_clamp(4.0))
                    kickoff(made, ~home_ball, 4.0)
                if missed.any():
                    outcomes["fg_missed"] += int(missed.sum())
                    possessions += int(missed.sum())
                    x_opp = np.where((100.0 - x) <= 20, 20.0, 107.0 - x)
                    x = np.where(missed, np.clip(x_opp, 1.0, 99.0), x)
                    home_ball = np.where(missed, ~home_ball, home_ball)
                    down = np.where(missed, 1, down)
                    ytg = np.where(missed,
                                   np.minimum(10.0, 100.0 - x), ytg)
                    gsr = np.where(missed, np.maximum(gsr - 4.0, 0.0), gsr)
                resolved = resolved | fg_m
        # ---------- penalties (RD-10): in the PBP record most
        # penalty events are standalone no_play rows BETWEEN
        # scrimmage plays - they move the ball (and sometimes the
        # sticks) without consuming a play. The draw therefore
        # applies its effect first, and the scrimmage play of this
        # step still happens.
        play = active & ~resolved
        if play.any():
            pen_rate = fit.base["pen_rate"]
            p_off = pen_rate * fit.pen_share_off * off["pen_factor"]
            p_def = pen_rate * (1 - fit.pen_share_off) * dfn["pen_factor"]
            u_pen = rng.random(R)
            pen_off = play & (u_pen < p_off)
            pen_def = play & ~pen_off & (u_pen < p_off + p_def)
            if pen_off.any():
                yards = _empirical_draw(rng, fit.pen_off_yards, R)
                x = np.where(pen_off, np.maximum(x - yards, 1.0), x)
                ytg = np.where(pen_off, ytg + yards, ytg)
                gsr = np.where(pen_off,
                               np.maximum(gsr - 5.0, 0.0), gsr)
            if pen_def.any():
                yards = _empirical_draw(rng, fit.pen_def_yards, R)
                nx = np.minimum(x + yards, 99.0)
                fd_win = pen_def & ((yards >= ytg)
                                    | (rng.random(R)
                                       < fit.pen_def_autofd))
                x = np.where(pen_def, nx, x)
                down = np.where(fd_win, 1, down)
                ytg = np.where(fd_win, np.minimum(10.0, 100.0 - x),
                               np.where(pen_def,
                                        np.maximum(1.0, ytg - yards),
                                        ytg))
                gsr = np.where(pen_def,
                               np.maximum(gsr - 5.0, 0.0), gsr)
        play = active & ~resolved
        if play.any():
            n_scrimmage += int(play.sum())
            # (down, ytg-bucket) cell index per replication,
            # computed once for both gain-pool draws of this step
            # (down/ytg do not change between them).
            cell_idx_all = (np.clip(down, 1, 4) - 1) * 4 + np.select(
                [ytg <= 2, ytg <= 5, ytg <= 9], [0, 1, 2], default=3)
            is_pass = rng.random(R) < fit.pass_prob[db, tb]
            sec = np.where(is_pass, pace_draw(1), pace_draw(0))
            gain = np.zeros(R)
            turn = np.zeros(R, dtype=bool)
            turn_spot = x.copy()  # where a turnover hands the ball over
            ball_carried = np.zeros(R, dtype=bool)
            # pass branch
            pm = play & is_pass
            if pm.any():
                sack_p = np.clip(fit.base["sack_rate"] * off["sack_factor"]
                                 * dfn["sack_made_factor"], 0.0, 0.5)
                sack = pm & (rng.random(R) < sack_p)
                gain = np.where(sack, _empirical_draw(
                    rng, fit.sack_losses, R), gain)
                # strip-sack fumbles (RD-11): spot at the sack.
                sfum_p = np.clip(fit.sack_fum_rate * off["fum_factor"]
                                 * dfn["takeaway_factor"], 0.0, 0.5)
                sfum = sack & (rng.random(R) < sfum_p)
                if sfum.any():
                    turn = turn | sfum
                    turn_spot = np.where(sfum, x + gain, turn_spot)
                att_m = pm & ~sack
                int_p = np.clip(fit.base["int_rate"] * off["int_factor"]
                                * dfn["takeaway_factor"], 0.0, 0.25)
                intc = att_m & (rng.random(R) < int_p)
                turn = turn | intc
                comp_p = np.clip(fit.base["comp_rate"]
                                 * off["comp_factor"], 0.05, 0.97)
                comp = att_m & ~intc & (rng.random(R) < comp_p)
                g = _cond_draw(rng, fit._pass_pool_by_cell, down, ytg,
                               np.ones(R, dtype=bool),
                               cell_idx=cell_idx_all) \
                    * fit.gain_scale[db, tb, 1] * off["pass_factor"] \
                    * dfn["pass_allowed_factor"] \
                    * np.where(x >= 80, off["rz_factor"], 1.0)
                gain = np.where(comp, g, gain)
                ball_carried = ball_carried | comp
            # run branch
            rm = play & ~is_pass
            if rm.any():
                fum_p = np.clip(fit.base["fum_rate_run"]
                                * off["fum_factor"]
                                * dfn["takeaway_factor"], 0.0, 0.10)
                fum = rm & (rng.random(R) < fum_p)
                turn = turn | fum
                g = _cond_draw(rng, fit._run_pool_by_cell, down, ytg,
                               np.ones(R, dtype=bool),
                               cell_idx=cell_idx_all) \
                    * fit.gain_scale[db, tb, 0] * off["rush_factor"] \
                    * dfn["rush_allowed_factor"] \
                    * np.where(x >= 80, off["rz_factor"], 1.0)
                gain = np.where(rm & ~fum, g, gain)
            # fumbles on completed pass plays (RD-11): the fitted
            # per-completion rate, spot at the end of the play.
            pfum_p = np.clip(fit.base["fum_rate_pass"]
                             * off["fum_factor"]
                             * dfn["takeaway_factor"], 0.0, 0.10)
            pfum = play & ball_carried & ~turn & ((x + gain) < 100) \
                & (rng.random(R) < pfum_p)
            if pfum.any():
                turn = turn | pfum
                turn_spot = np.where(pfum, x + gain, turn_spot)
            nx = x + gain
            # safety: per-play draw at the fitted rate for plays
            # starting inside the offense's own 5 (RD-9); a drawn
            # gain crossing the goal line without the draw is
            # floored at the 1 in the continuation below.
            saf = play & (x <= 5) \
                & (rng.random(R) < fit.base["safety_rate_own5"])
            turn = turn & ~saf
            if saf.any():
                n_safeties += int(saf.sum())
                outcomes["safety"] += int(saf.sum())
                add_points(saf, 2.0, ~home_ball, ts_clamp(sec))
                kickoff(saf, ~home_ball, sec)
            # touchdowns (+ conversion)
            td = play & ~turn & ~saf & (nx >= 100)
            if td.any():
                outcomes["td"] += int(td.sum())
                add_points(td, 6.0, home_ball, ts_clamp(sec))
                sh = np.where(td & home_ball, sh + 6.0, sh)
                sa = np.where(td & ~home_ball, sa + 6.0, sa)
                d_after = diff + 6.0
                band_idx = np.select(
                    [np.abs(d_after) < 4, np.abs(d_after) < 12],
                    [0, 1], default=2)
                two_rate = fit.two_pt_arr[tb, band_idx]
                go2 = td & (rng.random(R) < two_rate)
                conv = go2 & (rng.random(R)
                              < fit.base["two_pt_success"])
                kick = td & ~go2 & (rng.random(R)
                                    < fit.base["pat_kick_good"])
                add_points(conv, 2.0, home_ball, ts_clamp(sec))
                add_points(kick, 1.0, home_ball, ts_clamp(sec))
                sh = np.where(conv & home_ball, sh + 2.0, sh)
                sa = np.where(conv & ~home_ball, sa + 2.0, sa)
                sh = np.where(kick & home_ball, sh + 1.0, sh)
                sa = np.where(kick & ~home_ball, sa + 1.0, sa)
                kickoff(td, ~home_ball, sec)
            # turnovers: a fitted share are returned for a
            # defensive TD (RD-9); the rest flip at the spot.
            if turn.any():
                outcomes["turnover"] += int(turn.sum())
                def_td = turn & (rng.random(R) < fit.opp_td_rate)
                if def_td.any():
                    outcomes["def_td"] += int(def_td.sum())
                    add_points(def_td, 6.0, ~home_ball, ts_clamp(sec))
                    sh = np.where(def_td & ~home_ball, sh + 6.0, sh)
                    sa = np.where(def_td & home_ball, sa + 6.0, sa)
                    pat = def_td & (rng.random(R)
                                    < fit.base["pat_kick_good"])
                    add_points(pat, 1.0, ~home_ball, ts_clamp(sec))
                    sh = np.where(pat & ~home_ball, sh + 1.0, sh)
                    sa = np.where(pat & home_ball, sa + 1.0, sa)
                    kickoff(def_td, home_ball, sec)
                plain = turn & ~def_td
                if plain.any():
                    possessions += int(plain.sum())
                    x_opp = np.where(
                        turn_spot >= 99, 20.0,
                        np.clip(100.0 - turn_spot, 1.0, 99.0))
                    x = np.where(plain, x_opp, x)
                    home_ball = np.where(plain, ~home_ball, home_ball)
                    down = np.where(plain, 1, down)
                    ytg = np.where(plain,
                                   np.minimum(10.0, 100.0 - x), ytg)
                    gsr = np.where(plain,
                                   np.maximum(gsr - sec, 0.0), gsr)
            # ordinary continuation
            cont = play & ~turn & ~saf & ~td
            if cont.any():
                first = cont & (gain >= ytg)
                x = np.where(cont, np.maximum(nx, 1.0), x)
                down = np.where(first, 1,
                                np.where(cont, down + 1, down))
                ytg = np.where(first, np.minimum(10.0, 100.0 - x),
                               np.where(cont, ytg - gain, ytg))
                downs = cont & (down > 4)
                if downs.any():
                    outcomes["downs"] += int(downs.sum())
                    possessions += int(downs.sum())
                    x = np.where(downs, np.clip(100.0 - x, 1.0, 99.0), x)
                    home_ball = np.where(downs, ~home_ball, home_ball)
                    down = np.where(downs, 1, down)
                    ytg = np.where(downs,
                                   np.minimum(10.0, 100.0 - x), ytg)
                gsr = np.where(cont, np.maximum(gsr - sec, 0.0), gsr)
    outcomes["expiry"] = int(possessions - sum(
        outcomes[k] for k in ("td", "fg_made", "fg_missed", "punt",
                              "turnover", "downs", "safety")))
    outcomes["possessions_per_game"] = possessions / R
    return {"home_q": qh, "away_q": qa, "steps": steps,
            "n_safeties": n_safeties,
            "unfinished": int((gsr > 0).sum()),
            "drive_outcomes": outcomes,
            "scrimmage_plays_per_team_game": n_scrimmage / (2.0 * R)}


# ------------------------------------------------------------------
# Panel integrity (design section 6.5 guard - re-run, not assumed)
# ------------------------------------------------------------------
def panel_integrity(panel: pd.DataFrame, games: pd.DataFrame) -> dict:
    finals = {}
    reg = games[(games["game_type"] == "REG")
                & games["home_score"].notna()]
    for r in reg.itertuples():
        finals[(r.game_id, r.home_team)] = (float(r.home_score),
                                            bool(r.overtime))
        finals[(r.game_id, r.away_team)] = (float(r.away_score),
                                            bool(r.overtime))
    n, exact, ot_only, neg, nan = 0, 0, 0, 0, 0
    unexplained = []
    for r in panel.itertuples():
        tot = r.q1 + r.q2 + r.q3 + r.q4
        if any(pd.isna(v) for v in (r.q1, r.q2, r.q3, r.q4)):
            nan += 1
            continue
        fin, is_ot = finals[(r.game_id, r.team)]
        d = fin - tot
        n += 1
        if d == 0:
            exact += 1
        elif d > 0 and is_ot:
            ot_only += 1
        elif d < 0:
            neg += 1
        else:
            unexplained.append((r.game_id, r.team, fin, tot))
    return {"n_team_games": n,
            "exact_share": exact / n if n else 0.0,
            "ot_only_share": ot_only / n if n else 0.0,
            "negative_diffs": neg, "nan_rows": nan,
            "unexplained": unexplained[:10]}


def baseline_rows(v1, wf, panel: pd.DataFrame) -> pd.DataFrame:
    """Per-team-game B0/B1 predictions, replicating v1's
    run_period_screen state machine exactly (weekly batching,
    point-in-time league shares), extended to keep per-row values
    for the Q4 state breakdown. The caller asserts this frame's
    aggregates equal run_period_screen's own output."""
    panel = panel.sort_values(["season", "week", "game_id", "team"])
    team_periods: dict[str, list] = {}
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

    rows = []
    for (season, week), wk in panel.groupby(["season", "week"]):
        l_share = league_share(int(season))
        for r in wk.itertuples():
            mu = wf.mu_by_game_team.get((r.game_id, r.team))
            if mu is None:
                continue
            realized = np.array([r.q1, r.q2, r.q3, r.q4], dtype=float)
            rows.append({
                "game_id": r.game_id, "season": int(season),
                "week": int(week), "team": r.team, "mu": mu,
                "real_q": realized,
                "b0_q": mu * l_share,
                "b1_q": mu * np.array([0.25, 0.25, 0.25, 0.25]),
            })
        for r in wk.itertuples():
            arr = np.array([r.q1, r.q2, r.q3, r.q4])
            team_periods.setdefault(r.team, []).append((int(season), arr))
            season_period_pts[int(season)] = \
                season_period_pts.get(int(season), np.zeros(4)) + arr
            season_total_pts[int(season)] = \
                season_total_pts.get(int(season), 0.0) + float(arr.sum())
        last_week = int(panel[panel.season == season].week.max())
        if int(week) == last_week:
            tot = season_total_pts.get(int(season), 0.0)
            if tot > 0:
                prev_season_share[int(season)] = \
                    season_period_pts[int(season)] / tot
    df = pd.DataFrame(rows)
    # realized margin entering Q4, from the team's perspective
    by_game = {}
    for r in df.itertuples():
        by_game.setdefault(r.game_id, {})[r.team] = r.real_q
    margins = []
    for r in df.itertuples():
        others = [v for t, v in by_game[r.game_id].items() if t != r.team]
        opp = others[0]
        margins.append(float(r.real_q[:3].sum() - opp[:3].sum()))
    df["q4_enter_margin"] = margins
    return df


def bucket_errors(real_q: np.ndarray, pred_q: np.ndarray) -> dict:
    e = np.abs(np.asarray(pred_q) - np.asarray(real_q))
    return {"Q1": e[0], "Q2": e[1], "Q3": e[2], "Q4": e[3],
            "1H": abs(pred_q[0] + pred_q[1] - real_q[0] - real_q[1]),
            "2H": abs(pred_q[2] + pred_q[3] - real_q[2] - real_q[3])}


def evaluate_arms(df: pd.DataFrame, m_col: str = "m_q") -> dict:
    """MAE table + the four design-section-5 legs for arm M in
    column `m_col` against B0/B1 columns of `df`."""
    per_bucket = {b: {"m": [], "b0": [], "b1": []} for b in BUCKETS}
    per_season = {}
    for r in df.itertuples():
        em = bucket_errors(r.real_q, getattr(r, m_col))
        e0 = bucket_errors(r.real_q, r.b0_q)
        e1 = bucket_errors(r.real_q, r.b1_q)
        for b in BUCKETS:
            per_bucket[b]["m"].append(em[b])
            per_bucket[b]["b0"].append(e0[b])
            per_bucket[b]["b1"].append(e1[b])
        ps = per_season.setdefault(int(r.season),
                                   {"m": [], "b0": [], "b1": []})
        for b in BUCKETS:
            ps["m"].append(em[b])
            ps["b0"].append(e0[b])
            ps["b1"].append(e1[b])
    table = {b: {k: float(np.mean(v)) for k, v in per_bucket[b].items()}
             for b in BUCKETS}
    pooled = {k: float(np.mean([e for b in BUCKETS
                                 for e in per_bucket[b][k]]))
              for k in ("m", "b0", "b1")}
    seasons = {s: {k: float(np.mean(v)) for k, v in ps.items()}
               for s, ps in per_season.items()}
    wins = sum(1 for b in BUCKETS if table[b]["m"] < table[b]["b0"])
    legs = {
        "L1_pooled_beats_b0_and_b1": bool(
            pooled["m"] < pooled["b0"] and pooled["m"] < pooled["b1"]),
        "L2_buckets_beating_b0": {"wins": wins, "need": 4,
                                  "pass": bool(wins >= 4)},
        "L3_q4_beats_b0": bool(table["Q4"]["m"] < table["Q4"]["b0"]),
        "L4_stability": {
            "per_season_excess": {s: seasons[s]["m"] - seasons[s]["b0"]
                                  for s in seasons},
            "pass": bool(all(seasons[s]["m"] <= seasons[s]["b0"]
                             + STABILITY_SLACK for s in seasons))},
    }
    passed = bool(legs["L1_pooled_beats_b0_and_b1"]
                  and legs["L2_buckets_beating_b0"]["pass"]
                  and legs["L3_q4_beats_b0"]
                  and legs["L4_stability"]["pass"])
    return {"bucket_mae": table, "pooled_mae": pooled,
            "per_season_pooled_mae": seasons, "legs": legs,
            "screen_pass": passed}


# ------------------------------------------------------------------
# Base-rate reproduction diagnostic (build validation, design
# section 6.5's logic: a simulator that cannot reproduce the game
# it claims to model is mis-built, whatever its screen MAE says).
# League-average bundles on the fit's OWN training window; the
# acceptance bands below were fixed before the diagnostic was run:
#   |points/team-game sim - real| <= 1.0
#   |scrimmage plays/team-game sim - real| <= 3.0
#   |TD drive share sim - real| <= 0.02
#   |punt drive share sim - real| <= 0.03
# ------------------------------------------------------------------
DIAGNOSTIC_SEED = 20261027
DIAGNOSTIC_REPS = 2000


def base_rate_diagnostic(plays_train: pd.DataFrame,
                         starts_train: pd.DataFrame,
                         fit: LeagueFit) -> dict:
    games_n = plays_train["game_id"].nunique()
    scr = plays_train[plays_train["is_scrimmage"]]
    fin = plays_train.groupby("game_id")[
        ["total_home_score", "total_away_score"]].max()
    real_points = float((fin["total_home_score"].mean()
                         + fin["total_away_score"].mean()) / 2)
    real_plays = len(scr) / (2.0 * games_n)
    res = plays_train.dropna(subset=["fixed_drive"]).groupby(
        ["game_id", "fixed_drive"])["fixed_drive_result"].first()
    shares = res.value_counts(normalize=True)
    real = {"points_per_team_game": real_points,
            "plays_per_team_game": float(real_plays),
            "td_share": float(shares.get("Touchdown", 0.0)),
            "punt_share": float(shares.get("Punt", 0.0)),
            "drives_per_game": float(len(res) / games_n)}
    blank = {k: 1.0 for k in (
        "rush_factor", "pass_factor", "comp_factor", "sack_factor",
        "int_factor", "fum_factor", "rush_allowed_factor",
        "pass_allowed_factor", "sack_made_factor", "takeaway_factor",
        "pen_factor", "pace_ratio", "rz_factor")}
    blank.update({
        "starts": tuple(float(v) for v in starts_train["x_start"]),
        "n_sample_games": 0,
        "league": league_rates({k: 0.0 for k in _LEAGUE_KEYS})})
    global R_REPS
    saved = R_REPS
    R_REPS = DIAGNOSTIC_REPS
    try:
        rng = np.random.default_rng(
            np.random.SeedSequence([DIAGNOSTIC_SEED, 0]))
        sim = simulate_game(fit, blank, blank, rng)
    finally:
        R_REPS = saved
    o = sim["drive_outcomes"]
    tot = sum(v for k, v in o.items()
              if k not in ("possessions_per_game", "def_td"))
    sim_d = {
        "points_per_team_game": float(
            (sim["home_q"].sum(1).mean() + sim["away_q"].sum(1).mean())
            / 2),
        "plays_per_team_game": float(
            sim["scrimmage_plays_per_team_game"]),
        "td_share": o["td"] / tot, "punt_share": o["punt"] / tot,
        "drives_per_game": float(o["possessions_per_game"]),
        "outcome_shares": {k: v / tot for k, v in o.items()
                           if k not in ("possessions_per_game",
                                        "def_td")},
        "def_td_per_game": o["def_td"] / DIAGNOSTIC_REPS,
    }
    checks = {
        "points": abs(sim_d["points_per_team_game"]
                      - real["points_per_team_game"]) <= 1.0,
        "plays": abs(sim_d["plays_per_team_game"]
                     - real["plays_per_team_game"]) <= 3.0,
        "td_share": abs(sim_d["td_share"] - real["td_share"]) <= 0.02,
        "punt_share": abs(sim_d["punt_share"]
                          - real["punt_share"]) <= 0.03,
    }
    return {"real": real, "sim": sim_d, "checks": checks,
            "accepted": bool(all(checks.values()))}


# ------------------------------------------------------------------
# Screen driver
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# Parallel game simulation. Results are reassembled in job order
# and per-game streams derive from SeedSequence([seed, job
# index]), so the numbers are identical for any worker count.
# ------------------------------------------------------------------
_PAR_FITS: dict = {}


def _par_init(fits: dict) -> None:
    global _PAR_FITS
    _PAR_FITS = fits


def _sim_job(task):
    j, seed, job = task
    rng = np.random.default_rng(np.random.SeedSequence([seed, j]))
    sim = simulate_game(_PAR_FITS[job["season"]], job["home_b"],
                        job["away_b"], rng)
    return (j, sim["home_q"].mean(axis=0), sim["away_q"].mean(axis=0),
            float(sim["home_q"].sum(axis=1).mean()),
            float(sim["away_q"].sum(axis=1).mean()),
            int(sim["n_safeties"]), int(sim["unfinished"]))


def _bucket_maes_from_base(base: pd.DataFrame, col: str) -> dict:
    per = {b: [] for b in BUCKETS}
    for r in base.itertuples():
        e = bucket_errors(r.real_q, getattr(r, col))
        for b in BUCKETS:
            per[b].append(e[b])
    return {b: float(np.mean(v)) for b, v in per.items()}


def run_screen(cache_dir: str, workers: int = 2) -> dict:
    v1 = load_v1_module()
    hashes: dict[str, str] = {}
    gpath, gh = v1.fetch(cache_dir, "games.csv.gz", v1.SCHEDULES_URL)
    hashes["games_csv_gz"] = gh
    games = pd.read_csv(gpath, low_memory=False)

    # Sibling means + period panel + baselines: the v1 pack's own
    # machinery, imported unmodified (frozen sibling untouched).
    wf = v1.WalkForward(games)
    tt = v1.run_team_total_screen(wf)
    panel = v1.build_period_panel(cache_dir, hashes)
    integrity = panel_integrity(panel, games)
    v1_periods = v1.run_period_screen(wf, panel)
    base = baseline_rows(v1, wf, panel)
    repro = {"n_v1": v1_periods["n_team_games"], "n_base": int(len(base))}
    for arm, col in (("b0", "b0_q"), ("b1", "b1_q")):
        mine = _bucket_maes_from_base(base, col)
        diffs = {b: abs(mine[b] - v1_periods["buckets"][b][arm])
                 for b in BUCKETS}
        repro[f"max_bucket_diff_{arm}"] = float(max(diffs.values()))
        repro[f"pooled_diff_{arm}"] = float(abs(
            float(np.mean(list(mine.values())))
            - v1_periods["pooled_mae"][arm]))

    # PBP for rates / state functions (2022 = training + supplement).
    pbp = load_pbp(cache_dir, range(TRAIN_BASE_SEASON, 2026), hashes)
    plays = prepare_plays(pbp)
    starts = drive_starts(plays)
    season_of_game = plays.groupby("game_id")["season"].first()
    starts = starts.assign(
        season=starts["game_id"].map(season_of_game)).dropna(
            subset=["season"])
    agg = team_game_aggregates(plays, starts)

    # League fits: per eval season on PRIOR seasons only (RD-2), and
    # per single season for the section-9 stability diagnostic.
    fits, stability, diagnostics = {}, {}, {}
    for s in EVAL_SEASONS:
        tr_plays = plays[plays["season"] < s]
        tr_starts = starts[starts["season"] < s]
        fits[s] = LeagueFit(tr_plays, tr_starts)
        diagnostics[s] = base_rate_diagnostic(tr_plays, tr_starts,
                                              fits[s])
        own_plays = plays[plays["season"] == s]
        own_starts = starts[starts["season"] == s]
        stability[s] = LeagueFit(own_plays, own_starts).state_summary()

    # Chronological point-in-time team rates (RD-3/RD-4).
    sched = games[(games["game_type"] == "REG")
                  & games["home_score"].notna()].copy()
    sched = sched.sort_values(["season", "week", "gameday", "game_id"])
    game_meta = {r.game_id: (int(r.season), r.home_team, r.away_team)
                 for r in sched.itertuples()
                 if TRAIN_BASE_SEASON <= int(r.season) <= 2025}
    book = TeamRateBook(agg, None)
    panel_games = set(panel["game_id"])
    jobs = []
    for gid in sched["game_id"]:
        if gid not in game_meta:
            continue
        season, home_team, away_team = game_meta[gid]
        if gid in panel_games:
            jobs.append({
                "game_id": gid, "season": season,
                "home_team": home_team, "away_team": away_team,
                "home_b": book.bundle(home_team, season),
                "away_b": book.bundle(away_team, season),
                "fit": fits[season],
            })
        if gid in book.agg.index.get_level_values("game_id"):
            book.record_game(gid)

    base_idx = base.set_index(["game_id", "team"])
    seed_results = {}
    for seed in (SEED_A, SEED_B):
        m_q: dict[tuple[str, str], np.ndarray] = {}
        coherence = []
        total_safeties = 0
        unfinished = 0
        slim = [{k: v for k, v in job.items() if k != "fit"}
                for job in jobs]
        tasks = [(j, seed, slim[j]) for j in range(len(jobs))]
        if workers > 1 and len(jobs) > 1:
            import multiprocessing as mp
            with mp.get_context("fork").Pool(
                    workers, initializer=_par_init,
                    initargs=(fits,)) as pool:
                results = list(pool.imap(_sim_job, tasks,
                                         chunksize=8))
        else:
            _par_init(fits)
            results = [_sim_job(t) for t in tasks]
        for (j, hq, aq, h_tot, a_tot, n_saf, unfin) in results:
            job = jobs[j]
            total_safeties += n_saf
            unfinished += unfin
            m_q[(job["game_id"], job["home_team"])] = hq
            m_q[(job["game_id"], job["away_team"])] = aq
            for team, tot in ((job["home_team"], h_tot),
                              (job["away_team"], a_tot)):
                mu = base_idx.loc[(job["game_id"], team), "mu"]
                coherence.append((tot, float(mu)))
        df = base.copy()
        df["m_q"] = [m_q[(g, t)] for g, t in zip(df["game_id"],
                                                 df["team"])]
        ev = evaluate_arms(df)
        # Q4 state-conditional breakdown (reporting only, design 5)
        q4_break: dict[str, dict] = {}
        for r in df.itertuples():
            b = str(diff_bucket(r.q4_enter_margin))
            slot = q4_break.setdefault(b, {"m": [], "b0": [], "n": 0})
            slot["m"].append(abs(r.m_q[3] - r.real_q[3]))
            slot["b0"].append(abs(r.b0_q[3] - r.real_q[3]))
            slot["n"] += 1
        q4_break = {k: {"n": v["n"], "mae_m": float(np.mean(v["m"])),
                        "mae_b0": float(np.mean(v["b0"]))}
                    for k, v in sorted(q4_break.items())}
        coh = np.array(coherence)
        ev["q4_state_breakdown"] = q4_break
        ev["coherence_vs_sibling"] = {
            "mean_sim_minus_sibling": float((coh[:, 0] - coh[:, 1]).mean()),
            "mae_sim_vs_sibling": float(
                np.abs(coh[:, 0] - coh[:, 1]).mean()),
            "corr": float(np.corrcoef(coh[:, 0], coh[:, 1])[0, 1]),
        }
        ev["sim_diagnostics"] = {
            "total_safeties": total_safeties,
            "safeties_per_game": total_safeties / max(len(jobs), 1),
            "unfinished_reps": unfinished,
            "training_safety_rate_own5": float(
                np.mean([fits[s].base["safety_rate_own5"]
                         for s in EVAL_SEASONS])),
        }
        seed_results[seed] = ev

    pass_a = seed_results[SEED_A]["screen_pass"]
    pass_b = seed_results[SEED_B]["screen_pass"]
    if pass_a and pass_b:
        verdict = "SCREEN_PASS"
    elif not pass_a and not pass_b:
        verdict = "SCREEN_FAIL"
    else:
        verdict = "NOT_EXECUTABLE_CONTESTED_SEED_FLIP"
    return {
        "kind": "DESIGN_SCREEN",
        "construction": "NFL_PERIOD_DRIVE_STATE_V2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs_sha256": hashes,
        "note": ("Design screen on seen seasons (2023-2025 DESIGN "
                 "data); entry ticket only, never validation. No "
                 "market line is an input to any arm."),
        "panel_integrity": integrity,
        "baseline_reproduction_vs_v1_screen": repro,
        "v1_screen_recorded": {
            "pooled_mae": v1_periods["pooled_mae"],
            "buckets": v1_periods["buckets"],
            "n_team_games": v1_periods["n_team_games"],
        },
        "sibling_team_total_screen": {
            "pooled_cv_c": tt["pooled_cv_c"],
            "pooled_mae_mu": tt["pooled"]["mae_mu"],
        },
        "state_stability_diagnostic": {
            str(s): stability[s] for s in EVAL_SEASONS},
        "base_rate_diagnostics": {
            str(s): diagnostics[s] for s in EVAL_SEASONS},
        "seeds": {str(seed): seed_results[seed]
                  for seed in (SEED_A, SEED_B)},
        "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(_HERE,
                                                    ".screen_cache"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--diagnostic", action="store_true",
                    help="run only the base-rate build diagnostics "
                         "(no screen simulation, no verdict)")
    ap.add_argument("--workers", type=int, default=2,
                    help="parallel game-simulation workers "
                         "(results are worker-count invariant)")
    args = ap.parse_args()
    os.makedirs(args.cache, exist_ok=True)
    if args.diagnostic:
        hashes: dict[str, str] = {}
        pbp = load_pbp(args.cache, range(TRAIN_BASE_SEASON, 2026),
                       hashes)
        plays = prepare_plays(pbp)
        starts = drive_starts(plays)
        season_of_game = plays.groupby("game_id")["season"].first()
        starts = starts.assign(
            season=starts["game_id"].map(season_of_game)).dropna(
                subset=["season"])
        out = {}
        for s in EVAL_SEASONS:
            tr_plays = plays[plays["season"] < s]
            tr_starts = starts[starts["season"] < s]
            fit = LeagueFit(tr_plays, tr_starts)
            out[str(s)] = base_rate_diagnostic(tr_plays, tr_starts, fit)
        print(json.dumps(out, indent=1, default=float))
        return 0
    report = run_screen(args.cache, workers=args.workers)
    text = json.dumps(report, indent=1, default=float)
    out_path = args.out or os.path.join(_HERE, "screen_results_v2.json")
    with open(out_path, "w") as fh:
        fh.write(text + "\n")
    print(json.dumps({"verdict": report["verdict"],
                      "panel_integrity": report["panel_integrity"],
                      "reproduction": report[
                          "baseline_reproduction_vs_v1_screen"],
                      "pooled_by_seed": {
                          s: report["seeds"][s]["pooled_mae"]
                          for s in report["seeds"]}}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
