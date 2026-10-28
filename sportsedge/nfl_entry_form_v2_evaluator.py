"""NFL_ENTRY_FORM_V2 — evaluator adapter (DESIGN stage; NOT FROZEN).

The family adapter PREREG_DRAFT §7.6 requires. It implements, for
diagnostics on NON-COUNTED records:

- the Oct 22 v1.1 close rule carried in unchanged (PREREG_DRAFT §8),
  with the five frozen reason codes (``NO_CLOSE_ROW``, ``LINE_MOVED``,
  ``CLOSE_SINGLE_SIDED``, ``CLOSE_NOT_PREKICKOFF``, ``CLOSE_STALE``)
  assigned in the shared forward evaluator's order (existence ->
  single-sided -> not-pre-kickoff -> stale; a close is readable only at
  the entry line, with both prices, captured before kickoff and no more
  than 60 minutes before it — Part 2 prereg §4.5 mechanics);
- the moved bucket with direction recorded from the picked side's
  perspective under the pinned v1.1 convention (NBA team-totals
  evaluator §6c: OVER is FAVORABLE when the line moved up, UNDER when it
  moved down; generalized here to SPREAD as HOME up / AWAY down —
  favorable = the close moved toward the picked side), the second
  verdict test's exact one-sided sign test, the 20%
  INSUFFICIENT_CLOSE_DATA trip counting ONLY true capture failures
  (``LINE_MOVED`` never counts toward it), and the LOW_COVERAGE label
  when moved rows exceed 50% of a market's graded picks;
- primary CLV on same-line (READABLE) pick rows, in the shared forward
  evaluator's units: no-vig probability of the selected side at the
  close minus at entry (``forward_validation.core`` _score_row);
- the §6 kill instrumentation: accuracy kill (§6.3: at >= 40 priced
  games, construction MAE exceeding the close's MAE by > 1.0 pt),
  calibration kill (§6.1), CLV kill (§6.2). These are INSTRUMENTS only —
  they report flags on non-counted diagnostics and stop nothing.

COUNTING IS REFUSED. No freeze exists for this family (PREREG_DRAFT is a
draft; §7's checklist is unexecuted), so every counted-evaluation entry
point raises :class:`EFV2FreezeNotAuthorized` with the named refusal
``EF_V2_FREEZE_NOT_AUTHORIZED``. There is no caller-controlled bypass:
the refusal is governed by the module-level ``FREEZE_PIN``, which only
a freeze act (a separate prospective PR pinning the frozen prereg,
construction, constants, and this adapter per §7) may set. Diagnostics
grade rows for accuracy/CLV readout only (DESIGN §4.3: PASS rows are
"graded for accuracy/CLV diagnostics, never a pick"); every diagnostics
output is stamped ``counted = False`` / NON_COUNTED.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Dict, Optional, Sequence

FREEZE_PIN: Optional[dict] = None  # set only by a freeze act (PREREG §7)

REFUSAL = "EF_V2_FREEZE_NOT_AUTHORIZED"

CLOSE_MAX_AGE_S = 3600.0        # Part 2 §4.5: close no more than 60 min pre-kickoff
TRUE_FAILURE_REASONS = ("NO_CLOSE_ROW", "CLOSE_SINGLE_SIDED",
                        "CLOSE_NOT_PREKICKOFF", "CLOSE_STALE")
TRIP_SHARE = 0.20               # PREREG §8 rule 3 / §6.4
LOW_COVERAGE_SHARE = 0.50       # PREREG §8 rule 4
ACCURACY_KILL_MIN_GAMES = 40    # PREREG §6.3
ACCURACY_KILL_GAP = 1.0         # PREREG §6.3
CALIBRATION_KILL_MIN_PICKS = 25     # PREREG §6.1
CALIBRATION_KILL_TOP_BAND_P = 0.58  # PREREG §6.1 (top stated band)
CALIBRATION_KILL_TOP_MIN = 15       # PREREG §6.1
CLV_KILL_MIN_PICKS = 30             # PREREG §6.2
# PREREG §6.2 states the CLV kill as "mean same-line CLV <= -0.50 pts".
# CLV in this program is carried in no-vig probability units (shared
# forward evaluator), so "pts" is read as probability points: -0.0050.
# Flagged for the freeze package to pin explicitly; the value is used
# only by this non-counted instrumentation until then.
CLV_KILL_THRESHOLD = -0.005
COVERAGE_KILL_MIN_PICKS = 25        # PREREG §6.4

BANDS = ((0.0, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 5.0), (5.0, math.inf))


class EFV2FreezeNotAuthorized(Exception):
    """Named fail-closed refusal (PREREG_DRAFT §7.6): counted evaluation
    attempted against an unfrozen construction."""

    reason = REFUSAL

    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(f"{REFUSAL}: {detail}" if detail else REFUSAL)


class EFV2AdapterError(ValueError):
    """Input-contract violation in diagnostics inputs (not a close
    disposition; the five frozen codes are never invented around)."""


def _require_freeze() -> None:
    if FREEZE_PIN is None:
        raise EFV2FreezeNotAuthorized(
            "NFL_ENTRY_FORM_V2 is DESIGN ONLY — no freeze act has pinned "
            "the preregistration, construction, constants, and evaluator "
            "per PREREG_DRAFT §7; counted evaluation is refused.")


# ---------------------------------------------------------------------------
# Counted entry points — refused until a freeze act pins this family.
# ---------------------------------------------------------------------------

def count_rows(rows: Sequence[dict]) -> list:
    """Count priced rows toward the validation sample. REFUSED."""
    _require_freeze()
    raise AssertionError("unreachable: a freeze pin must route via the "
                         "pinned shared evaluator, not this adapter")


def score_counted(rows: Sequence[dict], closes: Sequence[dict],
                  results: Dict[str, dict], kickoffs: Dict[str, str]) -> dict:
    """Produce a counted score/verdict sample. REFUSED."""
    _require_freeze()
    raise AssertionError("unreachable: a freeze pin must route via the "
                         "pinned shared evaluator, not this adapter")


def verdict(rows: Sequence[dict], closes: Sequence[dict],
            results: Dict[str, dict], kickoffs: Dict[str, str]) -> dict:
    """Issue a §5 verdict. REFUSED (no verdict exists before a freeze,
    and the verdict review is a separate governed act even then)."""
    _require_freeze()
    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Shared-evaluator-identical price math (forward_validation.stats).
# ---------------------------------------------------------------------------

def _raw_implied(price: float) -> float:
    price = float(price)
    if price < 0:
        return (-price) / ((-price) + 100.0)
    return 100.0 / (price + 100.0)


def _devig_pair(price_a: float, price_b: float) -> tuple:
    ra, rb = _raw_implied(price_a), _raw_implied(price_b)
    s = ra + rb
    return ra / s, rb / s


def _parse_ts(value: str, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise EFV2AdapterError(f"{field}: missing timestamp")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        raise EFV2AdapterError(f"{field}: unparseable timestamp {value!r}")
    if ts.tzinfo is None:
        raise EFV2AdapterError(f"{field}: timestamp lacks a timezone {value!r}")
    return ts.astimezone(timezone.utc)


def sign_test_p(adverse: int, n: int) -> Optional[float]:
    """One-sided exact sign test P(X >= adverse | n, 1/2); None if n == 0.
    Identical to the pinned NBA team-totals evaluator's sign_test_p."""
    if n == 0:
        return None
    return sum(math.comb(n, i) for i in range(adverse, n + 1)) / 2.0 ** n


