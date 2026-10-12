"""Factor-evaluation report against Isaac's bar. Research only.

Verdicts:
  PASS            - candidate beats the existing model out-of-sample on BOTH
                    Brier and log-loss, with enough samples, and (when a
                    market baseline exists) beats that too.
  CONDITIONAL_PASS - candidate beats the existing model, but no market
                    baseline exists to check the second leg. Per Isaac's bar
                    this is NOT a full pass: the factor may be evaluated
                    further but must not enter production pricing on this
                    verdict alone.
  FAIL            - any leg fails, with explicit reasons.

A market baseline that does not exist is flagged MISSING, never invented.
"""
from __future__ import annotations

import json

from . import metrics


class ReportError(ValueError):
    pass


def _summary(name, summary):
    if not isinstance(summary, dict):
        raise ReportError("BACKTEST_REPORT_SUMMARY_MALFORMED:" + name)
    if "n" not in summary:
        raise ReportError("BACKTEST_REPORT_SUMMARY_INCOMPLETE:" + name)
    if summary["n"] > 0:
        for key in ("brier", "log_loss"):
            if key not in summary:
                raise ReportError("BACKTEST_REPORT_SUMMARY_INCOMPLETE:" + name)
    return summary


def evaluate(*, candidate, existing, baseline=None, baseline_status="MISSING",
             min_n=30):
    """Apply Isaac's bar. ``candidate``/``existing`` are metrics.summarize()
    dicts; ``baseline`` likewise or None."""
    cand = _summary("candidate", candidate)
    curr = _summary("existing", existing)
    reasons = []
    if cand["n"] < min_n:
        reasons.append(
            "INSUFFICIENT_OUT_OF_SAMPLE: n=%d < min_n=%d" % (cand["n"], min_n))
    if cand["n"] == 0:
        reasons.append("CANDIDATE_HAS_NO_PREDICTIONS")
    else:
        if not cand["brier"] < curr["brier"]:
            reasons.append(
                "BRIER_NOT_IMPROVED: candidate %.4f vs existing %.4f"
                % (cand["brier"], curr["brier"]))
        if not cand["log_loss"] < curr["log_loss"]:
            reasons.append(
                "LOG_LOSS_NOT_IMPROVED: candidate %.4f vs existing %.4f"
                % (cand["log_loss"], curr["log_loss"]))
    base = None
    if baseline is not None:
        base = _summary("baseline", baseline)
        if base["n"] > 0 and cand["n"] > 0:
            if not cand["brier"] < base["brier"]:
                reasons.append(
                    "BASELINE_BRIER_NOT_IMPROVED: candidate %.4f vs baseline %.4f"
                    % (cand["brier"], base["brier"]))

    if reasons:
        verdict = "FAIL"
    elif baseline_status == "MISSING" or baseline is None or base["n"] == 0:
        verdict = "CONDITIONAL_PASS"
        reasons.append(
            "MARKET_BASELINE_MISSING: no archived market prices; the "
            "market-baseline leg of Isaac's bar could not be checked. "
            "Do not promote on this verdict alone.")
    else:
        verdict = "PASS"
    return {
        "verdict": verdict,
        "reasons": reasons,
        "candidate": cand,
        "existing": curr,
        "baseline": {"status": baseline_status,
                     "summary": base if base is not None else {"n": 0}},
        "min_n": min_n,
        "research_only": True,
    }


