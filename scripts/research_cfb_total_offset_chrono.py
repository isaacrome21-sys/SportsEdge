"""Research-only chronological CFB totals-intercept diagnostic.

Accepts already-created pregame predictions paired with settled scores.
No frozen scorer changes, no sportsbook probability/staking authority.
Retrospectively reconstructed examples NEVER establish forward PIT evidence.
"""
from __future__ import annotations

import argparse
import json
from math import isfinite, sqrt
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "CFB_TOTAL_OFFSET_CHRONO_RESEARCH_V1"
DATA_ROLES = {"RECONSTRUCTED_DEVELOPMENT", "CAPTURED_PREGAME_RESEARCH"}


def _utc_timestamp(value, field):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("timezone required")
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("CFB_TOTAL_OFFSET_TIMESTAMP_INVALID:" + field) from exc


def _number(value, field):
    if isinstance(value, bool):
        raise ValueError("CFB_TOTAL_OFFSET_NUMERIC_INVALID:" + field)
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("CFB_TOTAL_OFFSET_NUMERIC_INVALID:" + field) from exc
    if not isfinite(result):
        raise ValueError("CFB_TOTAL_OFFSET_NUMERIC_INVALID:" + field)
    return result


def _parse(rows):
    if not isinstance(rows, list) or not rows:
        raise ValueError("CFB_TOTAL_OFFSET_ROWS_REQUIRED")
    seen, parsed = set(), []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("CFB_TOTAL_OFFSET_ROW_INVALID")
        year, week = row.get("season"), row.get("week")
        if isinstance(year, bool) or isinstance(week, bool) or not isinstance(year, int) or not isinstance(week, int) or year < 2015 or not 1 <= week <= 20:
            raise ValueError("CFB_TOTAL_OFFSET_PERIOD_INVALID")
        game_id = str(row.get("game_id") or "")
        key = (year, week, game_id)
        if not game_id or key in seen:
            raise ValueError("CFB_TOTAL_OFFSET_DUPLICATE_OR_MISSING_GAME")
        seen.add(key)
        role = row.get("evidence_role")
        if role not in DATA_ROLES:
            raise ValueError("CFB_TOTAL_OFFSET_EVIDENCE_ROLE_REQUIRED")
        if role == "CAPTURED_PREGAME_RESEARCH":
            prediction_time = _utc_timestamp(row.get("prediction_captured_at"), "prediction_captured_at")
            kickoff_time = _utc_timestamp(row.get("kickoff_at"), "kickoff_at")
            settled_time = _utc_timestamp(row.get("settled_at"), "settled_at")
            if not prediction_time < kickoff_time < settled_time:
                raise ValueError("CFB_TOTAL_OFFSET_CAPTURE_NOT_PREGAME")
            source_sha256 = str(row.get("source_sha256") or "")
            if len(source_sha256) != 64 or any(c not in "0123456789abcdef" for c in source_sha256):
                raise ValueError("CFB_TOTAL_OFFSET_SOURCE_HASH_REQUIRED")
        model = _number(row.get("model_total"), "model_total")
        actual = _number(row.get("actual_total"), "actual_total")
        if not 0 <= model <= 150 or not 0 <= actual <= 200:
            raise ValueError("CFB_TOTAL_OFFSET_POINTS_RANGE_INVALID")
        close = row.get("closing_total")
        close = None if close is None else _number(close, "closing_total")
        if close is not None and not 1 <= close <= 150:
            raise ValueError("CFB_TOTAL_OFFSET_CLOSE_RANGE_INVALID")
        parsed.append({"season": year, "week": week, "game_id": game_id,
                       "role": role, "model": model, "actual": actual,
                       "close": close})
    return parsed


def _metrics(rows, offset):
    errors = [r["model"] + offset - r["actual"] for r in rows]
    closes = [r for r in rows if r["close"] is not None]
    return {"n": len(rows),
            "mean_error_points": sum(errors) / len(errors),
            "mae_points": sum(abs(e) for e in errors) / len(errors),
            "rmse_points": sqrt(sum(e * e for e in errors) / len(errors)),
            "closing_lines_joined": len(closes),
            "closing_total_mae_points": (
                sum(abs(r["close"] - r["actual"]) for r in closes) / len(closes)
                if closes else None)}


def evaluate_chronological(rows, *, train_through, holdout_from,
                           min_train=50, min_holdout=20):
    """Estimate total correction on past outcomes, score later held-out rows.

    Closing lines never enter fitting. A later season/week cannot leak into
    training. Results always retain zero betting/promotion authority.
    """
    parsed = _parse(rows)
    train_period = tuple(train_through)
    test_period = tuple(holdout_from)
    if len(train_period) != 2 or len(test_period) != 2 or not train_period < test_period:
        raise ValueError("CFB_TOTAL_OFFSET_CHRONOLOGY_INVALID")
    train = [r for r in parsed if (r["season"], r["week"]) <= train_period]
    test = [r for r in parsed if (r["season"], r["week"]) >= test_period]
    if len(train) < min_train or len(test) < min_holdout:
        raise ValueError("CFB_TOTAL_OFFSET_HOLDOUT_UNDERSIZED")
    offset = sum(r["actual"] - r["model"] for r in train) / len(train)
    if abs(offset) > 10:
        raise ValueError("CFB_TOTAL_OFFSET_SUSPECT_MAGNITUDE")
    return {
        "schema": SCHEMA,
        "evidence_roles": sorted({r["role"] for r in parsed}),
        "evidence_class": "RETROSPECTIVE_RESEARCH_ONLY",
        "train_through": list(train_period),
        "holdout_from": list(test_period),
        "train_n": len(train),
        "holdout_n": len(test),
        "offset_points": offset,
        "train_baseline": _metrics(train, 0.0),
        "holdout_baseline": _metrics(test, 0.0),
        "holdout_adjusted": _metrics(test, offset),
        "fit_inputs": "MODEL_TOTAL_AND_SETTLED_SCORE_ONLY_CLOSE_EXCLUDED",
        "calibration_applied_in_production": False,
        "market_probability_calibrated": False,
        "positive_ev_proven": False,
        "staking_authority": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train-year", type=int, required=True)
    parser.add_argument("--train-week", type=int, required=True)
    parser.add_argument("--holdout-year", type=int, required=True)
    parser.add_argument("--holdout-week", type=int, required=True)
    args = parser.parse_args(argv)
    report = evaluate_chronological(
        json.loads(args.input.read_text()),
        train_through=(args.train_year, args.train_week),
        holdout_from=(args.holdout_year, args.holdout_week),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("CFB_TOTAL_OFFSET_RESEARCH_ONLY train=%d holdout=%d offset=%+.3f MAE=%.3f->%.3f" %
          (report["train_n"], report["holdout_n"], report["offset_points"],
           report["holdout_baseline"]["mae_points"],
           report["holdout_adjusted"]["mae_points"]))


if __name__ == "__main__":
    main()
