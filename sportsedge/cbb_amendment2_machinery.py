"""Amendment 2 counted machinery for the two CBB Torvik families.

Amendment 2 to the CBB freeze packages (adopted Oct 30, 2026;
research/nba_cbb_activation_20261028/AMENDMENT_2_DRAFT.md, sha256
25be46029ca1933e1a2eb7d7aa6a858928f3879a254285e90a0b9bf1270d926a,
adoption record AMENDMENT_2_ADOPTION_RECORD.md in the same
directory) supplied the three terms the packages' PREREG_FINAL
section 8 recorded as blocking gaps G-1 / G-2 / G-3:

  * G-1 (its section 1): the pick rule -- gap and designated side
    per row, pick thresholds SPREAD 2.2 / TOTAL 3.5 / TEAM_TOTAL
    2.1, CLV on the designated side over PICKED rows with a valid
    same-line close, ROI at flat 1-unit stakes over the PICKED
    set, and the committed per-row record.
  * G-2 (its section 2): the accuracy leg's interval -- paired
    candidate-minus-baseline absolute error per market, game-
    cluster bootstrap, 10,000 resamples, seed 20261028, two-sided
    percentile interval at level 1 - alpha/k (alpha = 0.05;
    k computed at the freeze act and again at the verdict, the
    larger governs), nearest-rank bounds. The accuracy row set is
    close-independent: every priced row with a verified final.
  * G-3 (its section 3): close validity (the lane's FINAL
    capture; exists, two-sided, before tip, no more than 60:00
    before tip -- exactly 60:00 valid -- checked before any
    moved classification), the moved-row bucket (one-sided exact
    sign test at alpha/k; more than 50% of PICKED rows moved
    yields INSUFFICIENT_CLOSE_DATA), one disposition code per
    priced row, and the more-than-20% missing-close limit whose
    breach makes the review's outcome INSUFFICIENT_CLOSE_DATA.

This module is that machinery, shared by both families
(CBB_TORVIK_EFFICIENCY_V1 spread/total and its team-totals
readout). The efficiency family's market leg reads on ONE POOLED
picked set across SPREAD and TOTAL (adoption Flag 1); its
accuracy leg stays per market. The arithmetic mirrors the
amendment's own toy-slate computability proof
(verify_amendment2_toy_slate.py, pinned in the adoption record)
operation for operation, so the proof's published quantities
reproduce exactly through this module (asserted in
tests/test_cbb_amendment2_machinery.py).

STATE: this module changes no family state. Both families remain
NOT FROZEN; the runners wire run_forward_test to
evaluate_forward_test behind their FREEZE_STATE, so every counted
entry point keeps refusing NOT_FROZEN until a freeze act flips
the state. evaluate_forward_test additionally enforces the
review discipline of the preregistrations (section 5 verdict /
amendment section 4): the review happens ONCE, at the first
slate close with >= 40 distinct graded games, both legs read
together, no re-review absent a new preregistration, and NO
interim looks -- before the gate is met it returns operational
counts only (rows, dispositions, graded games), never accuracy,
CLV, or ROI figures.

Input contracts (fail-closed; a malformed record is a refusal,
never a partial score):

  * priced records are the forward runners' record dicts. The
    machinery recomputes gap / designated side / classification
    from (market, model value, entry line) -- the record's own
    stamps are cross-checked, never trusted: a record stamped by
    a pre-Amendment-2 build (PICK_RULE_UNDEFINED) or with a
    disagreeing classification refuses ROW_CLASSIFICATION_MISMATCH.
    For SPREAD, the record's line is the away spread as captured
    (side A's line, the shared intake parser's convention), which
    IS the market-implied margin M_mkt of amendment section 1.1:
    gap = model margin - line.
  * finals map espn_event_id -> {"home_points", "away_points"}
    with an optional "void" flag (the runners' settle_records
    input shape; the settlement source of amendment section 1.4).
  * closes map row_id -> the game's FINAL capture for that row's
    market as ONE mapping {"line", "side_a_price",
    "side_b_price", "captured_at"} (a CBB close is a single
    captured body carrying both sides, amendment section 3.1, so
    there is one capture timestamp, not a per-side pair). Side A
    is the record's side_a (AWAY for SPREAD, OVER otherwise). A
    structurally malformed close (non-numeric line or price,
    unparseable timestamp) refuses CLOSE_RECORD_INVALID; a close
    with a missing side price is the named CLOSE_SINGLE_SIDED
    disposition, not a refusal.

Disposition precedence (one code per priced row, amendment
section 3.3): VOID, RESULT_UNAVAILABLE, then the section 3.1
close failures in check order (NO_CLOSE_ROW, CLOSE_SINGLE_SIDED,
CLOSE_NOT_PREKICKOFF, CLOSE_STALE), then LINE_MOVED, GAP_ZERO,
PUSH, and VALID_SAME_LINE for a settled row with a valid
same-line close. Two readings the amendment leaves implicit are
taken here and flagged for the build's review: (1) the
more-than-20% missing-close share is computed over the family's
priced rows that enter the test -- VOID and RESULT_UNAVAILABLE
rows are excluded from numerator and denominator alike, per
section 1.4's "excluded from every leg"; GAP_ZERO rows remain in
the denominator and count in the numerator when their close
factually fails. (2) When both the section 3.3 share and the
section 3.2 moved-row rule 1 trip, the recorded review outcome
is INSUFFICIENT_CLOSE_DATA (section 3.3 names the recorded
outcome) with the market leg still reported failed on rule 1.
"""

