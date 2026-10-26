"""Fail-closed pre-freeze viability test of one CFB successor instantiation.

Compares raw, market-blind converged score ratings against *published closes*
in full-slate 2023-2025.  No source quote timestamps/prices or authentic score
publication times exist: NOT verified PIT, NOT CLV, NOT a live engine.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.converged_successor import (
    BASE_POINTS,
    EMBARGO,
    FIRST_ELIGIBLE_WEEK,
    HFA_POINTS,
    LAST_GAMES,
    MAX_MARKET_DISAGREEMENT,
    MAX_RAW_MARGIN,
    MIN_PRIOR_GAMES,
    RIDGE_GAMES,
    Game,
    project_season,
)

DESIGN_SEASONS = (2023, 2024, 2025)
MIN_SCOREABLE_PER_SEASON = 100
MIN_BETA = 0.10
MIN_POSITIVE_SEASONS = 2
MAX_MAE_DEFICIT_POINTS = 0.5
MODEL_VERSION = "CFB_CONVERGED_SCORES_RESEARCH_V0"


def _bool(value) -> bool:
    if type(value) is bool or type(value).__name__ == "bool_":
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    raise ValueError("CFB_SUCCESSOR_REQUIRED_BOOLEAN_UNKNOWN")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_games(frame: pd.DataFrame) -> list[Game]:
    if frame.game_id.duplicated().any():
        raise ValueError("CFB_SUCCESSOR_DUPLICATE_RESULT_GAME_ID")
    games = []
    for r in frame.itertuples(index=False):
        try:
            if (str(r.home_division).lower() != "fbs"
                    or str(r.away_division).lower() != "fbs"):
                # Mismatches and uncertain divisions are not model inputs.
                continue
            kickoff = pd.to_datetime(r.start_date, utc=True, errors="raise")
            if pd.isna(kickoff):
                raise ValueError("INVALID_KICKOFF")
            games.append(Game(
                game_id=int(r.game_id), season=int(r.season), week=int(r.week),
                instant=kickoff.to_pydatetime(), home_id=int(r.home_id),
                away_id=int(r.away_id), home_points=float(r.home_points),
                away_points=float(r.away_points), neutral_site=_bool(r.neutral_site),
                home_division="fbs", away_division="fbs",
            ))
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f"CFB_SUCCESSOR_INVALID_FBS_RESULT:{r.game_id}:{exc}") from exc
    return sorted(games, key=lambda g: (g.instant, g.game_id))


def _slope(xs: list[float], ys: list[float]) -> float | None:
    """OLS slope with intercept; x=model-close, y=actual-close."""
    if len(xs) < 2:
        return None
    xm, ym = sum(xs) / len(xs), sum(ys) / len(ys)
    var = sum((x - xm) ** 2 for x in xs)
    return sum((x - xm) * (y - ym) for x, y in zip(xs, ys)) / var if var > 1e-12 else None


def _metrics(rows: list[dict]) -> dict:
    if not rows:
        return {"n": 0, "beta": None, "model_mae": None, "close_mae": None}
    xs = [r["raw_prediction"] - r["market_close"] for r in rows]
    ys = [r["actual"] - r["market_close"] for r in rows]
    return {
        "n": len(rows),
        "beta": _slope(xs, ys),
        "model_mae": sum(abs(r["raw_prediction"] - r["actual"]) for r in rows) / len(rows),
        "close_mae": sum(abs(r["market_close"] - r["actual"]) for r in rows) / len(rows),
        "mean_abs_disagreement": sum(abs(x) for x in xs) / len(xs),
    }


def screen(rows: list[dict]) -> dict:
    """Fixed gate, no hyperparameter/threshold sweep or fitted calibration."""
    pooled = _metrics(rows)
    season = {str(s): _metrics([r for r in rows if r["season"] == s])
              for s in DESIGN_SEASONS}
    positive = sum((m["beta"] is not None and m["beta"] > 0)
                   for m in season.values())
    coverage = all(m["n"] >= MIN_SCOREABLE_PER_SEASON for m in season.values())
    beta_ok = pooled["beta"] is not None and pooled["beta"] >= MIN_BETA
    accuracy_ok = (pooled["model_mae"] is not None
                   and pooled["model_mae"] <= pooled["close_mae"] + MAX_MAE_DEFICIT_POINTS)
    passed = coverage and beta_ok and positive >= MIN_POSITIVE_SEASONS and accuracy_ok
    return {
        "status": ("PASSED_PRE_FREEZE_SCREEN_RESEARCH_ONLY" if passed else
                   "INSUFFICIENT_SCOREABLE_DESIGN_SEASONS" if not coverage else
                   "FAILED_NO_VIABLE_SCORE_ONLY_CONSTRUCTION"),
        "criteria": {
            "min_beta": MIN_BETA, "min_positive_seasons": MIN_POSITIVE_SEASONS,
            "max_mae_worse_than_close_points": MAX_MAE_DEFICIT_POINTS,
            "min_scoreable_per_season": MIN_SCOREABLE_PER_SEASON,
        },
        "checks": {"coverage": coverage, "beta": beta_ok,
                   "season_signs": positive >= MIN_POSITIVE_SEASONS,
                   "accuracy": accuracy_ok},
        "positive_seasons": positive, "pooled": pooled, "by_season": season,
    }


def evaluate(data_dir: Path) -> tuple[dict, list[dict]]:
    results_file = data_dir / "sdv_cfb_results_all.csv"
    closes_file = data_dir / "sdv_cfb_closes_all.csv"
    results = pd.read_csv(results_file, low_memory=False)
    closes = pd.read_csv(closes_file, low_memory=False)
    required_results = {"game_id", "season", "week", "start_date", "neutral_site",
                        "home_id", "away_id", "home_division", "away_division",
                        "home_points", "away_points"}
    required_closes = {"game_id", "season", "home_id", "away_id", "neutral_site",
                       "home_team_spread", "over_under", "spread_scoreable",
                       "total_scoreable", "home_division", "away_division"}
    if not required_results.issubset(results) or not required_closes.issubset(closes):
        raise ValueError("CFB_SUCCESSOR_SOURCE_SCHEMA_MISSING")
    if results.game_id.duplicated().any() or closes.game_id.duplicated().any():
        raise ValueError("CFB_SUCCESSOR_DUPLICATE_GAME_ID")
    if any(int(s) not in DESIGN_SEASONS for s in results.season.unique()):
        raise ValueError("CFB_SUCCESSOR_UNREGISTERED_RESULT_SEASON")
    if any(int(s) not in DESIGN_SEASONS for s in closes.season.unique()):
        raise ValueError("CFB_SUCCESSOR_UNREGISTERED_CLOSE_SEASON")
    if set(results.season) != set(DESIGN_SEASONS):
        raise ValueError("CFB_SUCCESSOR_MISSING_DESIGN_SEASON")

    by_close = {int(r.game_id): r for r in closes.itertuples(index=False)}
    by_result = {int(r.game_id): r for r in results.itertuples(index=False)}
    predictions = []
    source_counts = {
        "completed_result_rows": len(results),
        "result_fbs_fbs_rows": int(((results.home_division == "fbs")
                                   & (results.away_division == "fbs")).sum()),
        "result_non_fbs_fbs_excluded": int(((results.home_division != "fbs")
                                            | (results.away_division != "fbs")).sum()),
        "published_close_rows": len(closes),
        "published_scoreable_spread_rows": int(sum(_bool(x) for x in closes.spread_scoreable)),
        "published_scoreable_total_rows": int(sum(_bool(x) for x in closes.total_scoreable)),
    }
    home_missing = results.home_division.isna()
    away_missing = results.away_division.isna()
    missing = home_missing | away_missing
    source_counts["missing_home_division"] = int(home_missing.sum())
    source_counts["missing_away_division"] = int(away_missing.sum())
    source_counts["missing_either_division"] = int(missing.sum())
    source_counts["non_fbs_fbs_with_known_divisions"] = (
        source_counts["result_non_fbs_fbs_excluded"] - int(missing.sum()))
    source_counts["fbs_fbs_before_week5"] = int((
        (results.home_division == "fbs") & (results.away_division == "fbs")
        & (results.week < FIRST_ELIGIBLE_WEEK)
    ).sum())
    for season, group in results.groupby("season"):
        predictions.extend(project_season(_load_games(group)))
    source_counts["fbs_fbs_week5_plus"] = (
        source_counts["result_fbs_fbs_rows"] - source_counts["fbs_fbs_before_week5"])
    source_counts["week5_plus_insufficient_prior_history"] = (
        source_counts["fbs_fbs_week5_plus"] - len(predictions))
    if source_counts["week5_plus_insufficient_prior_history"] < 0:
        raise ValueError("CFB_SUCCESSOR_PROJECTION_POPULATION_INCONSISTENT")
    rows = []
    exclusions = Counter()
    for p in predictions:
        c = by_close.get(p.game_id)
        if c is None:
            exclusions["NO_PUBLISHED_CLOSE"] += 1
            continue
        if (int(c.season) != p.season
                or str(c.home_division) != "fbs" or str(c.away_division) != "fbs"):
            raise ValueError(f"CFB_SUCCESSOR_CLOSE_IDENTITY_MISMATCH:{p.game_id}")
        # A prediction's exact teams and venue must be checked against the
        # score source, not joined by name or an inferred home-field flag.
        original = by_result[p.game_id]
        if (int(c.home_id) != int(original.home_id)
                or int(c.away_id) != int(original.away_id)
                or _bool(c.neutral_site) != _bool(original.neutral_site)):
            raise ValueError(f"CFB_SUCCESSOR_CLOSE_EVENT_MISMATCH:{p.game_id}")
        for market, raw, line_col, scoreable, actual in (
            ("SPREAD", p.raw_margin, "home_team_spread", c.spread_scoreable,
             float(original.home_points - original.away_points)),
            ("TOTAL", p.raw_total, "over_under", c.total_scoreable,
             float(original.home_points + original.away_points)),
        ):
            if not _bool(scoreable):
                exclusions[f"{market}_UNAVAILABLE"] += 1
                continue
            line = float(getattr(c, line_col))
            if not math.isfinite(line):
                raise ValueError(f"CFB_SUCCESSOR_SCOREABLE_NONFINITE_CLOSE:{p.game_id}")
            close = -line if market == "SPREAD" else line
            rows.append({
                "season": p.season, "game_id": p.game_id, "market": market,
                "raw_prediction": raw, "market_close": close, "actual": actual,
                "disagreement": raw - close, "result_minus_close": actual - close,
                "week": p.week, "training_games_available": p.training_games_available,
            })
    by_market = {m: screen([r for r in rows if r["market"] == m])
                 for m in ("SPREAD", "TOTAL")}
    return ({
        "model_version": MODEL_VERSION,
        "research_only": True,
        "verified_point_in_time": False,
        "score_availability": "KICKOFF_PLUS_24H_UNVERIFIED_PROXY",
        "verified_clv": False,
        "closing_quote_timestamps_available": False,
        "historical_price_evidence_available": False,
        "production_eligible": False,
        "cfb_production_weight": 0,
        "model_p_authority": False,
        "staking_authority": False,
        "freeze_authorized": False,
        "forward_clock_started": False,
        "post_freeze_issuance_cap_proposal_points": MAX_MARKET_DISAGREEMENT,
        "screen_uses_uncapped_market_disagreement": True,
        "backup_qb_signal": "NOT_EVALUATED_NO_HISTORICAL_ASOF_QB_RECEIPTS",
        "design_seasons": list(DESIGN_SEASONS),
        "fixed_research_instantiation": {
            "base_points": BASE_POINTS, "home_field_points": HFA_POINTS,
            "last_games": LAST_GAMES, "ridge_games": RIDGE_GAMES,
            "first_eligible_week": FIRST_ELIGIBLE_WEEK,
            "min_prior_games": MIN_PRIOR_GAMES, "raw_margin_cap": MAX_RAW_MARGIN,
            "score_embargo_hours": EMBARGO.total_seconds() / 3600,
        },
        "data_sha256": {
            f.name: _sha(f) for f in (results_file, closes_file,
                                      data_dir / "provenance.json")
        },
        "source_asset_provenance": json.loads((data_dir / "provenance.json").read_text()),
        "code_sha256": {
            "converged_successor.py": _sha(ROOT / "sportsedge/sports/cfb/converged_successor.py"),
            "evaluate_cfb_converged_viability.py": _sha(Path(__file__)),
        },
        "source_population": source_counts,
        "exclusions_after_eligible_projection": dict(sorted(exclusions.items())),
        "projections_before_close_join": len(predictions),
        "market_results": by_market,
        "disposition": ("PRE_FREEZE_SIGNAL_SCREEN_PASSED_NO_AUTHORITY"
                        if any(x["status"] == "PASSED_PRE_FREEZE_SCREEN_RESEARCH_ONLY"
                               for x in by_market.values())
                        else "NO_VIABLE_SCORE_ONLY_CONSTRUCTION_IN_THIS_FIXED_SCREEN"),
    }, rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="output/cfb_sdv_closes")
    ap.add_argument("--out-dir", default="output/cfb_converged_screen")
    args = ap.parse_args(argv)
    report, rows = evaluate(Path(args.data_dir))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    pd.DataFrame(rows).to_csv(out / "predictions.csv", index=False)
    for name, result in report["market_results"].items():
        print(f"{name}: {result['status']} n={result['pooled']['n']} "
              f"beta={result['pooled']['beta']} "
              f"MAE={result['pooled']['model_mae']} "
              f"close_MAE={result['pooled']['close_mae']}")
    print("RESEARCH_ONLY, NO_VERIFIED_CLV, NO_MODEL_P, CFB_PRODUCTION_WEIGHT=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