def _ca_trend_p(ns: Sequence[float], covers: Sequence[float],
                scores: Sequence[float]) -> float:
    """One-sided Cochran-Armitage trend p (normal approx), H1 increasing —
    the design screen's formula (SCREEN_RESULTS §3 method)."""
    n_tot = float(sum(ns))
    if n_tot == 0:
        return 1.0
    p = float(sum(covers)) / n_tot
    xbar = sum(n * s for n, s in zip(ns, scores)) / n_tot
    num = sum(s * (c - n * p) for n, c, s in zip(ns, covers, scores))
    var = p * (1 - p) * sum(n * (s - xbar) ** 2 for n, s in zip(ns, scores))
    if var <= 0:
        return 1.0
    z = num / math.sqrt(var)
    return 0.5 * (1 - math.erf(z / math.sqrt(2)))


# ---------------------------------------------------------------------------
# Close attachment — PREREG §8 (v1.1), shared-evaluator order.
# ---------------------------------------------------------------------------

def move_direction(market: str, side: str, entry_line: float,
                   close_line: float) -> str:
    """Direction of a line move from the picked side's perspective
    (pinned v1.1 convention; see module docstring)."""
    up = close_line > entry_line
    favorable_if_up = (side in ("OVER", "HOME"))
    return "FAVORABLE" if up == favorable_if_up else "ADVERSE"


