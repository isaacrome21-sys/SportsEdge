#!/usr/bin/env python3
"""One-shot exploratory V3 pair-mean screen against the pinned date-only SBR archive.

The raw archive has no trustworthy tipoff/result-available/quote-observed
instants or exact bookmaker identity. We use strictly EARLIER calendar dates
and preserve all paired rows, but this is never certified PIT or a market beat.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.research_nba_v2_sbr_dateonly_screen import (  # noqa: E402
    BEGIN_HOLDOUT, END_HOLDOUT, SOURCE_BLOB_SHA1, SOURCE_COMMIT,
    SOURCE_PATH, evaluate_calendar_archive, normalize, verify_archive_blob,
)

SCREEN = "NBA_TOTALS_PAIR_MEAN_V3_DATE_ONLY_EXPLORATORY"
PAIR_MEAN_WEIGHT = 0.5
WINDOW = 450
MIN_LEAGUE = 30
MIN_TEAM = 5
SHRINK = 20.0
BOOTSTRAP_DRAWS = 750
BOOTSTRAP_SEED = 17
PARENT_PAIRED_GAMES = 8215
PARENT_NORMALIZED_ROWS = 13893


def _rmse(rows, key):
    if not rows:
        return None
    return math.sqrt(sum((r[key] - r["actual"]) ** 2 for r in rows) / len(rows))


def _mean_diff(rows, left, right):
    if not rows:
        return None
    return sum((r[left] - r["actual"]) ** 2 -
               (r[right] - r["actual"]) ** 2 for r in rows) / len(rows)


def _day_cluster_interval(rows, left, right):
    """Exact preregistered day-cluster bootstrap; not a formal PIT inference."""
    if not rows:
        return None
    by_day = defaultdict(list)
    for row in rows:
        by_day[row["day"]].append(row)
    strata = []
    for day in sorted(by_day):
        games = by_day[day]
        strata.append((
            sum((r[left] - r["actual"]) ** 2 -
                (r[right] - r["actual"]) ** 2 for r in games),
            len(games),
        ))
    rng = random.Random(BOOTSTRAP_SEED)
    values = []
    for _ in range(BOOTSTRAP_DRAWS):
        draws = [strata[rng.randrange(len(strata))]
                 for _ in range(len(strata))]
        values.append(sum(x[0] for x in draws) / sum(x[1] for x in draws))
    values.sort()
    return [values[int((BOOTSTRAP_DRAWS - 1) * p)] for p in (0.025, 0.975)]


def score_archive(raw, *, begin=BEGIN_HOLDOUT, end=END_HOLDOUT,
                  require_parent_reference_parity=True):
    """Return all-seasons report; no market-dependent forecast or subcohort search."""
    games = normalize(raw)
    scored = []
    paired = []
    for index, game in enumerate(games):
        if not begin <= game["season"] <= end:
            continue
        prior = []
        for j in range(index - 1, -1, -1):
            if games[j]["day"] < game["day"]:
                prior.append(games[j])
                if len(prior) == WINDOW:
                    break
        if len(prior) < MIN_LEAGUE:
            continue
        league = sum((g["hp"] + g["ap"]) / 2.0 for g in prior) / len(prior)
        home, away = game["home"], game["away"]
        team = {home: {"sc": [], "co": []}, away: {"sc": [], "co": []}}
        for old in prior:
            if old["home"] in team:
                team[old["home"]]["sc"].append(old["hp"])
                team[old["home"]]["co"].append(old["ap"])
            if old["away"] in team:
                team[old["away"]]["sc"].append(old["ap"])
                team[old["away"]]["co"].append(old["hp"])
        if min(len(team[home]["sc"]), len(team[away]["sc"])) < MIN_TEAM:
            continue

        def shrunk(values):
            n = len(values)
            return (sum(values) / n - league) * n / (n + SHRINK)

        effects = (
            shrunk(team[home]["sc"]) + shrunk(team[home]["co"])
            + shrunk(team[away]["sc"]) + shrunk(team[away]["co"])
        )
        parent_v2 = 2 * league + effects
        candidate_v3 = 2 * league + PAIR_MEAN_WEIGHT * effects
        base = 2 * league
        result = {
            "season": game["season"], "day": game["day"],
            "actual": game["hp"] + game["ap"], "v3": candidate_v3,
            "v2": parent_v2, "climatology": base,
        }
        scored.append(result)
        market = game["market"]
        if market is not None and 170 <= market <= 270:
            paired.append({**result, "reference": market})

    # Recompute the independent parent script on EXACTLY this raw cohort;
    # refuse silently differing game filters or V2 arithmetic.
    parent = evaluate_calendar_archive(raw, begin=begin, end=end)
    if (len(scored) != parent["model_scored_games"]
            or len(paired) != parent["paired_games"]
            or len(games) != parent["normalized_rows"]):
        raise ValueError("NBA_V3_PARENT_COHORT_MISMATCH")
    if paired:
        if (not math.isclose(_rmse(paired, "v2"),
                             parent["candidate_rmse_paired"],
                             rel_tol=0, abs_tol=1e-9)
                or not math.isclose(_rmse(paired, "climatology"),
                                    parent["climatology_rmse_paired"],
                                    rel_tol=0, abs_tol=1e-9)
                or not math.isclose(_rmse(paired, "reference"),
                                    parent["indicative_market_rmse_paired"],
                                    rel_tol=0, abs_tol=1e-9)):
            raise ValueError("NBA_V3_PARENT_NUMERIC_PARITY_FAILED")
    if require_parent_reference_parity and (
            (begin, end) != (BEGIN_HOLDOUT, END_HOLDOUT)
            or len(games) != PARENT_NORMALIZED_ROWS
            or len(paired) != PARENT_PAIRED_GAMES):
        raise ValueError("NBA_V3_PINNED_FULL_COHORT_NOT_REPRODUCED")

    by_season = []
    for season in range(begin, end + 1):
        group = [r for r in paired if r["season"] == season]
        by_season.append({
            "season": season, "paired_games": len(group),
            "v3_rmse": _rmse(group, "v3"), "v2_rmse": _rmse(group, "v2"),
            "indicative_reference_rmse": _rmse(group, "reference"),
            "under": sum(r["v3"] < r["reference"] for r in group),
            "over": sum(r["v3"] > r["reference"] for r in group),
            "tie": sum(r["v3"] == r["reference"] for r in group),
            "signed_model_minus_reference_mean": (
                sum(r["v3"] - r["reference"] for r in group) / len(group)
                if group else None),
        })
    v3rmse, v2rmse, refrmse = (
        _rmse(paired, "v3"), _rmse(paired, "v2"),
        _rmse(paired, "reference"),
    )
    delta_v2 = _mean_diff(paired, "v3", "v2")
    delta_market = _mean_diff(paired, "v3", "reference")
    ci_v2 = _day_cluster_interval(paired, "v3", "v2")
    ci_market = _day_cluster_interval(paired, "v3", "reference")
    if not paired:
        disposition = "INSUFFICIENT_PAIRED_REFERENCE"
    elif (v3rmse < v2rmse and v3rmse < refrmse
          and ci_v2[1] < 0 and ci_market[1] < 0):
        disposition = "EXPLORATORY_BETTER_THAN_V2_AND_INDICATIVE_REFERENCE"
    elif v3rmse < v2rmse:
        disposition = "EXPLORATORY_BETTER_THAN_V2_ONLY"
    else:
        disposition = "EXPLORATORY_NOT_BETTER_THAN_V2"
    return {
        "screen": SCREEN, "source_path": SOURCE_PATH,
        "source_commit": SOURCE_COMMIT, "source_blob_sha1": SOURCE_BLOB_SHA1,
        "source_rows": len(raw), "normalized_rows": len(games),
        "scored_games": len(scored), "paired_games": len(paired),
        "paired_dates": len({r["day"] for r in paired}),
        "holdout_seasons": [begin, end],
        "chronology": "STRICT_EARLIER_CALENDAR_DATES_ONLY",
        "real_game_tipoff": "UNKNOWN", "result_available_at": "UNKNOWN",
        "quote_observed_at": "UNKNOWN", "reference_bookmaker": "UNKNOWN",
        "reference_admission": "INDICATIVE_DATE_ONLY_NOT_ADMITTED",
        "model_formula": "2*rolling_league_mean+0.5*(four_shrunk_team_effects)",
        "parameters": {"prior_games": WINDOW, "minimum_league_games": MIN_LEAGUE,
                       "minimum_team_games": MIN_TEAM, "shrink_games": SHRINK,
                       "pair_mean_weight": PAIR_MEAN_WEIGHT},
        "v3_rmse_all": _rmse(scored, "v3"),
        "v3_rmse_paired": v3rmse, "v2_rmse_paired": v2rmse,
        "climatology_rmse_paired": _rmse(paired, "climatology"),
        "indicative_reference_rmse_paired": refrmse,
        "v3_minus_v2_mean_squared_error": delta_v2,
        "v3_minus_reference_mean_squared_error": delta_market,
        "v3_minus_v2_day_bootstrap_95pct": ci_v2,
        "v3_minus_reference_day_bootstrap_95pct": ci_market,
        "bootstrap": {"clusters": "calendar_day", "draws": BOOTSTRAP_DRAWS,
                      "seed": BOOTSTRAP_SEED},
        "under_rows": sum(r["v3"] < r["reference"] for r in paired),
        "over_rows": sum(r["v3"] > r["reference"] for r in paired),
        "tie_rows": sum(r["v3"] == r["reference"] for r in paired),
        "all_seasons": by_season,
        "disposition": disposition,
        "eligible_for_card": False, "validated_market_beat": False,
        "model_p_authority": False, "play_authority": False,
        "staking_authority": False, "promotion_authority": False,
        "reused_cohort": True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw_bytes = args.source.read_bytes()
    verify_archive_blob(raw_bytes)
    raw = json.loads(raw_bytes)
    report = score_archive(raw)
    report["source_git_blob_verified"] = True
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    print(f"NBA V3 research screen: {report['paired_games']} pairs, "
          f"disposition={report['disposition']}, no card authority.")


if __name__ == "__main__":
    main()
