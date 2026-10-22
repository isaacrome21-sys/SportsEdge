"""Reproduce NHL-free NBA Elo V2 SIDES screen on an unadmitted SBR archive.

Date-only research. Archive has no tipoff, quote-capture or result-availability
instants. Historical market 'closes' are INDICATIVE, not independently proven
pregame or authenticated to DraftKings. No forward evidence, PLAY, or promotion.
File must match the exact public upstream Git blob SHA-1.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SOURCE_COMMIT = "1a820e50c6fbd0276cde073c22bfffae78930868"
SOURCE_BLOB_SHA1 = "f5ba0d4f8f729236fdd8883a65189f2d6443338c"
SOURCE_PATH = "data/nba_archive_10Y.json"
SCREEN = "NBA_ELO_SIDES_V2_SBR_DATE_ONLY_SCREEN_V1"
ALIASES = {"Golden State": "Warriors", "NewJersey": "Nets",
           "Bobcats": "Hornets", "NewOrleans": "Pelicans"}

# Declared, UNVALIDATED params as fixed in sportsedge.ratings.params (not tuned).
INITIAL = 1500.0
K = 20.0
SCALE = 400.0
ELO_PER_POINT = 20.0
HOME_COURT_POINTS = 2.0
SEASON_REGRESS = 0.33
NBA_MARGIN_SD = 12.5
NFL_MARGIN_SD = 13.7
MIN_TEAM_GAMES = 5
HOLDOUT_FIRST = 2015
HOLDOUT_LAST = 2021


def verify_source_blob(raw_bytes: bytes) -> str:
    digest = hashlib.sha1(
        ("blob " + str(len(raw_bytes)) + "\0").encode("ascii") + raw_bytes
    ).hexdigest()
    if digest != SOURCE_BLOB_SHA1:
        raise ValueError("NBA_SIDE_DATE_ONLY_SOURCE_BLOB_MISMATCH")
    return digest


def _number(value):
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (ValueError, TypeError):
        return None
    return out if math.isfinite(out) else None


def normalize(raw):
    """Date-level, not instant-level fixtures. Never fabricate missing clocks."""
    rows, seen = [], set()
    for x in raw:
        home = ALIASES.get(str(x.get("home_team") or ""),
                           str(x.get("home_team") or ""))
        away = ALIASES.get(str(x.get("away_team") or ""),
                           str(x.get("away_team") or ""))
        hp, ap = _number(x.get("home_final")), _number(x.get("away_final"))
        if not home or not away or home == away or hp is None or ap is None or hp + ap < 120:
            continue
        try:
            season = int(x["season"])
            day = int(float(x["date"]))
            datetime.strptime(str(day), "%Y%m%d")
        except (TypeError, ValueError, KeyError) as e:
            raise ValueError("NBA_SIDE_DATE_ONLY_CALENDAR_DATE_INVALID") from e
        key = (day, home, away)
        if key in seen:
            raise ValueError("NBA_SIDE_DATE_ONLY_DUPLICATE_GAME")
        seen.add(key)
        sp, hml, aml = (_number(x.get("home_close_spread")),
                        _number(x.get("home_close_ml")), _number(x.get("away_close_ml")))
        rows.append({
            "day": day, "season": season, "home": home, "away": away,
            "hp": hp, "ap": ap,
            "spread": sp if sp is not None and abs(sp) <= 25 else None,
            "home_ml": hml if hml is not None and abs(hml) >= 100 else None,
            "away_ml": aml if aml is not None and abs(aml) >= 100 else None,
        })
    return sorted(rows, key=lambda z: (z["day"], z["home"], z["away"]))


def _expected(a, b):
    return 1.0 / (1.0 + 10.0 ** (-(a - b) / SCALE))


def _american_implied(odds):
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def _rmse(rows, error):
    return math.sqrt(sum(x[error]**2 for x in rows) / len(rows)) if rows else None


def _mean(rows, name):
    return sum(x[name] for x in rows) / len(rows) if rows else None


def evaluate_date_only(raw, *, first=HOLDOUT_FIRST, last=HOLDOUT_LAST,
                       min_team_games=MIN_TEAM_GAMES, include_rows=False):
    """Score FULL calendar days before learning any final from that same day.

    Elo updates are applied after whole-day predictions. When a team has
    multiple same-date games their updates are treated as simultaneous using
    the preceding day's rating; intra-day ordering cannot be verified.
    This matches neutral-site Elo update math with a declared +2 home
    point layer and a rating_at-style PRE-season-regression read.
    """
    rows = normalize(raw)
    # Per-team rating and last observed season; counts are previous-date games.
    ratings, counts = {}, defaultdict(int)
    results = []
    i = 0
    while i < len(rows):
        j = i + 1
        while j < len(rows) and rows[j]["day"] == rows[i]["day"]:
            j += 1
        updates = []
        for g in rows[i:j]:
            home, away = g["home"], g["away"]
            prior_h = ratings.get(home, (INITIAL, None))[0]
            prior_a = ratings.get(away, (INITIAL, None))[0]
            if first <= g["season"] <= last and min(counts[home], counts[away]) >= min_team_games:
                margin = (prior_h - prior_a) / ELO_PER_POINT + HOME_COURT_POINTS
                prob_home = _expected(prior_h + HOME_COURT_POINTS * ELO_PER_POINT, prior_a)
                actual = g["hp"] - g["ap"]
                win = float(actual > 0)
                obs = {"day": g["day"], "season": g["season"],
                       "margin_error": margin - actual,
                       "ml_brier": (prob_home - win)**2,
                       "spread_error": None, "market_ml_brier": None}
                if g["spread"] is not None:
                    obs["spread_error"] = -g["spread"] - actual
                if g["home_ml"] is not None and g["away_ml"] is not None:
                    ih, ia = (_american_implied(g["home_ml"]),
                              _american_implied(g["away_ml"]))
                    obs["market_ml_brier"] = (ih / (ih + ia) - win)**2
                results.append(obs)
            # Updates affect NEXT date only; no invented within-day ordering.
            rating_h, season_h = ratings.get(home, (INITIAL, None))
            rating_a, season_a = ratings.get(away, (INITIAL, None))
            new_h = rating_h + SEASON_REGRESS * (INITIAL - rating_h) if season_h is not None and season_h != g["season"] else rating_h
            new_a = rating_a + SEASON_REGRESS * (INITIAL - rating_a) if season_a is not None and season_a != g["season"] else rating_a
            pre_diff = new_h - new_a
            win = 1.0 if g["hp"] > g["ap"] else 0.0 if g["hp"] < g["ap"] else 0.5
            normalized = NFL_MARGIN_SD / NBA_MARGIN_SD
            winner_diff = pre_diff if g["hp"] > g["ap"] else -pre_diff
            mov_mult = ((abs(g["hp"] - g["ap"]) * normalized + 3.0)**0.8
                        / (7.45 + 0.006 * abs(winner_diff) * normalized))
            step = K * mov_mult
            neutral_expected = _expected(new_h, new_a)
            updates.append((home, new_h + step * (win - neutral_expected),
                            away, new_a + step * ((1.0 - win) - (1.0 - neutral_expected)),
                            g["season"]))
        for home, nh, away, na, season in updates:
            ratings[home] = (nh, season)
            ratings[away] = (na, season)
            counts[home] += 1
            counts[away] += 1
        i = j
    spread = [z for z in results if z["spread_error"] is not None]
    money = [z for z in results if z["market_ml_brier"] is not None]
    rep = {
        "screen": SCREEN, "source_commit": SOURCE_COMMIT,
        "source_blob_sha1": SOURCE_BLOB_SHA1, "source_path": SOURCE_PATH,
        "source_rows": len(raw), "normalized_rows": len(rows),
        "holdout_seasons": [first, last],
        "model_games": len(results), "spread_reference_games": len(spread),
        "moneyline_reference_games": len(money),
        "spread_reference_distinct_days": len({z["day"] for z in spread}),
        "moneyline_reference_distinct_days": len({z["day"] for z in money}),
        "model_margin_rmse_all": _rmse(results, "margin_error"),
        "model_margin_rmse_paired": _rmse(spread, "margin_error"),
        "indicative_market_spread_rmse": _rmse(spread, "spread_error"),
        "model_moneyline_brier_all": _mean(results, "ml_brier"),
        "model_moneyline_brier_paired": _mean(money, "ml_brier"),
        "indicative_market_moneyline_brier": _mean(money, "market_ml_brier"),
        "model_minus_market_spread_mse": (
            _mean([{"diff": z["margin_error"]**2 - z["spread_error"]**2}
                   for z in spread], "diff") if spread else None),
        "model_minus_market_moneyline_brier": (
            _mean([{"diff": z["ml_brier"] - z["market_ml_brier"]}
                   for z in money], "diff") if money else None),
        "clock_resolution": "DATE_ONLY_NO_EVENT_START_OR_RESULT_AVAILABLE_TIMESTAMP",
        "price_capture_timestamp": "UNKNOWN",
        "market_reference_authority": "INDICATIVE_NOT_ADMITTED",
        "validation_status": "HISTORICAL_RESEARCH_ONLY_UNVALIDATED",
        "spread_indicative_reference_screen":_indicative_side_verdict(
            _rmse(spread, "margin_error"),_rmse(spread, "spread_error")),
        "moneyline_indicative_reference_screen":_indicative_side_verdict(
            _mean(money, "ml_brier"),_mean(money, "market_ml_brier")),
        "candidate_card_source_eligible":False,
        "screen_verdict_authority":"RESEARCH_DIAGNOSTIC_ONLY",
        "model_parameters": "DECLARED_FROZEN_FOR_THIS_DIAGNOSTIC_UNTUNED",
        "play_authority": False,
    }
    if include_rows:
        rep["rows"] = results
    return rep



def _indicative_side_verdict(model_metric, reference_metric):
    """No hypothetical good result can confer quote provenance or PLAY."""
    if model_metric is None or reference_metric is None:
        return "REFERENCE_UNMEASURED"
    if model_metric >= reference_metric:
        return "FAILED_INDICATIVE_REFERENCE_NOT_A_CARD_SOURCE"
    return "BETTER_INDICATIVE_ONLY_SOURCE_NOT_ADMITTED"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    raw_bytes = args.source.read_bytes()
    verify_source_blob(raw_bytes)
    report = evaluate_date_only(json.loads(raw_bytes))
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
