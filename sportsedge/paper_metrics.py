"""Paper (HYPOTHETICAL) tracking metrics for research cards. RESEARCH ONLY.

We place no bets. This ledger is PAPER tracking of what research cards WOULD
have done at flat 1-unit paper stakes, labeled HYPOTHETICAL/RESEARCH on every
output, never presented as actual results. No unverifiable claims, ever.

Conventions (match the backtest harness):
- reason codes in UPPER_SNAKE; ``research_only: True`` on every report;
- a missing closing line degrades to MISSING, never invented;
- degenerate probabilities are fail-closed: the record is rejected with a
  reason, never silently included in a metric.

Definitions:
- beat-close: our independent-lane modeled probability for the selected side
  (``our_p``) vs the archived closing no-vig probability for the same side
  (``close_p``), market data evaluation-side only. A record "beats the close"
  when ``close_p > our_p`` (the closing market agreed with our side more
  strongly than our model did).
- CLV edge (pp): mean(close_p - our_p) x 100 over records with an archived
  close. Research-only analog of the bettor metric; NOT a wagering claim.
- ledger: month-by-month paper W/L/P with red months SHOWN, every profit
  figure next to its units-risked denominator.

Settlement is by recorded outcome, not by us: records arrive with
``result`` in WIN/LOSS/PUSH/UNSETTLED.
"""
from __future__ import annotations

import json
from math import isfinite

SCHEMA = "SPORTSEDGE_PAPER_METRICS_V1"

VALID_RESULTS = frozenset({"WIN", "LOSS", "PUSH", "UNSETTLED"})
SETTLED = frozenset({"WIN", "LOSS", "PUSH"})


class PaperMetricsError(ValueError):
    pass