from __future__ import annotations

import math
import random
from datetime import timedelta

from sportsedge.cbb_torvik_efficiency_v1 import (
    CbbForwardError,
    no_vig_pair,
    parse_ts,
    price_ok,
)

AMENDMENT_2_SHA256 = (
    "25be46029ca1933e1a2eb7d7aa6a858928f3879a254285e90a0b9bf1270d926a")

PICK_RULE_ID = "AMENDMENT_2_S1_PICK_RULE"
INTERVAL_CONSTRUCTION_ID = (
    "AMENDMENT_2_S2_GAME_CLUSTER_BOOTSTRAP_10000_SEED_20261028")
CLOSE_RULE_ID = "AMENDMENT_2_S3_CLOSE_VALIDITY"

ALPHA = 0.05
BOOTSTRAP_RESAMPLES = 10000
BOOTSTRAP_SEED = 20261028
PICK_THRESHOLDS = {"SPREAD": 2.2, "TOTAL": 3.5, "TEAM_TOTAL": 2.1}
CLOSE_MAX_AGE = timedelta(minutes=60)
MAX_MISSING_CLOSE_SHARE = 0.2
MIN_GRADED_GAMES = 40

CLASSIFICATIONS = ("PICKED", "PASSED", "GAP_ZERO")
CLOSE_FAILURE_CODES = (
    "NO_CLOSE_ROW", "CLOSE_SINGLE_SIDED", "CLOSE_NOT_PREKICKOFF",
    "CLOSE_STALE")
DECLARED_DISPOSITION_CODES = frozenset({
    "VALID_SAME_LINE", "LINE_MOVED", "VOID", "RESULT_UNAVAILABLE",
    "GAP_ZERO", "PUSH", *CLOSE_FAILURE_CODES})

_SIDES = {
    "SPREAD": ("HOME", "AWAY"),       # gap > 0 -> HOME, gap < 0 -> AWAY
    "TOTAL": ("OVER", "UNDER"),
    "TEAM_TOTAL": ("OVER", "UNDER"),
}


# ------------------------------------------------------------------
# Section 1 -- gap, designated side, pick classification.
# ------------------------------------------------------------------