def to_json(report):
    return json.dumps(report, indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Actionability metric (pipeline health, not a model gate)
# ---------------------------------------------------------------------------
#
# Isaac's frustration metric ("every run comes back empty"): on a typical
# board/run, what share of selections actually reaches the user as
# actionable? This measures the PIPELINE — pricing coverage and quote
# freshness — not model skill. It needs no harness-gating itself; the
# goal is to GROW the actionable share via correct pricing, broader
# coverage, and fresher quotes. The bar does not lower.
#
# Input: a list of selection records (dicts), each carrying the pipeline
# "status" string (e.g. card["evaluated_rows"] from the RUN IT pipeline).
# Classification:
#   ACTIONABLE - priced with a current quote (status in PRICED_STATUSES)
#   WATCH      - priced but the quote is stale (status starts with WATCH_)
#   BLOCKED    - everything else, grouped by exact status/reason code
#
# Output is a JSON-serializable dict so it can be stored per run and
# tracked over time.

PRICED_STATUSES = frozenset({
    "RESEARCH_CANDIDATE_NOT_VALIDATED",  # priced, current quote, research-only
    "PRICED_RESEARCH",
    "PRICED",
})
WATCH_STATUS_PREFIX = "WATCH_"
MISSING_STATUS = "MISSING_STATUS"


def _classify_selection(status, priced_statuses, watch_prefix):
    status = str(status or "").strip() or MISSING_STATUS
    if status in priced_statuses:
        return "actionable"
    if status.startswith(watch_prefix):
        return "watch"
    return "blocked"


def summarize_actionability(records, *, run_id=None, run_at=None,
                            priced_statuses=None, watch_prefix=None):
    """Summarize a board/run into the actionability metric.

    Returns a JSON-serializable dict:
      {run_id, run_at, total,
       actionable: {n, pct}, watch: {n, pct},
       blocked: {n, pct, by_reason: {code: n}},
       research_only: True}
    """
    if not isinstance(records, list):
        raise ReportError("BACKTEST_ACTIONABILITY_RECORDS_NOT_LIST")
    priced = PRICED_STATUSES if priced_statuses is None else frozenset(
        str(s) for s in priced_statuses)
    prefix = WATCH_STATUS_PREFIX if watch_prefix is None else str(watch_prefix)
    n_actionable = n_watch = 0
    by_reason = {}
    for record in records:
        if not isinstance(record, dict):
            raise ReportError("BACKTEST_ACTIONABILITY_RECORD_NOT_OBJECT")
        bucket = _classify_selection(record.get("status"), priced, prefix)
        if bucket == "actionable":
            n_actionable += 1
        elif bucket == "watch":
            n_watch += 1
        else:
            status = str(record.get("status") or "").strip() or MISSING_STATUS
            by_reason[status] = by_reason.get(status, 0) + 1
    total = len(records)
    n_blocked = total - n_actionable - n_watch

    def pct(n):
        return round(100.0 * n / total, 1) if total else 0.0

    return {
        "run_id": run_id,
        "run_at": run_at,
        "total": total,
        "actionable": {"n": n_actionable, "pct": pct(n_actionable)},
        "watch": {"n": n_watch, "pct": pct(n_watch)},
        "blocked": {"n": n_blocked, "pct": pct(n_blocked),
                    "by_reason": dict(sorted(by_reason.items()))},
        "research_only": True,
    }


def actionability_to_json(summary):
    """JSON string of an actionability summary (for per-run tracking)."""
    if not isinstance(summary, dict) or "total" not in summary:
        raise ReportError("BACKTEST_ACTIONABILITY_SUMMARY_MALFORMED")
    return json.dumps(summary, indent=2, sort_keys=True)


def actionability_to_markdown(summary, *, title="Actionability"):
    """Markdown rendering of an actionability summary."""
    if not isinstance(summary, dict) or "total" not in summary:
        raise ReportError("BACKTEST_ACTIONABILITY_SUMMARY_MALFORMED")
    a, w, b = summary["actionable"], summary["watch"], summary["blocked"]
    lines = [
        "## %s: %d selections" % (title, summary["total"]),
        "",
        "| bucket | n | pct |",
        "|---|---:|---:|",
        "| actionable (priced, current quote) | %d | %.1f%% |" % (a["n"], a["pct"]),
        "| watch (priced, stale quote) | %d | %.1f%% |" % (w["n"], w["pct"]),
        "| blocked | %d | %.1f%% |" % (b["n"], b["pct"]),
        "",
    ]
    if b["by_reason"]:
        lines += ["Blocked by reason:", ""]
        lines += ["- %s: %d" % (code, n)
                  for code, n in b["by_reason"].items()]
        lines.append("")
    return "\n".join(lines)


def _calibration_markdown(records):
    rows = metrics.calibration_bins(records, n_bins=10)
    lines = ["| prob bin | n | mean p | hit rate |",
             "|---|---:|---:|---:|"]
    for b in rows:
        mp = "—" if b["mean_p"] is None else "%.3f" % b["mean_p"]
        hr = "—" if b["hit_rate"] is None else "%.3f" % b["hit_rate"]
        lines.append("| %.1f-%.1f | %d | %s | %s |"
                     % (b["lo"], b["hi"], b["n"], mp, hr))
    return "\n".join(lines)


def to_markdown(report, *, candidate_records=None, title="Backtest factor evaluation",
                extra_models=None, actionability=None):
    """Markdown report. ``candidate_records`` enables the calibration table.

    ``extra_models``: optional {"name": summarize_dict} of additional legs
    (e.g. {"elo": elo_summary, "naive": naive_summary}) rendered as
    comparison-floor rows. They do not change the verdict.
    ``actionability``: optional summarize_actionability() dict appended as
    the pipeline-health section (the board/run this evaluation ran on).
    """
    r = report
    c, e = r["candidate"], r["existing"]
    b = r["baseline"]
    lines = [
        "# " + title,
        "",
        "## Verdict: %s" % r["verdict"],
        "",
    ]
    if r["reasons"]:
        lines.append("Reasons:")
        lines += ["- " + reason for reason in r["reasons"]]
        lines.append("")
    lines += [
        "| model | n | Brier | log loss | mean p | base rate |",
        "|---|---:|---:|---:|---:|---:|",
        "| candidate | %(n)d | %(brier).4f | %(log_loss).4f | %(mean_p).3f | %(base_rate).3f |" % c,
        "| existing | %(n)d | %(brier).4f | %(log_loss).4f | %(mean_p).3f | %(base_rate).3f |" % e,
    ]
    bs = b["summary"]
    if b["status"] == "AVAILABLE" and bs.get("n"):
        lines.append(
            "| market baseline | %(n)d | %(brier).4f | %(log_loss).4f | %(mean_p).3f | %(base_rate).3f |" % bs)
    else:
        lines.append("| market baseline | MISSING — no archived prices; leg not checked |")
    for name, summary in (extra_models or {}).items():
        s = _summary("extra:" + name, summary)
        if s["n"] > 0:
            lines.append(
                "| %s | %d | %.4f | %.4f | %.3f | %.3f |"
                % (name, s["n"], s["brier"], s["log_loss"],
                   s["mean_p"], s["base_rate"]))
        else:
            lines.append("| %s | no predictions |" % name)
    lines += [
        "",
        "Brier delta (candidate - existing): %+.4f" % (c["brier"] - e["brier"]),
        "Log-loss delta (candidate - existing): %+.4f" % (c["log_loss"] - e["log_loss"]),
        "",
    ]
    if candidate_records:
        lines += ["## Candidate calibration (out-of-sample)", "",
                  _calibration_markdown(candidate_records), ""]
    if actionability is not None:
        lines += [actionability_to_markdown(actionability), ""]
    lines += ["_research_only: no betting authority. min_n=%d._" % r["min_n"]]
    return "\n".join(lines)
