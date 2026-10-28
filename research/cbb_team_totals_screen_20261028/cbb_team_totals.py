#!/usr/bin/env python3
"""CBB team totals — the construction, exactly as designed.

Design of record (both documents merged in PR #2843):

* research/nba_cbb_activation_20261028/CBB_TEAM_TOTALS_1H_DESIGN.md
  section 1: "Team totals need no second model: the expected team
  points of CBB_TORVIK_EFFICIENCY_V1 ... *are* the team-total
  forecasts, home and away. The family therefore: Screens inside the
  section 3 design screen of the sides/totals document, as a third
  leg: team-points MAE, candidate vs (i) a naive team-mean baseline
  and (ii) the simple ratings baseline's team points, same pins, same
  walk-forward protocol, same DESIGN-evidence label. The leg passes
  or fails on its own CI, independently of the spread/total legs."
* research/nba_cbb_activation_20261028/
  CBB_SIDES_TOTALS_DESIGN_AND_PREREG_DRAFT.md section 1 (the parent
  construction) and section 3 (the screen spec).

Construction (parent design section 1), implemented verbatim:

* Inputs are exactly one source: the BartTorvik T-Rank archive
  row for the game, taken only via the PR #2832 admitted route
  under the input convention declared by Amendment 1 (PR #2883,
  merged): the PRIOR-SNAPSHOT convention — for a game on date D
  the input file is dated D-1, the last end-of-day snapshot
  strictly before D; a missing D-1 file makes the fixture
  NO_DATA, never substituted. (The design's original morning-of
  premise was falsified on the pinned bytes — the archive files
  are end-of-day; the first screen run, PR #2882, refused with
  AS_OF_PREMISE_FAILURE. Amendment 1 is the declared convention
  the PR #2832 rule-4 route required.)
* Expected possessions = blend of the two teams' adj_tempo. The
  design says "blend" without naming the operator; this packet
  operationalizes it as the arithmetic mean — the same reading the
  parent screen's attempt 3 recorded — and flags it here and in
  the screen report as an operationalization, not a design term.
* Expected team points = (team adj_o + opponent adj_d - league mean
  efficiency) / 100 * expected possessions, each term as of the
  prior snapshot for D. League mean efficiency / league mean tempo
  are computed over the prior-snapshot file for D as published
  (mean of adj_o / adj_tempo over the file's team rows) — the
  parent attempt-3 convention, applied to the D-1 file.
* The home-court term enters the parent design's MARGIN only; a
  single team's expected points carry no home-court term, for the
  candidate and for both baselines alike.

Baselines (team-totals design section 1):

* (i) Naive team-mean: the team's own mean points scored, computed
  over three-way-verified fixtures from seasons strictly before
  the scored season (the walk-forward discipline the parent
  section 3 protocol imposes on every fitted quantity); a team
  with no prior-season verified history takes the league mean
  team points over the same prior-season window. Operationalization
  recorded here and in the report; the design names the baseline
  ("a naive team-mean baseline") without a formula.
* (ii) The simple ratings baseline's team points: the parent
  section 1 baseline is the same expected-points formula with
  league-mean tempo — "no tempo interaction for totals" — i.e.
  the ablation of the candidate's claimed tempo-blend addition.
  (The baseline's fixed home-court constant belongs to its margin;
  it does not enter team points, exactly as for the candidate.)

Metrics (parent section 3 + team-totals section 1): team-points MAE
per team-game (each fixture contributes two observations, home and
away), candidate vs each baseline, paired per team-game; season-
block bootstrap (10,000 resamples of the scored seasons, seed
20261028 — the parent screen's constants), percentile 95% CI on the
mean paired difference (candidate MAE - baseline MAE). The leg's
bar, in the parent section 3 form: CI upper bound < 0 against BOTH
baselines. A pass is labelled DESIGN_PASS — design evidence only,
never validation (parent section 3).

This module is pure: no I/O, no network. The runner
(run_team_totals_screen.py) owns pins, fixtures, and the as-of
premise audit. Stdlib only.
"""

import random

# Parent screen constants (attempt-3 record; PR #2843 section 3
# specifies "paired, season-block bootstrap CIs" — reps/seed are the
# parent screen's recorded operationalization).
BOOTSTRAP_REPS = 10000
BOOTSTRAP_SEED = 20261028

# Design seasons (parent section 3): the admitted archive's
# coverage, 2014-15 -> 2022-23. 2014-15 is the initial fitting
# window (naive history) and is not scored, mirroring the parent
# screen's walk-forward protocol.
FIRST_WINDOW_YEAR = 2015          # season labelled 2014-15
LAST_YEAR = 2023                  # season labelled 2022-23
SCORED_YEARS = list(range(2016, 2024))

SEASON_LABEL = {2015: "2014-15", 2016: "2015-16", 2017: "2016-17",
                2018: "2017-18", 2019: "2018-19", 2020: "2019-20",
                2021: "2020-21", 2022: "2021-22", 2023: "2022-23"}


# ------------------------------------------------------- construction

def expected_possessions(tempo_home, tempo_away):
    """Blend of the two teams' adj_tempo (parent section 1).

    Operationalized as the arithmetic mean (see module docstring).
    """
    return (tempo_home + tempo_away) / 2.0


def expected_team_points(adj_o, adj_d_opp, league_mean_eff, possessions):
    """(adj_o + adj_d_opp - league mean efficiency) / 100 * poss.

    Parent design section 1, verbatim.
    """
    return (adj_o + adj_d_opp - league_mean_eff) / 100.0 * possessions


