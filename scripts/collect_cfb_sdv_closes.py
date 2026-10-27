#!/usr/bin/env python3
"""Collect SportsDataVerse CFB closing lines and build the evaluation dataset.

Downloads the `espn_cfb_betting` and `cfb_schedules` release assets
(CSV form) from sportsdataverse/sportsdataverse-data and joins them on
ESPN game_id. Measured format divergence (Oct 26, 2026, full-file compare
against the parquet form of the same releases): the two published formats
agree on every game except six (2017 x2, 2018 x1, 2023 x3) where one form
carries a real line and the other carries the placeholder/default row.
Exclusions are applied to whichever form is read, exactly as published;
the divergence is recorded in the evaluation report, not resolved by
picking a winner per game.

Source limits, stated on the data itself: spread + total only, no moneylines,
no per-book rows, NO timestamps. "Closing" means the spread/total as
published in this file; all downstream comparisons are vs-close, never
verified CLV, and the file carries no prices (any ROI is under a stated
flat -110 assumption made by the evaluator, not by this collector).

Exclusion rules (per game; reason recorded, never repaired or guessed):
  E0_UNVERIFIED_ODDS_SOURCE      unknown/missing source; admit only SDV
      core_odds_api or summary_pickcenter origins
  E1_PLACEHOLDER_DEFAULT_SOURCE  odds_source == "default" (placeholder
      2.5 / 55.5-era values; every row in 2004-2011)
  E2_NO_SPREAD_VALUE             home_team_spread is NaN (every
      summary_pickcenter row in 2012-2023 carries NaN values in this file)
  E3_NO_TOTAL_VALUE              over_under is NaN
  E4_SPREAD_FLAGGED_UNAVAILABLE  game_spread_available not explicitly true
  E5_NOT_COMPLETED               schedule incomplete / nonfinite final points
  E6_INVALID_SPREAD_VALUE         close nonfinite, bool, or malformed text
  E7_INVALID_TOTAL_VALUE          total nonfinite, bool, or malformed text

Usage:
  python scripts/collect_cfb_sdv_closes.py [--seasons 2004-2026] \
      [--out-dir output/cfb_sdv_closes]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import numbers
import sys

import numpy as np
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

BETTING_URL = ("https://github.com/sportsdataverse/sportsdataverse-data/"
               "releases/download/espn_cfb_betting/betting_{season}.csv.gz")
SCHEDULE_URL = ("https://github.com/sportsdataverse/sportsdataverse-data/"
                "releases/download/cfb_schedules/cfb_schedules_{season}.csv.gz")

SCHED_COLS = ["game_id", "season", "week", "season_type", "start_date",
              "completed", "neutral_site", "home_id", "home_team",
              "home_division", "away_id", "away_team", "away_division",
              "home_points", "away_points", "fbs_game"]

KEEP = ["game_id", "season", "week", "season_type", "start_date", "completed",
        "neutral_site", "home_id", "home_team", "home_division", "away_id",
        "away_team", "away_division", "home_points", "away_points", "fbs_game",
        "odds_source", "game_spread", "home_team_spread", "over_under",
        "game_spread_available", "joined_schedule", "excl_spread", "excl_total",
        "spread_scoreable", "total_scoreable"]


def as_bool(series: pd.Series) -> pd.Series:
    """Coerce a bool/object/string column to strict boolean (NaN -> False).

    Some seasons store `completed` as object dtype (True/False/NaN); the `~`
    operator on object booleans yields ints, not a mask, so never rely on it.
    """
    if series.dtype == bool:
        return series
    return series.astype(str).str.lower().isin(["true", "1", "t", "yes"])


def finite_numeric(series: pd.Series) -> pd.Series:
    """Require real finite numeric fields; refuse booleans, text, NaN, Infinity."""
    return series.map(lambda value: (
        isinstance(value, (numbers.Real, np.integer, np.floating))
        and not isinstance(value, (bool, np.bool_))
        and math.isfinite(float(value))
    ))


def fetch_csv(url: str) -> tuple[pd.DataFrame, str, str]:
    """Download one release CSV asset; fall back from .csv.gz to .csv.

    The in-progress season's release may publish the plain .csv before the
    .csv.gz (seen for betting_2026). Returns (frame, sha256, asset_name).
    """
    candidates = [url]
    if url.endswith(".csv.gz"):
        candidates.append(url[:-3])
    last_exc = None
    for candidate in candidates:
        try:
            with urllib.request.urlopen(candidate) as resp:  # noqa: S310 - pinned SDV release URL
                raw = resp.read()
        except Exception as exc:  # try the next form, then fail loudly
            last_exc = exc
            continue
        sha = hashlib.sha256(raw).hexdigest()
        if candidate.endswith(".gz"):
            raw = gzip.decompress(raw)
        df = pd.read_csv(io.BytesIO(raw), low_memory=False)
        return df, sha, candidate.rsplit("/", 1)[-1]
    raise RuntimeError(f"FETCH_FAILED {url}: {last_exc}")


def apply_exclusions(merged: pd.DataFrame) -> pd.DataFrame:
    """Tag excl_spread / excl_total and the *_scoreable flags in place."""
    m = merged
    m["completed"] = as_bool(m["completed"])
    m["excl_spread"] = ""
    m["excl_total"] = ""
    default = m.odds_source == "default"
    authentic = m.odds_source.isin(("core_odds_api", "summary_pickcenter"))
    m.loc[~authentic & ~default, ["excl_spread", "excl_total"]] = \
        "E0_UNVERIFIED_ODDS_SOURCE"
    m.loc[default, ["excl_spread", "excl_total"]] = "E1_PLACEHOLDER_DEFAULT_SOURCE"
    m.loc[(m.excl_spread == "") & m.home_team_spread.isna(), "excl_spread"] = "E2_NO_SPREAD_VALUE"
    m.loc[(m.excl_total == "") & m.over_under.isna(), "excl_total"] = "E3_NO_TOTAL_VALUE"
    m.loc[(m.excl_spread == "") & ~finite_numeric(m.home_team_spread), "excl_spread"] = \
        "E6_INVALID_SPREAD_VALUE"
    m.loc[(m.excl_total == "") & ~finite_numeric(m.over_under), "excl_total"] = \
        "E7_INVALID_TOTAL_VALUE"
    # CSV/object flags such as "False", "0" or NaN must not slip through
    # Python False comparison; require an explicitly affirmative source flag.
    m.loc[(m.excl_spread == "") & ~as_bool(m.game_spread_available), "excl_spread"] = \
        "E4_SPREAD_FLAGGED_UNAVAILABLE"  # noqa: E501 - reason string kept whole
    notdone = (~m.completed) | ~finite_numeric(m.home_points) | ~finite_numeric(m.away_points)
    for col in ("excl_spread", "excl_total"):
        cur = m.loc[notdone, col]
        m.loc[notdone, col] = cur.where(cur != "", "E5_NOT_COMPLETED")
    m["spread_scoreable"] = m.excl_spread == ""
    m["total_scoreable"] = m.excl_total == ""
    return m


def build_season(betting: pd.DataFrame, schedule: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    m = betting.merge(schedule[SCHED_COLS], on=["game_id", "season", "week"],
                      how="left", indicator=True)
    m["joined_schedule"] = m["_merge"] == "both"
    m = m.drop(columns=["_merge"])
    m = apply_exclusions(m)
    both_fbs = int((((m.home_division == "fbs") & (m.away_division == "fbs"))
                    & m.spread_scoreable).sum())
    fbs_fcs = int(((((m.home_division == "fbs") & (m.away_division == "fcs"))
                    | ((m.home_division == "fcs") & (m.away_division == "fbs")))
                   & m.spread_scoreable).sum())
    summary = dict(
        betting_rows=int(len(betting)),
        dup_game_ids=int(len(betting) - betting.game_id.nunique()),
        joined_schedule=int(m.joined_schedule.sum()),
        completed=int(m.completed.sum()),
        odds_source={str(k): int(v) for k, v in betting.odds_source.value_counts().items()},
        spread_scoreable=int(m.spread_scoreable.sum()),
        total_scoreable=int(m.total_scoreable.sum()),
        spread_exclusions={str(k): int(v) for k, v in
                             m.loc[m.excl_spread != "", "excl_spread"].value_counts().items()},
        total_exclusions={str(k): int(v) for k, v in
                            m.loc[m.excl_total != "", "excl_total"].value_counts().items()},
        both_fbs_scoreable=both_fbs,
        fbs_vs_fcs_scoreable=fbs_fcs,
    )
    return m[KEEP], summary


def parse_seasons(text: str) -> list[int]:
    if "-" in text:
        lo, hi = text.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(x) for x in text.split(",") if x.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2004-2026")
    ap.add_argument("--out-dir", default="output/cfb_sdv_closes")
    args = ap.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames, results_frames, validation, provenance = [], [], {}, {"retrieved_at_utc":
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "files": {}}
    for season in parse_seasons(args.seasons):
        betting, b_sha, b_name = fetch_csv(BETTING_URL.format(season=season))
        schedule, s_sha, s_name = fetch_csv(SCHEDULE_URL.format(season=season))
        provenance["files"][b_name] = b_sha
        provenance["files"][s_name] = s_sha
        frame, summary = build_season(betting, schedule)
        frames.append(frame)
        done = schedule[as_bool(schedule["completed"])
                        & finite_numeric(schedule.home_points)
                        & finite_numeric(schedule.away_points)]
        # A replacement model must know the historical venue and division at
        # its prediction cutoff.  Do not silently turn unknown neutral-site
        # values into home games or admit FBS/FCS mismatches to its fit.
        results_frames.append(done[["game_id", "season", "week", "start_date",
                                    "neutral_site", "home_id", "away_id",
                                    "home_division", "away_division",
                                    "home_points", "away_points"]])
        validation[str(season)] = summary
        print(f"season={season} rows={summary['betting_rows']} "
              f"spread_scoreable={summary['spread_scoreable']} "
              f"total_scoreable={summary['total_scoreable']}")
    ds = pd.concat(frames, ignore_index=True).sort_values(
        ["season", "start_date", "game_id"])
    ds.to_csv(out_dir / "sdv_cfb_closes_all.csv", index=False)
    results = pd.concat(results_frames, ignore_index=True)
    results.to_csv(out_dir / "sdv_cfb_results_all.csv", index=False)
    print(f"WROTE {out_dir}/sdv_cfb_results_all.csv rows={len(results)}")
    (out_dir / "validation_by_season.json").write_text(json.dumps(validation, indent=1))
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=1))
    print(f"WROTE {out_dir}/sdv_cfb_closes_all.csv rows={len(ds)} "
          f"spread_scoreable={int(ds.spread_scoreable.sum())} "
          f"total_scoreable={int(ds.total_scoreable.sum())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