def designate_pick(market: str, model_value: float,
                   entry_line: float) -> dict:
    """Amendment section 1.1/1.2 for one priced row.

    gap = model value - market value, in the model's own units:
    SPREAD compares the model's expected margin (home - away) to
    the market-implied margin (the captured away spread, side
    A's line); TOTAL and TEAM_TOTAL compare the model's expected
    total / team points to the entry line. A row with gap == 0
    has no designated side (GAP_ZERO); a row is PICKED on its
    designated side when |gap| meets the market threshold.
    """
    if market not in PICK_THRESHOLDS:
        raise CbbForwardError("MARKET_UNSUPPORTED",
                              f"no Amendment 2 pick rule for {market!r}")
    gap = float(model_value) - float(entry_line)
    threshold = PICK_THRESHOLDS[market]
    if gap == 0.0:
        return {"gap": gap, "designated_side": None,
                "classification": "GAP_ZERO", "threshold": threshold}
    positive_side, negative_side = _SIDES[market]
    side = positive_side if gap > 0 else negative_side
    classification = "PICKED" if abs(gap) >= threshold else "PASSED"
    return {"gap": gap, "designated_side": side,
            "classification": classification, "threshold": threshold}


def profit_units(price: float, result: str) -> float:
    """Net units on a flat 1-unit stake (amendment section 1.4):
    win pays the entry price's profit, loss -1, push 0."""
    if result == "PUSH":
        return 0.0
    if result == "LOSS":
        return -1.0
    price = float(price)
    return (100.0 / -price) if price < 0 else (price / 100.0)


def settle_pick(market: str, designated_side: str, entry_line: float,
                home_points: float, away_points: float) -> str:
    """WIN / LOSS / PUSH for a designated side against the final
    score, settled on the ENTRY line (amendment section 1.4;
    overtime included in the final as supplied)."""
    if market == "SPREAD":
        margin = home_points - away_points
        diff = (margin - entry_line if designated_side == "HOME"
                else entry_line - margin)
    elif market == "TOTAL":
        total = home_points + away_points
        diff = (total - entry_line if designated_side == "OVER"
                else entry_line - total)
    elif market == "TEAM_TOTAL":
        points = home_points  # caller passes the subject team's points
        diff = (points - entry_line if designated_side == "OVER"
                else entry_line - points)
    else:
        raise CbbForwardError("MARKET_UNSUPPORTED",
                              f"no settlement for {market!r}")
    return "WIN" if diff > 0 else ("PUSH" if diff == 0 else "LOSS")


# ------------------------------------------------------------------
# Section 3 -- close validity and moved classification.
# ------------------------------------------------------------------

def classify_close(record: dict, close, tip) -> dict:
    """The section 3.1 validity checks, in order, before any moved
    classification. Returns {"state", "close_line",
    "moved_direction"}: state is VALID (same line), LINE_MOVED,
    or one of CLOSE_FAILURE_CODES; moved_direction is FAVORABLE /
    ADVERSE for a PICKED row's moved close, else None."""
    if close is None:
        return {"state": "NO_CLOSE_ROW", "close_line": None,
                "moved_direction": None}
    if not isinstance(close, dict):
        raise CbbForwardError(
            "CLOSE_RECORD_INVALID",
            f"close for {record.get('row_id')} is not a mapping")
    line = close.get("line")
    if isinstance(line, bool) or not isinstance(line, (int, float)) \
            or not math.isfinite(float(line)):
        raise CbbForwardError(
            "CLOSE_RECORD_INVALID",
            f"close for {record.get('row_id')} carries no numeric line")
    price_a, price_b = close.get("side_a_price"), close.get("side_b_price")
    if price_a is None or price_b is None:
        return {"state": "CLOSE_SINGLE_SIDED",
                "close_line": float(line), "moved_direction": None}
    if not price_ok(price_a) or not price_ok(price_b):
        raise CbbForwardError(
            "CLOSE_RECORD_INVALID",
            f"close for {record.get('row_id')} carries an invalid price")
    captured = parse_ts(close.get("captured_at"))
    if captured is None or captured.tzinfo is None:
        raise CbbForwardError(
            "CLOSE_RECORD_INVALID",
            f"close for {record.get('row_id')} carries no parseable "
            "capture timestamp")
    if captured >= tip:
        return {"state": "CLOSE_NOT_PREKICKOFF",
                "close_line": float(line), "moved_direction": None}
    if tip - captured > CLOSE_MAX_AGE:
        return {"state": "CLOSE_STALE", "close_line": float(line),
                "moved_direction": None}
    entry_line = float(record["line"])
    if float(line) != entry_line:
        direction = None
        designation = designate_pick(record["market"],
                                     _model_value(record), entry_line)
        side = designation["designated_side"]
        if designation["classification"] == "PICKED" and side is not None:
            if record["market"] == "SPREAD":
                toward = float(line) > entry_line   # M_mkt rose -> HOME
                favorable = toward if side == "HOME" else not toward
            else:
                toward = float(line) > entry_line   # line rose -> OVER
                favorable = toward if side == "OVER" else not toward
            direction = "FAVORABLE" if favorable else "ADVERSE"
        return {"state": "LINE_MOVED", "close_line": float(line),
                "moved_direction": direction}
    return {"state": "VALID", "close_line": float(line),
            "moved_direction": None}


