"""NFL props v1.1 moved-line amendment — DRAFT, not frozen.

Overlay for Part 2 (#2396) and 2B (#2415). The frozen v1 pricers/scorers are
untouched; this module consumes their scored rows plus the close capture.

Rules (owner rulings #1, 2026-10-22):
* A LINE_MOVED row goes in its own bucket with a move direction relative to
  the pick (FAVORABLE / ADVERSE / AMBIGUOUS / NO_PICK). Direction is the sign
  of the line change only: no repricing, no model, no CLV value.
* Moved rows stay in win/loss, stay out of the CLV average, and stay out of
  the 20% limit, which now counts only capture failures (NO_CLOSE_ROW,
  CLOSE_SINGLE_SIDED, CLOSE_STALE, CLOSE_NOT_PREKICKOFF).
* Co-test: one-sided exact sign test, H1 adverse > favorable, alpha 0.05.
  AMBIGUOUS counts as adverse (conservative); NO_PICK is excluded.
* Moved share > 50% of graded rows -> LOW_COVERAGE (cannot open PLAY alone).
* Forward only: every row's kickoff must be after the freeze; the freeze must
  precede Sun 2026-10-25 12:00 CT (17:00Z).
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

ALPHA = 0.05
CAPTURE_FAILURE_LIMIT = 0.20
LOW_COVERAGE_LIMIT = 0.50
FREEZE_DEADLINE = datetime(2026, 10, 25, 17, 0, 0, tzinfo=timezone.utc)
CAPTURE_FAILURE_REASONS = frozenset(
    {"NO_CLOSE_ROW", "CLOSE_SINGLE_SIDED", "CLOSE_STALE", "CLOSE_NOT_PREKICKOFF"})
CLOSE_MAX_AGE_MINUTES = 60  # frozen v1 value (Part 2 :44, 2B :55)
SAMPLE_GATES = frozenset({"INSUFFICIENT_SAMPLE", "REVIEW_NOT_OPEN"})


def _ts(s: str) -> datetime:
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError(f"timestamp without zone: {s!r}")
    return d


def move_direction(side: str, entry_line: float, close_lines) -> str:
    lines = sorted({float(x) for x in close_lines})
    if not lines or float(entry_line) in lines:
        raise ValueError("LINE_MOVED requires close lines that all differ from entry")
    if side not in ("OVER", "UNDER"):
        return "NO_PICK"
    up = all(x > entry_line for x in lines)
    down = all(x < entry_line for x in lines)
    if not (up or down):
        return "AMBIGUOUS"
    return "FAVORABLE" if (up == (side == "OVER")) else "ADVERSE"


def _two_sided(c: dict) -> bool:
    return c.get("over_price") is not None and c.get("under_price") is not None


def recheck_moved(row: dict, other_line_closes: list) -> tuple[str, str | None, dict | None]:
    """Re-check a v1 LINE_MOVED row (v1 attach_close assigns LINE_MOVED
    before its timestamp / two-sided checks). Returns (bucket, reason, info).
    A row is moved only if >=1 close at another line is two-sided,
    pre-kickoff and within CLOSE_MAX_AGE_MINUTES. Otherwise, precedence
    (best close found wins, mirroring v1's check order):
      no other-line close           -> NO_CLOSE_ROW
      none two-sided                -> CLOSE_SINGLE_SIDED
      two-sided but none pre-kickoff -> CLOSE_NOT_PREKICKOFF
      two-sided pre-kickoff, all too old -> CLOSE_STALE
    Direction uses only the final (latest captured_at) qualifying capture."""
    kickoff = _ts(row["kickoff"])
    for c in other_line_closes:
        if "captured_at" not in c or c["captured_at"] is None:
            raise ValueError(f"row {row.get('row_id')}: close without captured_at")
    if not other_line_closes:
        return "CAPTURE_FAILURE", "NO_CLOSE_ROW", None
    two = [c for c in other_line_closes if _two_sided(c)]
    if not two:
        return "CAPTURE_FAILURE", "CLOSE_SINGLE_SIDED", None
    pre = [c for c in two if _ts(c["captured_at"]) < kickoff]
    if not pre:
        return "CAPTURE_FAILURE", "CLOSE_NOT_PREKICKOFF", None
    ok = [c for c in pre
          if (kickoff - _ts(c["captured_at"])).total_seconds() <= CLOSE_MAX_AGE_MINUTES * 60]
    if not ok:
        return "CAPTURE_FAILURE", "CLOSE_STALE", None
    last = max(_ts(c["captured_at"]) for c in ok)
    final = [c for c in ok if _ts(c["captured_at"]) == last]
    return "LINE_MOVED", "LINE_MOVED", {
        "captured_at": final[0]["captured_at"], "lines": sorted({float(c["line"]) for c in final})}


def annotate_moved(rows: list, close_capture: dict) -> list:
    closes_by = {}
    for c in close_capture.get("rows", []):
        closes_by.setdefault((c["game_id"], c["player_id"], c["market"]), []).append(c)
    out = []
    for r in rows:
        o = dict(r)
        o["v11_close_captured_at"] = None
        st, reason = r.get("close_status"), r.get("clv_missing_reason")
        if st == "READABLE":
            o["v11_bucket"], o["v11_reason"], o["move_direction"] = "READABLE", None, None
        elif st == "CLV_MISSING" and reason == "LINE_MOVED":
            key = (r["game_id"], r["player_id"], r["market"])
            if any(float(c["line"]) == float(r["line"]) and _two_sided(c)
                   for c in closes_by.get(key, [])):
                raise ValueError(f"row {r.get('row_id')}: v1 LINE_MOVED but capture has a "
                                 "two-sided close at the entry line")
            others = [c for c in closes_by.get(key, []) if float(c["line"]) != float(r["line"])]
            bucket, why, info = recheck_moved(r, others)
            o["v11_bucket"], o["v11_reason"], o["clv"] = bucket, why, None
            if info:
                o["move_direction"] = move_direction(r.get("selected_side"), r["line"], info["lines"])
                o["v11_close_captured_at"] = info["captured_at"]
            else:
                o["move_direction"] = None
        elif st == "CLV_MISSING" and reason in CAPTURE_FAILURE_REASONS:
            o["v11_bucket"], o["v11_reason"], o["move_direction"] = "CAPTURE_FAILURE", reason, None
        else:
            raise ValueError(f"row {r.get('row_id')}: unclassifiable close {st}/{reason}")
        out.append(o)
    return out


def sign_test_adverse(favorable: int, adverse: int) -> dict:
    n = favorable + adverse
    p = 1.0 if n == 0 else sum(math.comb(n, k) for k in range(adverse, n + 1)) / 2 ** n
    return {"n": n, "favorable": favorable, "adverse": adverse,
            "p_value": p, "alpha": ALPHA, "rejects": p < ALPHA}


def aggregate_v11(rows: list, *, sample_gate: str | None, primary_clv_beats: bool) -> dict:
    """sample_gate: the frozen v1 sample/review gate result (None if open).
    primary_clv_beats: the frozen v1 primary CLV test (incl. 2B's QB check)
    computed over READABLE rows only."""
    if sample_gate is not None and sample_gate not in SAMPLE_GATES:
        raise ValueError(f"sample_gate must be one of {sorted(SAMPLE_GATES)} or None")
    graded = [r for r in rows if r.get("outcome") is not None]
    n = len(graded)
    moved = [r for r in graded if r["v11_bucket"] == "LINE_MOVED"]
    capfail = [r for r in graded if r["v11_bucket"] == "CAPTURE_FAILURE"]
    fav = sum(r["move_direction"] == "FAVORABLE" for r in moved)
    adv = sum(r["move_direction"] in ("ADVERSE", "AMBIGUOUS") for r in moved)
    sign = sign_test_adverse(fav, adv)
    cf_share = len(capfail) / n if n else 0.0
    mv_share = len(moved) / n if n else 0.0
    reason = None
    if sample_gate:
        verdict = sample_gate
    elif cf_share > CAPTURE_FAILURE_LIMIT:
        verdict = "INSUFFICIENT_CLOSE_DATA"
    elif sign["rejects"]:
        verdict, reason = "DOES_NOT_BEAT_MARKET", "MOVED_BUCKET_ADVERSE_SIGN_TEST"
    elif mv_share > LOW_COVERAGE_LIMIT:
        verdict = "LOW_COVERAGE"
    elif primary_clv_beats:
        verdict = "BEATS_MARKET"
    else:
        verdict = "DOES_NOT_BEAT_MARKET"
    wins = sum(r.get("selected_result") == "WIN" for r in graded)
    losses = sum(r.get("selected_result") == "LOSS" for r in graded)
    return {
        "graded_rows": n,
        "clv_rows": sum(r["v11_bucket"] == "READABLE" and r.get("clv") is not None for r in graded),
        "capture_failure_rows": len(capfail), "capture_failure_share": cf_share,
        "moved": {"rows": len(moved), "share": mv_share, "favorable": fav,
                  "adverse": sum(r["move_direction"] == "ADVERSE" for r in moved),
                  "ambiguous": sum(r["move_direction"] == "AMBIGUOUS" for r in moved),
                  "no_pick": sum(r["move_direction"] == "NO_PICK" for r in moved),
                  "adverse_for_test": adv, "sign_test": sign},
        "win_loss": {"wins": wins, "losses": losses},
        "verdict": verdict, "verdict_reason": reason,
        "play_eligible_alone": verdict == "BEATS_MARKET",
    }


def validate_freeze_ts(freeze_ts: str) -> datetime:
    f = _ts(freeze_ts)
    if f >= FREEZE_DEADLINE:
        raise ValueError("v1.1 freeze must precede 2026-10-25 12:00 CT")
    return f


def assert_forward_only(rows: list, freeze_ts: str) -> None:
    f = _ts(freeze_ts)
    for r in rows:
        if _ts(r["kickoff"]) <= f:
            raise ValueError(f"row {r['row_id']} kicked off before v1.1 freeze; it is scored under v1")
