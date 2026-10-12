"""Strict, point-in-time paired MLB game-market evaluation.

Input rows are immutable *observations*, not candidate training data.
All three probabilities must refer to the same game, offered selection and
line. An absent or unattributed market observation blocks a verdict rather
than allowing an incomparable denominator. No live-pricing import or output.

This evaluator cannot establish betting profitability or cure a retrospectively
chosen model. It is a forecasting evidence screen only.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from math import isfinite, log
from random import Random

VERSION = "MLB_STRICT_PAIRED_OOS_V1"
REQUIRED = (
    "fixture_id", "series_id", "market", "selection", "line",
    "kickoff_utc", "as_of_utc", "feature_max_available_at_utc",
    "train_last_final_at_utc", "model_source_sha", "market_blind",
    "candidate_p", "existing_p", "outcome",
    "market_book", "opposite_book", "market_yes_american",
    "market_no_american", "market_yes_captured_at_utc",
    "market_no_captured_at_utc", "opposite_selection",
)
OPPOSITES = {"HOME": "AWAY", "AWAY": "HOME",
             "OVER": "UNDER", "UNDER": "OVER"}


class EvidenceError(ValueError):
    pass


def _stamp(value, key):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise EvidenceError("TIMESTAMP_INVALID:" + key) from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise EvidenceError("TIMESTAMP_NOT_UTC_AWARE:" + key)
    return stamp.astimezone(timezone.utc)


def _p(value, key):
    if isinstance(value, bool):
        raise EvidenceError("PROBABILITY_INVALID:" + key)
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceError("PROBABILITY_INVALID:" + key) from exc
    if not isfinite(x) or not 0 < x < 1:
        raise EvidenceError("PROBABILITY_INVALID:" + key)
    return x


def _decimal(value, key):
    if isinstance(value, bool):
        raise EvidenceError("ODDS_INVALID:" + key)
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceError("ODDS_INVALID:" + key) from exc
    if not isfinite(v) or v == 0 or -100 <= v < 100:
        raise EvidenceError("ODDS_INVALID:" + key)
    return 1 + (v / 100 if v > 0 else 100 / (-v))


def _validated(row):
    if not isinstance(row, dict):
        raise EvidenceError("ROW_NOT_OBJECT")
    absent = [k for k in REQUIRED if k not in row or row[k] is None or row[k] == ""]
    if absent:
        raise EvidenceError("MISSING_PIT_EVIDENCE:" + ",".join(absent))
    market = str(row["market"]).upper()
    selection = str(row["selection"]).upper()
    if market not in {"ML", "SPREAD", "TOTAL"}:
        raise EvidenceError("MARKET_SETTLEMENT_UNSUPPORTED")
    if selection not in OPPOSITES or str(row["opposite_selection"]).upper() != OPPOSITES[selection]:
        raise EvidenceError("MARKET_PAIR_SELECTION_CONFLICT")
    if market == "TOTAL" and selection not in {"OVER", "UNDER"}:
        raise EvidenceError("MARKET_SELECTION_CONFLICT")
    if market in {"ML", "SPREAD"} and selection not in {"HOME", "AWAY"}:
        raise EvidenceError("MARKET_SELECTION_CONFLICT")
    if market == "ML" and row["line"] != "ML":
        raise EvidenceError("ML_NO_POINT_EXPECTED")
    if market != "ML":
        try:
            point = float(row["line"])
        except (TypeError, ValueError) as exc:
            raise EvidenceError("MARKET_LINE_INVALID") from exc
        if not isfinite(point):
            raise EvidenceError("MARKET_LINE_INVALID")
    if row["market_blind"] is not True:
        raise EvidenceError("MARKET_BLIND_MODEL_REQUIRED")
    if str(row["market_book"]).lower() != str(row["opposite_book"]).lower():
        raise EvidenceError("BOOK_PAIR_MISMATCH")
    if str(row["market_book"]).strip() == "":
        raise EvidenceError("BOOK_UNKNOWN")
    if not all(str(row[k]).strip() for k in (
        "fixture_id", "series_id", "model_source_sha")):
        raise EvidenceError("IDENTITY_OR_MODEL_VERSION_MISSING")
    kickoff = _stamp(row["kickoff_utc"], "kickoff_utc")
    as_of = _stamp(row["as_of_utc"], "as_of_utc")
    feature_at = _stamp(row["feature_max_available_at_utc"], "feature_max_available_at_utc")
    train_at = _stamp(row["train_last_final_at_utc"], "train_last_final_at_utc")
    yes_at = _stamp(row["market_yes_captured_at_utc"], "market_yes_captured_at_utc")
    no_at = _stamp(row["market_no_captured_at_utc"], "market_no_captured_at_utc")
    if not (train_at < as_of < kickoff and feature_at <= as_of):
        raise EvidenceError("PIT_TRAIN_OR_FEATURE_LEAKAGE")
    if not (yes_at < kickoff and no_at < kickoff):
        raise EvidenceError("MARKET_QUOTE_NOT_PREGAME")
    if abs((yes_at - no_at).total_seconds()) > 120:
        raise EvidenceError("MARKET_PAIR_ASYNCHRONOUS")
    if (kickoff - max(yes_at, no_at)).total_seconds() > 1800:
        raise EvidenceError("MARKET_NOT_VERIFIED_CLOSE")
    candidate = _p(row["candidate_p"], "candidate_p")
    existing = _p(row["existing_p"], "existing_p")
    yes_dec = _decimal(row["market_yes_american"], "market_yes_american")
    no_dec = _decimal(row["market_no_american"], "market_no_american")
    implied_yes, implied_no = 1 / yes_dec, 1 / no_dec
    market_p = implied_yes / (implied_yes + implied_no)
    # A push is not a binary y=0.5; it needs explicit push-probability
    # settlement and EV semantics, which this lane does not implement.
    if row["outcome"] not in (0, 1) or isinstance(row["outcome"], bool):
        raise EvidenceError("BINARY_OUTCOME_REQUIRED_NO_PUSH")
    key = (str(row["fixture_id"]), market, selection, str(row["line"]))
    return {
        "key": key, "series_id": str(row["series_id"]),
        "model_source_sha": str(row["model_source_sha"]),
        "kickoff": kickoff, "as_of": as_of,
        "outcome": int(row["outcome"]),
        "candidate": candidate, "existing": existing, "market": market_p,
    }


def _loss(row, model, metric):
    p, y = row[model], row["outcome"]
    return (p - y) ** 2 if metric == "brier" else -(y * log(p) + (1 - y) * log(1 - p))


def _ci(rows, model, metric, *, iterations, seed):
    groups = defaultdict(list)
    for r in rows:
        groups[r["series_id"]].append(r)
    keys = sorted(groups)
    rng = Random(seed)
    sims = []
    for _ in range(iterations):
        selected = [r for _ in keys for r in groups[keys[rng.randrange(len(keys))]]]
        sims.append(sum(_loss(r, "candidate", metric) - _loss(r, model, metric)
                        for r in selected) / len(selected))
    sims.sort()
    return [round(sims[int((iterations - 1) * x)], 8) for x in (0.025, 0.975)]


def evaluate(rows, *, min_games=300, min_series=20, bootstrap_reps=1000,
             seed=2074):
    """Single-market, exact paired PIT readout; NEVER grants betting authority.

    Requires one row per selection and identical candidate/existing/market
    comparison unit. Missing evidence blocks the *whole* evaluation.
    Series-block resampling is diagnostic; this is not an edge-ROI test.
    """
    if not isinstance(rows, list) or not rows:
        return {"version": VERSION, "status": "BLOCKED_EVIDENCE",
                "reasons": ["NO_HISTORICAL_RECORDS"], "research_only": True}
    if not 1 <= min_games or not 2 <= min_series or not 100 <= bootstrap_reps:
        raise EvidenceError("PARAMETERS_INVALID")
    accepted, failures, seen = [], Counter(), set()
    for row in rows:
        try:
            item = _validated(row)
            if item["key"] in seen:
                raise EvidenceError("DUPLICATE_GAME_MARKET_SELECTION_LINE")
            seen.add(item["key"])
            accepted.append(item)
        except EvidenceError as exc:
            failures[str(exc).split(":")[0]] += 1
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str,
                                       separators=(",", ":")).encode()).hexdigest()
    result = {
        "version": VERSION, "dataset_sha256": digest, "n_submitted": len(rows),
        "n_verified": len(accepted), "n_rejected": len(rows) - len(accepted),
        "reject_reasons": dict(sorted(failures.items())),
        "research_only": True, "validated_profitability": False,
        "holdout_accessed": False, "authority": "NONE",
    }
    if failures:
        return dict(result, status="BLOCKED_EVIDENCE",
                    reasons=["INCOMPLETE_OR_UNVERIFIABLE_PIT_ROWS_NO_SILENT_DROPS"])
    if len({r["model_source_sha"] for r in accepted}) != 1:
        return dict(result, status="BLOCKED_EVIDENCE", reasons=["MODEL_SHA_NOT_FROZEN"])
    if len({r["key"][1] for r in accepted}) != 1:
        return dict(result, status="BLOCKED_EVIDENCE",
                    reasons=["MARKET_MUST_BE_EVALUATED_SEPARATELY"])
    keys = {r["key"][0] for r in accepted}
    clusters = {r["series_id"] for r in accepted}
    result.update(n_games=len(keys), n_series=len(clusters),
                  model_source_sha=accepted[0]["model_source_sha"],
                  market=accepted[0]["key"][1])
    if len(keys) < min_games or len(clusters) < min_series:
        return dict(result, status="INSUFFICIENT_OOS",
                    reasons=["MIN_GAMES_OR_SERIES_NOT_MET"])
    scored = {}
    meets = True
    for baseline in ("existing", "market"):
        for metric in ("brier", "log_loss"):
            cand = sum(_loss(r, "candidate", metric) for r in accepted) / len(accepted)
            base = sum(_loss(r, baseline, metric) for r in accepted) / len(accepted)
            ci = _ci(accepted, baseline, metric, iterations=bootstrap_reps,
                     seed=seed)
            delta = cand - base
            scored[baseline + "_" + metric] = {
                "candidate": round(cand, 8), "baseline": round(base, 8),
                "delta_candidate_minus_baseline": round(delta, 8),
                "series_block_ci_95": ci,
            }
            if not (delta < 0 and ci[1] < 0):
                meets = False
    result["paired_comparisons"] = scored
    result["status"] = ("FORECAST_IMPROVEMENT_RESEARCH_ONLY" if meets
                        else "NO_DEMONSTRATED_FORECAST_IMPROVEMENT")
    result["reasons"] = ([] if meets else ["PAIRED_DELTAS_NOT_ROBUSTLY_NEGATIVE"])
    return result