# ------------------------------------------------------------------
# Section 2 -- game-cluster bootstrap and the sign test.
# ------------------------------------------------------------------

def cluster_bootstrap_ci(clusters: list, *, k: int,
                         seed: int = BOOTSTRAP_SEED,
                         reps: int = BOOTSTRAP_RESAMPLES,
                         alpha: float = ALPHA) -> dict:
    """Game-cluster bootstrap of the mean paired difference.

    ``clusters`` is one list of paired differences per game (all
    of a game's rows of the market travel together). Each
    resample draws len(clusters) games with replacement and
    averages all differences of the drawn games. Two-sided
    percentile interval at level 1 - alpha/k, bounds the
    ceil(q*B)-th order statistics (nearest-rank), q = (alpha/k)/2
    and 1 - (alpha/k)/2. Operation order mirrors the amendment's
    toy-slate proof exactly, so its published intervals reproduce
    bit-for-bit under the pinned seed.
    """
    rng = random.Random(seed)
    n = len(clusters)
    stats = []
    for _ in range(reps):
        tot, cnt = 0.0, 0
        for _ in range(n):
            c = clusters[rng.randrange(n)]
            tot += sum(c)
            cnt += len(c)
        stats.append(tot / cnt)
    stats.sort()
    level = 1 - alpha / k
    q_lo = (1 - level) / 2
    lo = stats[max(0, math.ceil(q_lo * reps) - 1)]
    hi = stats[min(reps - 1, math.ceil((1 - q_lo) * reps) - 1)]
    point = sum(sum(c) for c in clusters) / sum(len(c) for c in clusters)
    return {"point": point, "ci_lower": lo, "ci_upper": hi,
            "level": level, "reps": reps, "seed": seed, "k": k,
            "ci_upper_below_zero": hi < 0}


def sign_test_p(adverse: int, favorable: int) -> float:
    """One-sided exact sign test: P(X >= adverse), X ~ Bin(m, 0.5),
    m = adverse + favorable (amendment section 3.2 rule 1)."""
    m = adverse + favorable
    if m == 0:
        return 1.0
    return sum(math.comb(m, x) for x in range(adverse, m + 1)) / (2 ** m)


# ------------------------------------------------------------------
# Record extraction / validation.
# ------------------------------------------------------------------

def _strict_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _model_value(record: dict) -> float:
    market = record["market"]
    if market == "SPREAD":
        return record["model_margin_home_candidate"]
    if market == "TOTAL":
        return record["model_total_candidate"]
    return record["model_team_points_candidate"]


def _baseline_value(record: dict) -> float:
    market = record["market"]
    if market == "SPREAD":
        return record["model_margin_home_baseline_simple"]
    if market == "TOTAL":
        return record["model_total_baseline_simple"]
    return record["model_team_points_baseline_simple"]


def _entry_prob(record: dict, side: str) -> float:
    """The record's committed entry no-vig probability for a side."""
    if "no_vig_prob_side_a" in record:
        return (record["no_vig_prob_side_a"]
                if side == record["side_a"]
                else record["no_vig_prob_side_b"])
    return (record["no_vig_prob_over"] if side == "OVER"
            else record["no_vig_prob_under"])