def candidate_team_points(fx):
    """CBB_TORVIK_EFFICIENCY_V1 expected team points (home, away).

    fx carries the prior-snapshot terms for the game date (the
    D-1 archive file, Amendment 1):
    adj_o_home, adj_d_home, tempo_home, adj_o_away, adj_d_away,
    tempo_away, league_mean_eff (all from the date's archive file).
    """
    poss = expected_possessions(fx["tempo_home"], fx["tempo_away"])
    pts_home = expected_team_points(fx["adj_o_home"], fx["adj_d_away"],
                                    fx["league_mean_eff"], poss)
    pts_away = expected_team_points(fx["adj_o_away"], fx["adj_d_home"],
                                    fx["league_mean_eff"], poss)
    return pts_home, pts_away


def simple_baseline_team_points(fx):
    """The section 1 simple ratings baseline's team points.

    Same expected-points formula with league-mean tempo in place of
    the two-team blend — "no tempo interaction" (parent section 1).
    fx additionally carries league_mean_tempo for the game date.
    """
    poss = fx["league_mean_tempo"]
    pts_home = expected_team_points(fx["adj_o_home"], fx["adj_d_away"],
                                    fx["league_mean_eff"], poss)
    pts_away = expected_team_points(fx["adj_o_away"], fx["adj_d_home"],
                                    fx["league_mean_eff"], poss)
    return pts_home, pts_away


# ------------------------------------------------------------ baselines

def naive_team_mean(prior_fixtures):
    """Naive team-mean baseline fitted on prior seasons' fixtures.

    prior_fixtures: three-way-verified fixtures from seasons
    strictly before the scored season, each with home_slug,
    away_slug, home_score, away_score. Returns (team_mean, league
    fallback): team_mean maps slug -> that team's mean points
    scored over the window; the fallback is the league mean team
    points over the same window, used for a team with no
    prior-season verified history.
    """
    scored = {}
    total_points = 0
    total_team_games = 0
    for fx in prior_fixtures:
        for slug, pts in ((fx["home_slug"], fx["home_score"]),
                          (fx["away_slug"], fx["away_score"])):
            scored.setdefault(slug, []).append(pts)
            total_points += pts
            total_team_games += 1
    if total_team_games == 0:
        return {}, None
    league_mean = total_points / total_team_games
    team_mean = {slug: sum(v) / len(v) for slug, v in scored.items()}
    return team_mean, league_mean


def naive_prediction(team_mean, league_fallback, slug):
    """One team's naive team-mean prediction (fallback if unseen)."""
    if slug in team_mean:
        return team_mean[slug]
    return league_fallback


# -------------------------------------------------------------- metrics

def team_game_errors(fx, team_mean, league_fallback):
    """Per-team-game absolute errors for one fixture.

    Returns a list of two dicts (home, away) with the actual points
    and each model's absolute error. Raises KeyError if the naive
    baseline has neither a team mean nor a league fallback (an
    empty fitting window) — the caller must not score then.
    """
    cand_home, cand_away = candidate_team_points(fx)
    base_home, base_away = simple_baseline_team_points(fx)
    out = []
    for side, cand, base in (("home", cand_home, base_home),
                             ("away", cand_away, base_away)):
        slug = fx[f"{side}_slug"]
        actual = fx[f"{side}_score"]
        naive = naive_prediction(team_mean, league_fallback, slug)
        if naive is None:
            raise KeyError("naive baseline has no fitting window")
        out.append({
            "side": side, "slug": slug, "actual": actual,
            "candidate_err": abs(cand - actual),
            "simple_err": abs(base - actual),
            "naive_err": abs(naive - actual),
        })
    return out


def mae(values):
    values = list(values)
    return sum(values) / len(values)


def season_block_bootstrap(diffs_by_season):
    """Percentile 95% CI for the pooled mean paired difference.

    Resamples scored seasons (blocks) with replacement; computed
    from per-season (sum, n) aggregates — algebraically identical
    to resampling the pooled paired diffs block-wise. Mirrors the
    parent screen's bootstrap exactly (reps, seed, percentiles).
    """
    seasons = sorted(diffs_by_season)
    agg = {s: (sum(diffs_by_season[s]), len(diffs_by_season[s]))
           for s in seasons}
    rng = random.Random(BOOTSTRAP_SEED)
    means = []
    for _ in range(BOOTSTRAP_REPS):
        total, n = 0.0, 0
        for _ in seasons:
            block_sum, block_n = agg[rng.choice(seasons)]
            total += block_sum
            n += block_n
        means.append(total / n)
    means.sort()
    lo = means[int(0.025 * BOOTSTRAP_REPS)]
    hi = means[min(BOOTSTRAP_REPS - 1, int(0.975 * BOOTSTRAP_REPS))]
    pooled = [d for s in seasons for d in diffs_by_season[s]]
    return {"mean_paired_diff": sum(pooled) / len(pooled),
            "ci95_lower": lo, "ci95_upper": hi,
            "reps": BOOTSTRAP_REPS, "seed": BOOTSTRAP_SEED,
            "blocks": len(seasons)}


def leg_criterion(bootstrap_result):
    """The leg's bar (parent section 3 form): CI upper bound < 0."""
    return bootstrap_result["ci95_upper"] < 0