def _sides(market: str) -> tuple:
    return ("HOME", "AWAY") if market == "SPREAD" else ("OVER", "UNDER")


def attach_close(row: dict, event_closes: Sequence[dict],
                 kickoff: datetime) -> dict:
    """Assign exactly one close disposition to a priced row.

    ``event_closes`` are every close snapshot for the row's game+market.
    Returns the disposition fields to merge into the graded row."""
    entry_line = float(row["entry_line"])
    out: dict = {"close_status": None, "close_line": None,
                 "close_prices": None, "moved_direction": None, "clv": None}
    if not event_closes:
        out["close_status"] = "NO_CLOSE_ROW"
        return out
    same = [c for c in event_closes if float(c["line"]) == entry_line]
    if not same:
        latest = max(event_closes,
                     key=lambda c: _parse_ts(c["captured_at"], "close"))
        out["close_status"] = "LINE_MOVED"
        out["close_line"] = float(latest["line"])
        side = row["selected_side"] if row["decision"] == "PICK" \
            else row["preferred_side"]
        out["moved_direction"] = move_direction(
            row["market"], side, entry_line, float(latest["line"]))
        return out
    close = max(same, key=lambda c: _parse_ts(c["captured_at"], "close"))
    first, second = _sides(row["market"])
    prices = close.get("prices") or {}
    if prices.get(first) is None or prices.get(second) is None:
        out["close_status"] = "CLOSE_SINGLE_SIDED"
        return out
    captured = _parse_ts(close["captured_at"], "close")
    if captured >= kickoff:
        out["close_status"] = "CLOSE_NOT_PREKICKOFF"
        return out
    if (kickoff - captured).total_seconds() > CLOSE_MAX_AGE_S:
        out["close_status"] = "CLOSE_STALE"
        return out
    out["close_status"] = "READABLE"
    out["close_line"] = float(close["line"])
    out["close_prices"] = {first: prices[first], second: prices[second]}
    if row["decision"] == "PICK":
        sel = row["selected_side"]
        e_first, _ = _devig_pair(row["entry_prices"][first],
                                 row["entry_prices"][second])
        c_first, _ = _devig_pair(prices[first], prices[second])
        entry_novig = e_first if sel == first else 1.0 - e_first
        close_novig = c_first if sel == first else 1.0 - c_first
        out["clv"] = close_novig - entry_novig
    return out


# ---------------------------------------------------------------------------
# Settlement + diagnostics (NON_COUNTED)
# ---------------------------------------------------------------------------

def _actuals(market: str, result: dict) -> float:
    if market == "SPREAD":
        return float(result["home_score"]) - float(result["away_score"])
    return float(result["home_score"]) + float(result["away_score"])


def _side_wins(market: str, side: str, actual: float, line: float) -> Optional[bool]:
    """True = the side covers, False = it does not, None = push."""
    diff = actual - line
    if diff == 0:
        return None
    if market == "SPREAD":
        return diff > 0 if side == "HOME" else diff < 0
    return diff > 0 if side == "OVER" else diff < 0


def _pick_return(price: int, won: Optional[bool]) -> Optional[float]:
    if won is None:
        return None
    if not won:
        return -1.0
    price = float(price)
    return (100.0 / (-price)) if price < 0 else (price / 100.0)


