"""Backtest runner: price historical fixtures point-in-time, settle, score.

Contract for ``price_fn(model_name, fixture, as_of, train)``:
    - ``fixture``: one fixture dict (must carry fixture_id, kickoff, as_of).
    - ``as_of``: ISO timestamp; the model may use ONLY data available at as_of.
    - ``train``: the training fixtures for this split (all kick off before
      the fixture). Prefer adapting existing pricers here rather than
      rewriting them.
    - Returns a list of {"market", "selection", "line" (optional),
      "model_p"} dicts.

Contract for ``settle_fn(fixture, market, selection, line)``:
    - Returns the graded outcome: 1.0 win, 0.0 loss, 0.5 push.

``market_baseline`` (optional): dict keyed
    (fixture_id, market, selection, line) -> baseline probability, or a
    callable with the same lookup signature. When absent, the baseline leg
    is explicitly reported MISSING -- prices are never invented.

Research only. No betting authority.
"""
from __future__ import annotations

from . import metrics


class RunnerError(ValueError):
    pass


def _check_prediction(pred, model_name):
    if not isinstance(pred, dict):
        raise RunnerError("BACKTEST_PREDICTION_NOT_OBJECT:" + model_name)
    market = str(pred.get("market") or "").strip()
    selection = str(pred.get("selection") or "").strip()
    if not market or not selection:
        raise RunnerError("BACKTEST_PREDICTION_MARKET_SELECTION_REQUIRED:" + model_name)
    try:
        p = float(pred["model_p"])
    except (KeyError, ValueError, TypeError) as exc:
        raise RunnerError("BACKTEST_PREDICTION_PROBABILITY_UNVERIFIED:" + model_name) from exc
    if not 0.0 <= p <= 1.0:
        raise RunnerError("BACKTEST_PREDICTION_PROBABILITY_INVALID:" + model_name)
    import math
    if not math.isfinite(p):
        raise RunnerError("BACKTEST_PREDICTION_PROBABILITY_INVALID:" + model_name)
    return {"market": market, "selection": selection,
            "line": pred.get("line"), "model_p": p}


def _baseline_lookup(market_baseline):
    if market_baseline is None:
        return None
    if callable(market_baseline):
        return market_baseline
    if not isinstance(market_baseline, dict):
        raise RunnerError("BACKTEST_BASELINE_MALFORMED")

    def lookup(fixture_id, market, selection, line):
        return market_baseline.get((fixture_id, market, selection, line))
    return lookup


def run_backtest(*, fixtures, splits, models, price_fn, settle_fn,
                 market_baseline=None):
    """Run all splits; return per-model prediction records.

    Returns {"records": {model: [record, ...]},
             "baseline": {"status": "AVAILABLE"|"MISSING", "records": [...]},
             "n_splits": int}
    Record: {fixture_id, as_of, kickoff, market, selection, line,
             model_p, outcome, model}.
    """
    if not isinstance(models, list) or not models or not all(
            isinstance(m, str) and m for m in models):
        raise RunnerError("BACKTEST_MODELS_INVALID")
    if len(set(models)) != len(models):
        raise RunnerError("BACKTEST_MODELS_DUPLICATE")
    baseline_fn = _baseline_lookup(market_baseline)
    split_list = list(splits)
    if not split_list:
        raise RunnerError("BACKTEST_NO_SPLITS")

    records = {m: [] for m in models}
    baseline_records = []
    for split in split_list:
        train, test = split.train, split.test
        for fixture in test:
            if not isinstance(fixture, dict):
                raise RunnerError("BACKTEST_FIXTURE_NOT_OBJECT")
            fid = str(fixture.get("fixture_id") or "").strip()
            as_of = str(fixture.get("as_of") or "").strip()
            kickoff = str(fixture.get("kickoff") or "").strip()
            if not fid or not as_of or not kickoff:
                raise RunnerError("BACKTEST_FIXTURE_IDENTITY_REQUIRED")
            for model in models:
                try:
                    preds = price_fn(model, fixture, as_of, train)
                except Exception as exc:
                    raise RunnerError(
                        "BACKTEST_PRICE_FN_FAILED:" + model + ":" + fid) from exc
                if not isinstance(preds, list):
                    raise RunnerError("BACKTEST_PRICE_FN_NOT_LIST:" + model)
                for raw in preds:
                    pred = _check_prediction(raw, model)
                    try:
                        outcome = settle_fn(fixture, pred["market"],
                                            pred["selection"], pred["line"])
                    except Exception as exc:
                        raise RunnerError(
                            "BACKTEST_SETTLE_FAILED:" + fid) from exc
                    try:
                        y = float(outcome)
                    except (ValueError, TypeError) as exc:
                        raise RunnerError(
                            "BACKTEST_OUTCOME_UNVERIFIED:" + fid) from exc
                    if y not in (0.0, 0.5, 1.0):
                        raise RunnerError("BACKTEST_OUTCOME_INVALID:" + fid)
                    records[model].append({
                        "fixture_id": fid, "as_of": as_of, "kickoff": kickoff,
                        "market": pred["market"], "selection": pred["selection"],
                        "line": pred["line"], "model_p": pred["model_p"],
                        "outcome": y, "model": model,
                    })
                    if baseline_fn is not None:
                        bp = baseline_fn(fid, pred["market"], pred["selection"],
                                         pred["line"])
                        if bp is not None:
                            try:
                                bpf = float(bp)
                            except (ValueError, TypeError) as exc:
                                raise RunnerError(
                                    "BACKTEST_BASELINE_PROBABILITY_UNVERIFIED") from exc
                            if not 0.0 < bpf < 1.0:
                                raise RunnerError(
                                    "BACKTEST_BASELINE_PROBABILITY_INVALID")
                            baseline_records.append({
                                "fixture_id": fid, "market": pred["market"],
                                "selection": pred["selection"], "line": pred["line"],
                                "model_p": bpf, "outcome": y, "model": "market_baseline",
                            })
    return {
        "records": records,
        "baseline": {
            "status": "AVAILABLE" if baseline_fn is not None else "MISSING",
            "records": baseline_records,
        },
        "n_splits": len(split_list),
    }


def compare_models(result):
    """Score every model's records; return summaries and candidate deltas."""
    summaries = {}
    for model, recs in result["records"].items():
        summaries[model] = metrics.summarize(recs) if recs else {"n": 0}
    baseline = result["baseline"]
    baseline_summary = (metrics.summarize(baseline["records"])
                        if baseline["records"] else {"n": 0})
    return {
        "models": summaries,
        "baseline": {"status": baseline["status"], "summary": baseline_summary},
        "n_splits": result["n_splits"],
    }
