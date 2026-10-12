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


def to_markdown(report, *, candidate_records=None, title="Backtest factor evaluation"):
    """Markdown report. ``candidate_records`` enables the calibration table."""
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
    lines += [
        "",
        "Brier delta (candidate - existing): %+.4f" % (c["brier"] - e["brier"]),
        "Log-loss delta (candidate - existing): %+.4f" % (c["log_loss"] - e["log_loss"]),
        "",
    ]
    if candidate_records:
        lines += ["## Candidate calibration (out-of-sample)", "",
                  _calibration_markdown(candidate_records), ""]
    lines += ["_research_only: no betting authority. min_n=%d._" % r["min_n"]]
    return "\n".join(lines)