def _entry_price(record: dict, side: str) -> float:
    return (record["side_a_price"] if side == record["side_a"]
            else record["side_b_price"])


def _prepare_row(record: dict, finals: dict, closes: dict) -> dict:
    """Validate one priced record and enrich it with its gap,
    designation, settlement state, factual close state, and its
    single disposition code."""
    if not isinstance(record, dict):
        raise CbbForwardError("ROW_RECORD_INVALID",
                              "priced row is not a mapping")
    row_id = record.get("row_id")
    market = record.get("market")
    if not row_id or market not in PICK_THRESHOLDS:
        raise CbbForwardError(
            "ROW_RECORD_INVALID",
            f"row {row_id!r} lacks row_id or a supported market")
    if "disposition" in record and \
            record["disposition"] not in DECLARED_DISPOSITION_CODES:
        raise CbbForwardError(
            "UNDECLARED_REFUSAL_CODE",
            f"row {row_id} carries undeclared disposition "
            f"{record['disposition']!r}")
    model = _strict_number(_model_value(record))
    baseline = _strict_number(_baseline_value(record))
    line = _strict_number(record.get("line"))
    if model is None or baseline is None or line is None:
        raise CbbForwardError(
            "ROW_RECORD_INVALID",
            f"row {row_id} carries a non-numeric model/baseline/line")
    if not price_ok(record.get("side_a_price")) \
            or not price_ok(record.get("side_b_price")):
        raise CbbForwardError(
            "ROW_RECORD_INVALID",
            f"row {row_id} carries an invalid entry price")
    prob_keys = (("no_vig_prob_side_a", "no_vig_prob_side_b")
                 if "no_vig_prob_side_a" in record
                 else ("no_vig_prob_over", "no_vig_prob_under"))
    if any(_strict_number(record.get(key)) is None
           for key in prob_keys):
        raise CbbForwardError(
            "ROW_RECORD_INVALID",
            f"row {row_id} lacks its committed entry no-vig "
            "probabilities (amendment section 1.5)")
    tip = parse_ts(record.get("tip_utc"))
    if tip is None or tip.tzinfo is None:
        raise CbbForwardError(
            "ROW_RECORD_INVALID",
            f"row {row_id} carries no parseable tip timestamp")
    if market == "TEAM_TOTAL" and record.get("venue") not in (
            "HOME", "AWAY"):
        raise CbbForwardError(
            "ROW_RECORD_INVALID",
            f"row {row_id} lacks a HOME/AWAY venue; the subject "
            "team's points cannot be read without it")
    designation = designate_pick(market, model, line)
    stamped = record.get("classification")
    if stamped is not None and stamped != designation["classification"]:
        raise CbbForwardError(
            "ROW_CLASSIFICATION_MISMATCH",
            f"row {row_id} is stamped {stamped!r} but the Amendment 2 "
            f"pick rule computes {designation['classification']!r}")
    final = finals.get(record.get("espn_event_id"))
    if final is None:
        settlement = "RESULT_UNAVAILABLE"
        home_points = away_points = None
    elif not isinstance(final, dict):
        raise CbbForwardError(
            "OUTCOME_RECORD_INVALID",
            f"final for {record.get('espn_event_id')} is not a mapping")
    elif final.get("void"):
        settlement = "VOID"
        home_points = away_points = None
    else:
        home_points = _strict_number(final.get("home_points"))
        away_points = _strict_number(final.get("away_points"))
        if home_points is None or away_points is None:
            raise CbbForwardError(
                "OUTCOME_RECORD_INVALID",
                f"final for {record.get('espn_event_id')} carries "
                "non-numeric points")
        settlement = "GRADED"
    close_info = classify_close(record, closes.get(row_id), tip)
    pick_result = None
    if settlement == "GRADED" \
            and designation["classification"] == "PICKED":
        subject = (home_points if record.get("venue") == "HOME"
                   else away_points) if market == "TEAM_TOTAL" else None
        pick_result = settle_pick(
            market, designation["designated_side"], line,
            subject if subject is not None else home_points,
            away_points)
    if settlement == "VOID":
        disposition = "VOID"
    elif settlement == "RESULT_UNAVAILABLE":
        disposition = "RESULT_UNAVAILABLE"
    elif close_info["state"] in CLOSE_FAILURE_CODES:
        disposition = close_info["state"]
    elif close_info["state"] == "LINE_MOVED":
        disposition = "LINE_MOVED"
    elif designation["classification"] == "GAP_ZERO":
        disposition = "GAP_ZERO"
    elif pick_result == "PUSH":
        disposition = "PUSH"
    else:
        disposition = "VALID_SAME_LINE"
    return {
        "row_id": row_id, "espn_event_id": record.get("espn_event_id"),
        "market": market, "record": record, "tip": tip,
        "model_value": model, "baseline_value": baseline, "line": line,
        "gap": designation["gap"],
        "designated_side": designation["designated_side"],
        "classification": designation["classification"],
        "settlement": settlement, "home_points": home_points,
        "away_points": away_points, "close_state": close_info["state"],
        "close_line": close_info["close_line"],
        "moved_direction": close_info["moved_direction"],
        "pick_result": pick_result, "disposition": disposition,
    }