def grade_records(rows: Sequence[dict], closes: Sequence[dict],
                  results: Dict[str, dict],
                  kickoffs: Dict[str, str]) -> dict:
    """Grade priced records into NON_COUNTED diagnostics.

    ``closes``: close snapshots {game_id, market, line, prices,
    captured_at}. ``results``: {game_id: {home_score, away_score}}.
    ``kickoffs``: {game_id: ISO timestamp}. Win/loss follows the v1.1
    rule that a LINE_MOVED row stays in win/loss at its ENTRY line and
    is never repriced (PREREG §8 rule 1)."""
    closes_by_key: Dict[tuple, list] = {}
    for c in closes:
        closes_by_key.setdefault((c["game_id"], c["market"]), []).append(c)
    graded = []
    for row in rows:
        out = dict(row)
        kickoff = _parse_ts(kickoffs[row["game_id"]], "kickoff")
        out.update(attach_close(
            row, closes_by_key.get((row["game_id"], row["market"]), []),
            kickoff))
        result = results.get(row["game_id"])
        if result is None:
            out["settlement"] = "RESULT_UNAVAILABLE"
            out["outcome"] = None
        else:
            actual = _actuals(row["market"], result)
            out["actual"] = actual
            out["settlement"] = "GRADED"
            side = row["selected_side"] if row["decision"] == "PICK" \
                else row["preferred_side"]
            won = _side_wins(row["market"], side, actual, float(row["entry_line"]))
            out["preferred_won"] = won
            if row["decision"] == "PICK":
                out["outcome"] = ("PUSH" if won is None
                                  else "WIN" if won else "LOSS")
                out["return_units"] = _pick_return(row["picked_price"], won)
            else:
                out["outcome"] = None
        graded.append(out)
    return {"family": "NFL_ENTRY_FORM_V2", "counted": False,
            "label": "NON_COUNTED — diagnostics only; counting refused "
                     "with EF_V2_FREEZE_NOT_AUTHORIZED (no freeze)",
            "rows": graded,
            "markets": {m: _market_diagnostics(
                [r for r in graded if r["market"] == m]) for m in
                ("SPREAD", "TOTAL")}}