def _fin(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if isfinite(f) else None


def validate_record(rec):
    """Fail-closed record validation. Raises PaperMetricsError on any
    unusable record; returns a normalized copy otherwise."""
    if not isinstance(rec, dict):
        raise PaperMetricsError("RECORD_MUST_BE_OBJECT")
    out = dict(rec)
    result = str(out.get("result") or "").upper()
    if result not in VALID_RESULTS:
        raise PaperMetricsError("UNKNOWN_RESULT:" + str(out.get("result"))[:60])
    out["result"] = result
    our_p = _fin(out.get("our_p"))
    if our_p is None or not 0.0 < our_p < 1.0:
        raise PaperMetricsError("DEGENERATE_OUR_PROBABILITY")
    out["our_p"] = our_p
    close_status = str(out.get("close_status") or "MISSING").upper()
    if close_status not in ("AVAILABLE", "MISSING"):
        raise PaperMetricsError("UNKNOWN_CLOSE_STATUS:" + close_status[:40])
    out["close_status"] = close_status
    if close_status == "AVAILABLE":
        close_p = _fin(out.get("close_p"))
        if close_p is None or not 0.0 < close_p < 1.0:
            raise PaperMetricsError("DEGENERATE_CLOSE_PROBABILITY")
        out["close_p"] = close_p
    else:
        out["close_p"] = None
    units = _fin(out.get("units", 1.0))
    if units is None or units <= 0:
        raise PaperMetricsError("INVALID_PAPER_UNITS")
    out["units"] = units
    month = str(out.get("month") or "").strip()
    if not month:
        raise PaperMetricsError("RECORD_MONTH_REQUIRED")
    out["month"] = month
    return out


def beat_close(records):
    """Beat-close % and CLV edge over records with an archived close.

    Records without a closing line are counted as MISSING and excluded —
    never invented.
    """
    valid, missing, rejected = [], 0, []
    for i, rec in enumerate(records):
        try:
            v = validate_record(rec)
        except PaperMetricsError as exc:
            rejected.append({"index": i, "reason": str(exc)})
            continue
        if v["close_status"] == "AVAILABLE":
            valid.append(v)
        else:
            missing += 1
    n = len(valid)
    if n == 0:
        return {"status": "MISSING", "n": 0, "beat": 0,
                "beat_close_pct": None, "clv_edge_pp": None,
                "missing_close_n": missing, "rejected_n": len(rejected),
                "reason": "NO_ARCHIVED_CLOSING_LINES"}
    beat = sum(1 for v in valid if v["close_p"] > v["our_p"])
    clv = sum(v["close_p"] - v["our_p"] for v in valid) / n * 100.0
    return {"status": "AVAILABLE", "n": n, "beat": beat,
            "beat_close_pct": round(beat / n * 100, 2),
            "clv_edge_pp": round(clv, 3),
            "missing_close_n": missing, "rejected_n": len(rejected),
            "reason": None}


def _american_profit_units(odds, units):
    """Paper profit in units for a WIN at American odds (flat paper stakes)."""
    o = _fin(odds)
    if o is None:
        raise PaperMetricsError("ODDS_REQUIRED_FOR_SETTLED_RECORD")
    if o == 0:
        raise PaperMetricsError("INVALID_AMERICAN_ODDS")
    if o > 0:
        return units * o / 100.0
    return units * 100.0 / abs(o)


def paper_ledger(records):
    """Month-by-month paper ledger. Red months are SHOWN. Unsettled records
    and records with degenerate inputs are excluded with counts."""
    months = {}
    rejected = 0
    unsettled_n = 0
    for rec in records:
        try:
            v = validate_record(rec)
        except PaperMetricsError:
            rejected += 1
            continue
        if v["result"] == "UNSETTLED":
            unsettled_n += 1
            continue
        m = months.setdefault(v["month"], {"plays": 0, "wins": 0, "losses": 0,
                                           "pushes": 0, "units_risked": 0.0,
                                           "profit_units": 0.0})
        m["plays"] += 1
        m["units_risked"] += v["units"]
        if v["result"] == "WIN":
            m["wins"] += 1
            m["profit_units"] += _american_profit_units(v.get("odds_american"), v["units"])
        elif v["result"] == "LOSS":
            m["losses"] += 1
            m["profit_units"] -= v["units"]
        else:
            m["pushes"] += 1
    rows = []
    for month in sorted(months):
        m = months[month]
        risked = m["units_risked"]
        roi = (m["profit_units"] / risked * 100) if risked else None
        rows.append({
            "month": month,
            "plays": m["plays"], "wins": m["wins"],
            "losses": m["losses"], "pushes": m["pushes"],
            "units_risked": round(risked, 2),
            "profit_units": round(m["profit_units"], 2),
            "roi_pct": round(roi, 2) if roi is not None else None,
            "red_month": m["profit_units"] < 0,
            "hypothetical": True,
        })
    return {"months": rows, "rejected_n": rejected,
            "unsettled_excluded_n": unsettled_n}


def summarize(records):
    """Full paper-metrics report, harness-style. Empty input is a valid
    report with n=0 — never an error, never invented numbers."""
    records = list(records or [])
    bc = beat_close(records)
    ledger = paper_ledger(records)
    total_risked = sum(m["units_risked"] for m in ledger["months"])
    total_profit = sum(m["profit_units"] for m in ledger["months"])
    return {
        "schema": SCHEMA,
        "research_only": True,
        "hypothetical": True,
        "disclaimer": ("PAPER TRACKING ONLY: no bets were placed. All figures "
                       "are hypothetical research-card tracking, never actual "
                       "results."),
        "records_evaluated": len(records),
        "beat_close": bc,
        "monthly_ledger": ledger,
        "totals": {
            "months": len(ledger["months"]),
            "red_months": sum(1 for m in ledger["months"] if m["red_month"]),
            "units_risked": round(total_risked, 2),
            "profit_units": round(total_profit, 2),
        },
    }


def to_json(report):
    return json.dumps(report, indent=2, sort_keys=True)


def to_markdown(report):
    """Markdown render. Every profit figure sits next to its units-risked
    denominator; red months are shown, not hidden."""
    r = report
    lines = [
        "# Paper tracking (HYPOTHETICAL / RESEARCH ONLY)",
        "",
        "_No bets were placed. This is paper tracking of research cards._",
        "",
        "## Beat the close",
        "",
    ]
    bc = r["beat_close"]
    if bc["status"] == "AVAILABLE":
        lines += [
            "- Records with archived close: %d" % bc["n"],
            "- Beat-close: %d/%d (%.2f%%)" % (bc["beat"], bc["n"], bc["beat_close_pct"]),
            "- CLV edge: %+.3f pp (mean close_no_vig_p − our_model_p)" % bc["clv_edge_pp"],
        ]
        if bc["missing_close_n"]:
            lines.append("- Missing closing lines (excluded, not invented): %d"
                         % bc["missing_close_n"])
        if bc["rejected_n"]:
            lines.append("- Rejected records (degenerate, excluded): %d" % bc["rejected_n"])
    else:
        lines.append("- MISSING — no archived closing lines; beat-close and CLV not computed.")
        if bc["missing_close_n"]:
            lines.append("  (%d records had no closing line)" % bc["missing_close_n"])
    lines += ["", "## Monthly ledger (paper, red months shown)", ""]
    months = r["monthly_ledger"]["months"]
    if months:
        lines.append("| month | plays | W-L-P | units risked | P/L (units) | ROI |")
        lines.append("|---|---:|---|---|---:|---:|---:|")
        for m in months:
            lines.append(
                "| %s | %d | %d-%d-%d | %.2fu | %+.2fu | %s |"
                % (m["month"], m["plays"], m["wins"], m["losses"], m["pushes"],
                   m["units_risked"], m["profit_units"],
                   ("%.2f%%" % m["roi_pct"]) if m["roi_pct"] is not None else "—"))
        t = r["totals"]
        lines.append("")
        lines.append("**Total: %+.2fu profit on %.2fu risked across %d months "
                     "(%d red).**"
                     % (t["profit_units"], t["units_risked"], t["months"], t["red_months"]))
    else:
        lines.append("No settled paper plays this period — a zero-play month is valid "
                     "output, not a gap to fill.")
    lines += ["", "_research_only: hypothetical tracking. units_risked is the denominator "
                  "for every profit figure._"]
    return "\n".join(lines)