# ------------------------------------------------------------------
# The review computation (sections 1-3 quantities + verdict).
# ------------------------------------------------------------------

def _disposition_counts(prepared: list) -> dict:
    counts: dict = {}
    for row in prepared:
        counts[row["disposition"]] = counts.get(row["disposition"], 0) + 1
    return counts


def compute_review_quantities(records: list, finals: dict,
                              closes: dict, *, k: int) -> dict:
    """Every leg quantity the amendment defines, computed once.

    This is the computability core the toy-slate proof exercises;
    the review gate and the one-review discipline live in
    evaluate_forward_test, which calls this only when the review
    is due. k is the governing multiple-testing count (the larger
    of the freeze-act and verdict computations, resolved by the
    caller).
    """
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise CbbForwardError("K_INVALID", f"k must be a positive "
                              f"integer, got {k!r}")
    row_ids = [r.get("row_id") if isinstance(r, dict) else None
               for r in records]
    if len(set(row_ids)) != len(row_ids):
        raise CbbForwardError(
            "DUPLICATE_ROW_ID",
            "two priced records share a row id; a duplicated row "
            "would be double-counted in every leg")
    prepared = [_prepare_row(r, finals, closes) for r in records]

    # --- section 3.3 insufficiency share (factual close states over
    # the rows that enter the test; see the module docstring).
    share_rows = [r for r in prepared
                  if r["settlement"] not in ("VOID", "RESULT_UNAVAILABLE")]
    missing = [r for r in share_rows
               if r["close_state"] in CLOSE_FAILURE_CODES]
    missing_share = (len(missing) / len(share_rows)) if share_rows else 0.0
    per_market_missing = {}
    for market in PICK_THRESHOLDS:
        rows_m = [r for r in share_rows if r["market"] == market]
        if rows_m:
            per_market_missing[market] = {
                "rows": len(rows_m),
                "missing_close_rows": sum(
                    1 for r in rows_m
                    if r["close_state"] in CLOSE_FAILURE_CODES),
                "missing_close_share": sum(
                    1 for r in rows_m
                    if r["close_state"] in CLOSE_FAILURE_CODES)
                / len(rows_m)}
    insufficient_share = missing_share > MAX_MISSING_CLOSE_SHARE

    picked = [r for r in prepared
              if r["classification"] == "PICKED"
              and r["settlement"] == "GRADED"]

    # --- section 1.4 ROI over the PICKED set (pushes in the
    # denominator; an empty set leaves ROI undefined).
    roi = None
    if picked:
        roi = sum(profit_units(_entry_price(r["record"],
                                            r["designated_side"]),
                               r["pick_result"])
                  for r in picked) / len(picked)

    # --- section 1.3 CLV over PICKED rows with a valid same-line
    # close (pooled across the family's markets -- Flag 1).
    clv_values = []
    for r in picked:
        if r["close_state"] != "VALID":
            continue
        close = closes[r["row_id"]]
        prob_close_a, prob_close_b = no_vig_pair(close["side_a_price"],
                                                 close["side_b_price"])
        prob_close = (prob_close_a
                      if r["designated_side"] == r["record"]["side_a"]
                      else prob_close_b)
        clv_values.append(
            prob_close - _entry_prob(r["record"], r["designated_side"]))
    mean_clv = (sum(clv_values) / len(clv_values)) if clv_values else None

    # --- section 3.2 moved-row bucket (read before the leg verdicts).
    moved_picked = [r for r in picked if r["close_state"] == "LINE_MOVED"]
    adverse = sum(1 for r in moved_picked
                  if r["moved_direction"] == "ADVERSE")
    favorable = sum(1 for r in moved_picked
                    if r["moved_direction"] == "FAVORABLE")
    p_value = sign_test_p(adverse, favorable) if moved_picked else None
    rule1 = bool(moved_picked) and p_value < ALPHA / k
    rule2 = bool(picked) and len(moved_picked) / len(picked) > 0.5

    market_leg_pass = (
        roi is not None and mean_clv is not None
        and roi > 0 and mean_clv > 0 and not rule1)
    market_leg = {
        "picked_rows": len(picked),
        "roi_on_picked": roi,
        "mean_clv_picked_same_line": mean_clv,
        "clv_rows": len(clv_values),
        "pushes": sum(1 for r in picked if r["pick_result"] == "PUSH"),
        "moved_picked_rows": len(moved_picked),
        "moved_adverse": adverse, "moved_favorable": favorable,
        "moved_sign_test_p": p_value,
        "moved_rule1_market_leg_fails": rule1,
        "moved_rule2_insufficient_close_data": rule2,
        "market_leg_pass": market_leg_pass,
    }

    # --- section 2 accuracy leg: per market, paired differences
    # clustered by game over every priced row with a verified
    # final (close-independent row set).
    accuracy = {}
    accuracy_pass = True
    for market in ("SPREAD", "TOTAL", "TEAM_TOTAL"):
        rows_m = [r for r in prepared if r["market"] == market
                  and r["settlement"] == "GRADED"]
        if not rows_m:
            continue
        clusters: dict = {}
        for r in rows_m:
            if market == "SPREAD":
                actual = r["home_points"] - r["away_points"]
            elif market == "TOTAL":
                actual = r["home_points"] + r["away_points"]
            else:
                actual = (r["home_points"]
                          if r["record"].get("venue") == "HOME"
                          else r["away_points"])
            diff = (abs(r["model_value"] - actual)
                    - abs(r["baseline_value"] - actual))
            clusters.setdefault(r["espn_event_id"], []).append(diff)
        ci = cluster_bootstrap_ci(list(clusters.values()), k=k)
        accuracy[market] = {
            "rows": len(rows_m), "games": len(clusters),
            "mean_paired_difference": ci["point"],
            "ci_lower": ci["ci_lower"], "ci_upper": ci["ci_upper"],
            "ci_level": ci["level"], "reps": ci["reps"],
            "seed": ci["seed"],
            "accuracy_leg_pass": ci["ci_upper_below_zero"]}
        accuracy_pass = accuracy_pass and ci["ci_upper_below_zero"]
    markets_present = {r["market"] for r in prepared}
    if any(m not in accuracy for m in markets_present):
        accuracy_pass = False     # a named market has no graded rows

    if insufficient_share or rule2:
        verdict = "INSUFFICIENT_CLOSE_DATA"
    elif accuracy_pass and market_leg_pass:
        verdict = "PASS"
    else:
        verdict = "FAIL"
    return {
        "k": k, "alpha": ALPHA,
        "rows_priced": len(prepared),
        "dispositions": _disposition_counts(prepared),
        "graded_games": len({r["espn_event_id"] for r in prepared
                             if r["settlement"] == "GRADED"}),
        "gap_zero_rows": sum(1 for r in prepared
                             if r["classification"] == "GAP_ZERO"),
        "passed_rows": sum(1 for r in prepared
                           if r["classification"] == "PASSED"),
        "missing_close_rows": len(missing),
        "missing_close_share": missing_share,
        "missing_close_share_by_market": per_market_missing,
        "insufficient_close_data_share": insufficient_share,
        "accuracy": accuracy, "accuracy_leg_pass": accuracy_pass,
        "market_leg": market_leg, "verdict": verdict,
    }