def _market_diagnostics(rows: Sequence[dict]) -> dict:
    picks = [r for r in rows if r["decision"] == "PICK"]
    graded_picks = [r for r in picks if r.get("settlement") == "GRADED"]
    clv_rows = [r for r in graded_picks if r.get("clv") is not None]
    moved = [r for r in graded_picks if r["close_status"] == "LINE_MOVED"]
    adverse = sum(1 for r in moved if r["moved_direction"] == "ADVERSE")
    favorable = len(moved) - adverse
    failures = [r for r in graded_picks
                if r["close_status"] in TRUE_FAILURE_REASONS]
    failure_share = (len(failures) / len(graded_picks)) if graded_picks else 0.0
    moved_share = (len(moved) / len(graded_picks)) if graded_picks else 0.0

    # Accuracy instrumentation (PREREG §6.3): all priced rows with a
    # result and a known close line (READABLE or LINE_MOVED).
    acc = [r for r in rows if r.get("settlement") == "GRADED"
           and r.get("close_line") is not None]
    if acc:
        mae_model = sum(abs(r["actual"] - r["projection"]) for r in acc) / len(acc)
        mae_close = sum(abs(r["actual"] - r["close_line"]) for r in acc) / len(acc)
        gap = mae_model - mae_close
    else:
        mae_model = mae_close = gap = None
    accuracy_kill = {
        "n_priced_games": len(acc),
        "mae_model": mae_model, "mae_close": mae_close, "gap": gap,
        "evaluated": len(acc) >= ACCURACY_KILL_MIN_GAMES,
        "fired": (len(acc) >= ACCURACY_KILL_MIN_GAMES and gap is not None
                  and gap > ACCURACY_KILL_GAP),
    }

    # Calibration-kill instrumentation (PREREG §6.1).
    top = [r for r in graded_picks if r["p_stated"] >= CALIBRATION_KILL_TOP_BAND_P]
    top_decided = [r for r in top if r["outcome"] in ("WIN", "LOSS")]
    if len(graded_picks) >= CALIBRATION_KILL_MIN_PICKS and len(top) >= CALIBRATION_KILL_TOP_MIN \
            and top_decided:
        cover = sum(1 for r in top_decided if r["outcome"] == "WIN") / len(top_decided)
        breakeven = sum(_raw_implied(r["picked_price"]) for r in top_decided) \
            / len(top_decided)
        cal_fired = cover < breakeven
    else:
        cover = breakeven = None
        cal_fired = False
    calibration_kill = {
        "n_graded_picks": len(graded_picks), "n_top_band": len(top),
        "top_cover": cover, "top_breakeven": breakeven,
        "evaluated": cover is not None, "fired": cal_fired,
    }

    # CLV-kill instrumentation (PREREG §6.2).
    mean_clv = (sum(r["clv"] for r in clv_rows) / len(clv_rows)) if clv_rows else None
    clv_kill = {
        "n_clv_rows": len(clv_rows), "mean_clv": mean_clv,
        "evaluated": len(graded_picks) >= CLV_KILL_MIN_PICKS and mean_clv is not None,
        "fired": (len(graded_picks) >= CLV_KILL_MIN_PICKS and mean_clv is not None
                  and mean_clv <= CLV_KILL_THRESHOLD),
    }

    returns = [r["return_units"] for r in graded_picks
               if r.get("return_units") is not None]
    wins = sum(1 for r in graded_picks if r["outcome"] == "WIN")
    losses = sum(1 for r in graded_picks if r["outcome"] == "LOSS")
    pushes = sum(1 for r in graded_picks if r["outcome"] == "PUSH")

    # §5.4 band table over all priced rows (picks + passes), preferred
    # side, pushes excluded from the cover denominator.
    band_rows = []
    ns, cv = [], []
    decided_rows = [r for r in rows if r.get("settlement") == "GRADED"]
    for lo, hi in BANDS:
        band = [r for r in decided_rows if lo <= abs(r["d"]) < hi]
        decided = [r for r in band if r.get("preferred_won") is not None]
        w = sum(1 for r in decided if r["preferred_won"])
        band_rows.append({
            "band": f"{lo:g}-{hi:g}" if math.isfinite(hi) else f"{lo:g}+",
            "n": len(band), "n_decided": len(decided),
            "mean_stated_p": (sum(r["p_stated"] for r in band) / len(band))
                             if band else None,
            "realized_cover": (w / len(decided)) if decided else None})
        ns.append(len(decided))
        cv.append(w)

    return {
        "counted": False,
        "n_priced": len(rows), "n_picks": len(picks),
        "n_graded_picks": len(graded_picks),
        "record": {"win": wins, "loss": losses, "push": pushes},
        "roi": (sum(returns) / len(returns)) if returns else None,
        "clv": {"n": len(clv_rows), "mean": mean_clv},
        "moved": {"n": len(moved), "favorable": favorable, "adverse": adverse,
                  "sign_test_p_adverse": sign_test_p(adverse, len(moved))},
        "close_failures": {
            "n": len(failures), "share_of_graded_picks": failure_share,
            "by_reason": {reason: sum(1 for r in failures
                                      if r["close_status"] == reason)
                          for reason in TRUE_FAILURE_REASONS},
            "trip_20pct": failure_share > TRIP_SHARE,
            "coverage_kill_fired": (len(graded_picks) >= COVERAGE_KILL_MIN_PICKS
                                    and failure_share > TRIP_SHARE)},
        "low_coverage": moved_share > LOW_COVERAGE_SHARE,
        "moved_share_of_graded_picks": moved_share,
        "accuracy_kill": accuracy_kill,
        "calibration_kill": calibration_kill,
        "clv_kill": clv_kill,
        "bands": band_rows,
        "band_trend_p": _ca_trend_p(ns, cv, [0, 1, 2, 3, 4]),
    }