# ------------------------------------------------------------------
# The gated review (preregistration section 5 + amendment
# section 4 discipline).
# ------------------------------------------------------------------

def evaluate_forward_test(records: list, finals: dict, closes: dict,
                          *, family_id: str, k_at_freeze=None,
                          k_at_verdict: int,
                          review_already_recorded: bool = False,
                          missing_offer: list | None = None) -> dict:
    """The family's one verdict review, gated.

    Refuses VERDICT_REVIEW_ALREADY_RECORDED when a review was
    already recorded for the family (no re-review absent a new
    preregistration). Before the first slate close with >= 40
    distinct graded games, returns REVIEW_NOT_DUE with operational
    counts only -- no accuracy, CLV, or ROI figures are computed
    or returned (no interim looks). At the gate, computes the full
    review with k = max(k at the freeze act, k at the verdict).
    """
    if review_already_recorded:
        raise CbbForwardError(
            "VERDICT_REVIEW_ALREADY_RECORDED",
            "the family's single review already happened; a "
            "re-review requires a new preregistration")
    candidates = [k_at_verdict] + ([k_at_freeze]
                                    if k_at_freeze is not None else [])
    for value in candidates:
        if not isinstance(value, int) or isinstance(value, bool) \
                or value < 1:
            raise CbbForwardError("K_INVALID",
                                  f"k must be a positive integer, "
                                  f"got {value!r}")
    k = max(candidates)
    prepared = [_prepare_row(r, finals, closes) for r in records]
    graded_games = len({r["espn_event_id"] for r in prepared
                        if r["settlement"] == "GRADED"})
    base = {
        "family_id": family_id,
        "pick_rule": PICK_RULE_ID,
        "interval_construction": INTERVAL_CONSTRUCTION_ID,
        "close_rule": CLOSE_RULE_ID,
        "amendment_2_sha256": AMENDMENT_2_SHA256,
        "k": k, "graded_games": graded_games,
        "min_graded_games": MIN_GRADED_GAMES,
        "rows_priced": len(prepared),
        "dispositions": _disposition_counts(prepared),
        "missing_offer": list(missing_offer or []),
    }
    if graded_games < MIN_GRADED_GAMES:
        return {**base, "review_status": "REVIEW_NOT_DUE",
                "verdict": None}
    quantities = compute_review_quantities(records, finals, closes, k=k)
    return {**base, "review_status": "REVIEW_RECORDED",
            "accuracy": quantities["accuracy"],
            "accuracy_leg_pass": quantities["accuracy_leg_pass"],
            "market_leg": quantities["market_leg"],
            "missing_close_rows": quantities["missing_close_rows"],
            "missing_close_share": quantities["missing_close_share"],
            "missing_close_share_by_market":
                quantities["missing_close_share_by_market"],
            "insufficient_close_data_share":
                quantities["insufficient_close_data_share"],
            "verdict": quantities["verdict"]}


__all__ = [
    "ALPHA",
    "AMENDMENT_2_SHA256",
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "CLASSIFICATIONS",
    "CLOSE_FAILURE_CODES",
    "CLOSE_MAX_AGE",
    "CLOSE_RULE_ID",
    "DECLARED_DISPOSITION_CODES",
    "INTERVAL_CONSTRUCTION_ID",
    "MAX_MISSING_CLOSE_SHARE",
    "MIN_GRADED_GAMES",
    "PICK_RULE_ID",
    "PICK_THRESHOLDS",
    "classify_close",
    "cluster_bootstrap_ci",
    "compute_review_quantities",
    "designate_pick",
    "evaluate_forward_test",
    "profit_units",
    "settle_pick",
    "sign_test_p",
]
