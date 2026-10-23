"""Universal forward-validation evaluator (framework v1).

A config-driven implementation of the standing SportsEdge validation law,
generalized from the FROZEN NFL props Part 2 forward test
(research/nfl_props_part2_20261018/PREREG_NFL_PROPS_PART2_FORWARD_V1.md,
esp. §3 scoring, §4 sample-size/verdicts, §4.5 missing-close rule) and the
Capture Spec V1 close rule (docs/football/CAPTURE_SPEC_V1.md: the close is
the last capture before event start and no more than 60 minutes before it).

A family is declared by a JSON config (see configs/ and README.md): sport,
family, market keys, the frozen model-version string its priced rows must
carry, market form (TWO_SIDED or YES_ONLY), minimum graded rows, minimum
distinct events, an optional minimum-slates gate, the CLV_MISSING share cap
and the close-window length. The evaluator consumes priced entry records +
close capture records + realized outcomes and emits the standard verdict
record per market:

    BEATS_MARKET / DOES_NOT_BEAT_MARKET / INSUFFICIENT_SAMPLE /
    INSUFFICIENT_CLOSE_DATA

with CLV (primary) and its game-clustered 95% CI, win/loss (secondary),
log loss of the model vs the de-vigged entry market, calibration deciles,
and the full gate table. Verdicts are per market, never pooled.

Fail-closed refusals (ForwardValidationRefusal, named reason) — the run is
refused, never partially scored, when:
  - MODEL_VERSION_MISMATCH: a prospective priced row carries a model
    version other than the config's frozen version (every model version is
    scored AS IT STOOD when it priced; a different version is a different
    test and never enters this one's sample);
  - POST_START_RECORD: a record whose recorded_at is after its event
    start and which is not labeled HISTORICAL (records written after an
    event starts are historical by definition; an unlabeled one cannot be
    admitted as prospective, and a HISTORICAL-labeled one is excluded
    from all verdict math, only counted);
  - RECORD_MISSING_TIMESTAMP: a prospective row lacks entry_captured_at,
    event_start or recorded_at;
  - CLOSE_RECORD_MISSING_TIMESTAMP: a close record lacks captured_at;
  - DUPLICATE_PROSPECTIVE_ROW: two prospective rows share the identity
    (event, subject, market, line, model version);
  - MODEL_PROBABILITY_INVALID / PRICE_INVALID: a priced row's model
    probabilities or entry prices are missing, out of range, or (for
    two-sided markets) do not sum to 1.
  - OUTCOME_RECORD_INVALID / OUTCOME_VALUE_INVALID / OUTCOME_DUPLICATE:
    a realized-outcome record is malformed (missing event_id / market /
    value), its value is not a real finite number (bool, string, NaN,
    +/-inf, None are refused, never coerced), or two records share one
    (event, subject, market) key.

Per-row dispositions that are NOT run refusals (frozen Part 2 mechanics):
an entry captured at/after event start is excluded per row
(ENTRY_NOT_PRE_EVENT, the Part 2 runner's EXCLUDED_LATE_CAPTURE), and a
close that violates the close rule makes its row CLV_MISSING with exactly
one of the five frozen reasons (NO_CLOSE_ROW, LINE_MOVED,
CLOSE_SINGLE_SIDED, CLOSE_NOT_PREKICKOFF, CLOSE_STALE) — the row stays in
win/loss and out of the CLV average, and its close is never backfilled.

A config whose preregistration is already frozen may pin it by path +
sha256 (``prereg`` / ``prereg_sha256``); the pin is stamped on every
verdict record so a readout names the exact frozen text it was scored
under. A config may also declare ``picked_beats_passed_required``
(frozen NBA props prereg §5/§9): the verdict sample is then the
market's classified engine rows — PICKED (runner-surfaced research
candidates) and PASSED (engine-priced, not picked) — the CLV leg is
the picked rows, and BEATS_MARKET additionally requires the picked
mean CLV to exceed the passed mean CLV. See nba_props.py for that
family's §2/§5 input screening.

This module does not price anything and does not read any family's engine.
Family adapters produce the priced records; this evaluator only judges
them, exactly as score_nfl_props_part2.py judges the Part 2 runner's rows.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import stats

EPS = 1e-12
CLV_MISSING_REASONS = ("NO_CLOSE_ROW", "LINE_MOVED", "CLOSE_SINGLE_SIDED",
                       "CLOSE_NOT_PREKICKOFF", "CLOSE_STALE")
VERDICTS = ("BEATS_MARKET", "DOES_NOT_BEAT_MARKET", "INSUFFICIENT_SAMPLE",
            "INSUFFICIENT_CLOSE_DATA")


class ForwardValidationRefusal(Exception):
    """Fail-closed refusal to score. ``reason`` is the named, stable code;
    ``detail`` carries the offending row ids / values for the record."""

    def __init__(self, reason: str, detail: dict | None = None):
        self.reason = reason
        self.detail = detail or {}
        super().__init__(f"{reason}: {json.dumps(self.detail, default=str)[:400]}")


def _parse_ts(value, *, row_id: str, field_name: str) -> datetime:
    reason = ("CLOSE_RECORD_MISSING_TIMESTAMP" if field_name == "captured_at"
              else "RECORD_MISSING_TIMESTAMP")
    if value is None:
        raise ForwardValidationRefusal(
            reason, {"row_id": row_id, "field": field_name})
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("timestamp requires an explicit UTC offset")
        return parsed
    except ValueError:
        raise ForwardValidationRefusal(
            reason,
            {"row_id": row_id, "field": field_name, "value": value})


@dataclass
class FamilyConfig:
    sport: str
    family: str
    markets: list
    engine_id: str
    model_version: str
    market_form: str = "TWO_SIDED"          # TWO_SIDED | YES_ONLY
    sides: list = field(default_factory=lambda: ["OVER", "UNDER"])
    over_side: str = "OVER"                  # side that wins iff value > line
    min_rows: int = 100
    min_events: int = 40
    min_slates: int | None = None
    max_clv_missing_share: float = 0.20
    clv_beats_threshold: float = 0.0
    close_max_age_minutes: int = 60
    status: str = "DRAFT — NOT FROZEN"
    capture_scope: str = ""
    capture_note: str = ""
    prereg_draft: str = ""
    prereg: str = ""
    prereg_sha256: str = ""
    picked_beats_passed_required: bool = False
    sha256: str = ""

    def validate(self) -> None:
        if self.market_form not in ("TWO_SIDED", "YES_ONLY"):
            raise ForwardValidationRefusal(
                "CONFIG_INVALID", {"field": "market_form", "value": self.market_form})
        if self.market_form == "TWO_SIDED" and len(self.sides) != 2:
            raise ForwardValidationRefusal(
                "CONFIG_INVALID", {"field": "sides", "value": self.sides})
        if self.market_form == "YES_ONLY" and self.sides != ["YES"]:
            raise ForwardValidationRefusal(
                "CONFIG_INVALID", {"field": "sides", "value": self.sides})
        if self.over_side not in self.sides:
            raise ForwardValidationRefusal(
                "CONFIG_INVALID", {"field": "over_side", "value": self.over_side})
        if not self.markets:
            raise ForwardValidationRefusal("CONFIG_INVALID", {"field": "markets"})
        if self.min_rows < 1 or self.min_events < 1:
            raise ForwardValidationRefusal(
                "CONFIG_INVALID", {"field": "minimums",
                                   "min_rows": self.min_rows,
                                   "min_events": self.min_events})
        if self.prereg_sha256 and len(self.prereg_sha256) != 64:
            raise ForwardValidationRefusal(
                "CONFIG_INVALID", {"field": "prereg_sha256",
                                   "value": self.prereg_sha256})


def load_config(path) -> FamilyConfig:
    p = Path(path)
    raw = p.read_bytes()
    doc = json.loads(raw)
    known = {f for f in FamilyConfig.__dataclass_fields__} - {"sha256"}
    unknown = set(doc) - known
    if unknown:
        raise ForwardValidationRefusal(
            "CONFIG_INVALID", {"unknown_fields": sorted(unknown)})
    cfg = FamilyConfig(**{k: doc[k] for k in known if k in doc})
    cfg.sha256 = hashlib.sha256(raw).hexdigest()
    cfg.validate()
    return cfg


def config_from_dict(doc: dict) -> FamilyConfig:
    cfg = FamilyConfig(**{k: v for k, v in doc.items()
                          if k in FamilyConfig.__dataclass_fields__})
    cfg.sha256 = hashlib.sha256(
        json.dumps(doc, sort_keys=True).encode()).hexdigest()
    cfg.validate()
    return cfg


# --------------------------------------------------------------------------
# Record admission
# --------------------------------------------------------------------------

def _admit_rows(cfg: FamilyConfig, rows: list) -> tuple[list, dict]:
    """Partition input rows into prospective scored rows and exclusions,
    enforcing the refusal rules. Returns (prospective_rows, excluded)."""
    prospective, historical = [], []
    late_entries = []
    seen: dict = {}
    for row in rows:
        row_id = row.get("row_id") or "<no row_id>"
        label = row.get("label") or "PROSPECTIVE"
        event_start = _parse_ts(row.get("event_start"), row_id=row_id,
                                field_name="event_start")
        recorded = _parse_ts(row.get("recorded_at"), row_id=row_id,
                             field_name="recorded_at")
        if recorded > event_start and label != "HISTORICAL":
            raise ForwardValidationRefusal(
                "POST_START_RECORD",
                {"row_id": row_id, "recorded_at": row.get("recorded_at"),
                 "event_start": row.get("event_start"), "label": label})
        if label == "HISTORICAL":
            historical.append(row_id)
            continue
        if recorded > event_start:  # unreachable given the check above
            raise AssertionError("post-start admission invariant violated")
        entry_ts = _parse_ts(row.get("entry_captured_at"), row_id=row_id,
                             field_name="entry_captured_at")
        if row.get("model_version") != cfg.model_version:
            raise ForwardValidationRefusal(
                "MODEL_VERSION_MISMATCH",
                {"row_id": row_id, "found": row.get("model_version"),
                 "frozen": cfg.model_version})
        line = _finite_number(row.get("line"), reason="LINE_INVALID",
                              row_id=row_id, field="line")
        key = (row.get("event_id"), row.get("subject_id"), row.get("market"),
               line, row.get("model_version"))
        if key in seen:
            raise ForwardValidationRefusal(
                "DUPLICATE_PROSPECTIVE_ROW",
                {"row_id": row_id, "duplicates": seen[key], "key": str(key)})
        seen[key] = row_id
        _check_probabilities_and_prices(cfg, row)
        if entry_ts >= event_start:
            late_entries.append(row_id)  # Part 2: EXCLUDED_LATE_CAPTURE
            continue
        prospective.append(row)
    return prospective, {"historical_rows": historical,
                         "late_entry_rows": late_entries}


def _finite_number(value, *, reason: str, row_id: str, field: str) -> float:
    """Preserve numeric-string compatibility, but never accept bool/nonfinite."""
    try:
        if isinstance(value, bool):
            raise ValueError("boolean is not numeric evidence")
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite numeric evidence")
        return number
    except (TypeError, ValueError, OverflowError):
        raise ForwardValidationRefusal(
            reason, {"row_id": row_id, "field": field, "value": repr(value)[:200]})


def _check_price(value, *, row_id: str, field: str) -> None:
    number = _finite_number(value, reason="PRICE_INVALID", row_id=row_id, field=field)
    try:
        decimal = stats.american_to_decimal(number)
        if not math.isfinite(decimal) or decimal <= 1.0:
            raise ValueError("price cannot represent a finite payout")
    except (TypeError, ValueError, OverflowError):
        raise ForwardValidationRefusal(
            "PRICE_INVALID", {"row_id": row_id, "field": field, "value": repr(value)[:200]})


def _check_probabilities_and_prices(cfg: FamilyConfig, row: dict) -> None:
    row_id = row.get("row_id") or "<no row_id>"
    mp = row.get("model_p")
    prices = row.get("entry_prices")
    if not isinstance(mp, dict):
        raise ForwardValidationRefusal("MODEL_PROBABILITY_INVALID", {"row_id": row_id})
    if not isinstance(prices, dict):
        raise ForwardValidationRefusal("PRICE_INVALID", {"row_id": row_id})
    total = 0.0
    for side in cfg.sides:
        p = _finite_number(mp.get(side), reason="MODEL_PROBABILITY_INVALID",
                           row_id=row_id, field=f"model_p.{side}")
        valid = (0.0 < p < 1.0) if cfg.market_form == "YES_ONLY" else (0.0 <= p <= 1.0)
        if not valid:
            raise ForwardValidationRefusal(
                "MODEL_PROBABILITY_INVALID", {"row_id": row_id, "side": side})
        total += p
        _check_price(prices.get(side), row_id=row_id, field=f"entry_prices.{side}")
    if cfg.market_form == "TWO_SIDED" and abs(total - 1.0) > 1e-6:
        raise ForwardValidationRefusal(
            "MODEL_PROBABILITY_INVALID", {"row_id": row_id, "sum": total})


# --------------------------------------------------------------------------
# Close attachment — the frozen §4.5 mechanics, generalized from
# price_nfl_props_part2.attach_close (same match key, same reason order:
# single-sided is judged before the timestamp rules, as there).
# --------------------------------------------------------------------------

def _attach_close(cfg: FamilyConfig, row: dict, close_index: dict,
                  close_keys_seen: set) -> None:
    key = (row["event_id"], row.get("subject_id"), row["market"],
           float(row["line"]))
    raw = close_index.get(key)
    kickoff = _parse_ts(row["event_start"], row_id=row.get("row_id", "?"),
                        field_name="event_start")
    reason = None
    prices = (raw or {}).get("prices")
    if prices is None:
        prices = {}
    if not isinstance(prices, dict):
        raise ForwardValidationRefusal("PRICE_INVALID", {"row_id": f"close:{key}"})
    for side in cfg.sides:
        if prices.get(side) is not None:
            _check_price(prices[side], row_id=f"close:{key}", field=f"prices.{side}")
    if raw is None:
        reason = ("LINE_MOVED"
                  if (row["event_id"], row.get("subject_id"), row["market"])
                  in close_keys_seen else "NO_CLOSE_ROW")
    elif any(prices.get(side) is None for side in cfg.sides):
        reason = "CLOSE_SINGLE_SIDED"
    else:
        captured = _parse_ts(raw.get("captured_at"),
                             row_id=f"close:{key}", field_name="captured_at")
        if captured >= kickoff:
            reason = "CLOSE_NOT_PREKICKOFF"
        elif (kickoff - captured).total_seconds() > cfg.close_max_age_minutes * 60:
            reason = "CLOSE_STALE"
    if reason is None:
        row["close_status"] = "READABLE"
        row["close_prices"] = {side: prices[side] for side in cfg.sides}
        row["close_captured_at"] = raw["captured_at"]
        row["clv_missing_reason"] = None
    else:
        row["close_status"] = "CLV_MISSING"
        row["clv_missing_reason"] = reason


def _index_closes(close_rows: list) -> tuple[dict, set]:
    by_key, seen = {}, set()
    for raw in close_rows:
        if raw.get("captured_at") is None:
            raise ForwardValidationRefusal(
                "CLOSE_RECORD_MISSING_TIMESTAMP",
                {"close_row": {k: raw.get(k) for k in
                                ("event_id", "subject_id", "market", "line")}})
        line = _finite_number(raw.get("line"), reason="LINE_INVALID",
                              row_id="close", field="line")
        key = (raw["event_id"], raw.get("subject_id"), raw["market"], line)
        # Validate every supplied capture, even when it does not match an
        # entry or is overwritten by another capture of the same key.
        _parse_ts(raw["captured_at"], row_id=f"close:{key}",
                  field_name="captured_at")
        by_key[key] = raw
        seen.add((raw["event_id"], raw.get("subject_id"), raw["market"]))
    return by_key, seen


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def _selected_side(cfg: FamilyConfig, row: dict) -> str:
    """The model's selected side: higher EV at the entry prices; an exact
    tie is TIE and is excluded from win/loss and CLV (Part 2 §2/§3).
    YES_ONLY markets follow the locked anytime-TD rule: picked iff the
    model probability beats the entry Yes price's raw implied probability."""
    if cfg.market_form == "YES_ONLY":
        p = float(row["model_p"]["YES"])
        implied = stats.raw_implied(row["entry_prices"]["YES"])
        return "YES" if p > implied else "PASS"
    evs = {side: float(row["model_p"][side])
           * stats.american_to_decimal(row["entry_prices"][side]) - 1.0
           for side in cfg.sides}
    a, b = cfg.sides
    if abs(evs[a] - evs[b]) < 1e-12:
        return "TIE"
    return a if evs[a] > evs[b] else b


def _score_row(cfg: FamilyConfig, row: dict, value: float) -> dict:
    out = dict(row)
    line = float(row["line"])
    if value > line:
        outcome_side = cfg.over_side
    elif value < line:
        outcome_side = next(s for s in cfg.sides if s != cfg.over_side) \
            if cfg.market_form == "TWO_SIDED" else "NO"
    else:
        outcome_side = "PUSH"
    out["realized_value"] = value
    out["outcome_side"] = outcome_side
    sel = _selected_side(cfg, row)
    out["selected_side"] = sel
    if cfg.market_form == "YES_ONLY":
        won = (outcome_side == "YES")
        if outcome_side == "PUSH" or sel == "PASS":
            out["selected_result"] = None  # pushes graded, out of W/L
        else:
            out["selected_result"] = "WIN" if won else "LOSS"
        if sel == "YES" and row.get("close_status") == "READABLE":
            out["clv"] = float(stats.raw_implied(row["close_prices"]["YES"])
                               - stats.raw_implied(row["entry_prices"]["YES"]))
        else:
            out["clv"] = None
        p_yes = float(row["model_p"]["YES"])
        if outcome_side == "PUSH":
            out["logloss_model"] = None
            out["logloss_market_entry"] = None
            out["brier_model"] = None
            out["reference_realized"] = None
        else:
            realized = 1.0 if won else 0.0
            out["logloss_model"] = float(-math.log(min(max(p_yes if won else 1 - p_yes, EPS), 1.0)))
            imp = stats.raw_implied(row["entry_prices"]["YES"])
            out["logloss_market_entry"] = float(
                -math.log(min(max(imp if won else 1 - imp, EPS), 1.0)))
            out["brier_model"] = float((p_yes - realized) ** 2)
            out["reference_realized"] = realized
        out["p_reference"] = p_yes
        return out
    # TWO_SIDED
    if outcome_side == "PUSH" or sel == "TIE":
        out["selected_result"] = None
    else:
        out["selected_result"] = "WIN" if sel == outcome_side else "LOSS"
    entry_novig = dict(zip(cfg.sides, stats.devig_pair(
        row["entry_prices"][cfg.sides[0]], row["entry_prices"][cfg.sides[1]])))
    out["entry_novig_p"] = entry_novig
    if outcome_side != "PUSH":
        p_model = float(row["model_p"][outcome_side])
        out["logloss_model"] = float(-math.log(min(max(p_model, EPS), 1.0)))
        out["logloss_market_entry"] = float(
            -math.log(min(max(entry_novig[outcome_side], EPS), 1.0)))
        out["brier_model"] = float(sum(
            (float(row["model_p"][s]) - (1.0 if s == outcome_side else 0.0)) ** 2
            for s in cfg.sides) / len(cfg.sides))
    else:
        out["logloss_model"] = None
        out["logloss_market_entry"] = None
        out["brier_model"] = None
    if row.get("close_status") == "READABLE" and sel in cfg.sides:
        close_novig = dict(zip(cfg.sides, stats.devig_pair(
            row["close_prices"][cfg.sides[0]], row["close_prices"][cfg.sides[1]])))
        out["clv"] = float(close_novig[sel] - entry_novig[sel])
    else:
        out["clv"] = None
    out["p_reference"] = float(row["model_p"][cfg.over_side])
    out["reference_realized"] = (None if outcome_side == "PUSH"
                                  else (1.0 if outcome_side == cfg.over_side else 0.0))
    return out


CALIBRATION_MIN_ROWS = 10


def calibration_deciles(rows: list) -> list:
    """Part 2 convention: deciles of the model's reference-side probability
    vs its realized rate (pushes excluded). The last entry is the extreme
    (top) decile, reported for the overconfidence check.

    Buckets are formed over the ranked rows WITHOUT splitting a tie
    block: rows sharing one p_reference always land in the same bucket,
    even when that makes bucket sizes uneven. Rank-slicing split ties by
    input order, which made the reported per-bucket error an artifact of
    row order — a perfectly calibrated all-tied sample (p = 0.5, half
    realized) reported apparent error 0.50 in every bucket when the
    realized-0 rows happened to sort first, and 0.00 when interleaved.
    Each entry carries its bucket index and [p_min, p_max] range so the
    top bucket is identified by identity, not by list position alone.
    Below CALIBRATION_MIN_ROWS eligible rows no deciles are emitted:
    with (near-)single-row buckets every realized rate is 0 or 1 by
    construction and the apparent errors are meaningless."""
    elig = [r for r in rows if r.get("reference_realized") is not None]
    if len(elig) < CALIBRATION_MIN_ROWS:
        return []
    order = sorted(elig, key=lambda r: r["p_reference"])
    n = len(order)
    parts = []
    start = 0
    for k in range(10):
        end = (k + 1) * n // 10
        while 0 < end < n and order[end]["p_reference"] == order[end - 1]["p_reference"]:
            end += 1
        if end > start:
            parts.append(order[start:end])
            start = end
        if start >= n:
            break
    out = []
    for idx, part in enumerate(parts):
        ps = [r["p_reference"] for r in part]
        out.append({
            "bucket": idx,
            "p_min": float(min(ps)),
            "p_max": float(max(ps)),
            "mean_p": float(sum(ps) / len(part)),
            "realized_rate": float(sum(r["reference_realized"] for r in part) / len(part)),
            "n": len(part)})
    return out


def _crps_summary(graded: list) -> dict:
    """CRPS candidate-vs-baseline over the MATCHED cohort only: the rows
    carrying BOTH fields. The two means previously ran over
    independently filtered row sets, so they could describe different
    games while reading as a like-for-like comparison, with no counts
    reported to reveal it. ``crps_paired_delta`` is the mean of the
    per-row (candidate - baseline) differences over the same matched
    rows (negative favors the candidate)."""
    matched = [r for r in graded
               if r.get("crps_candidate") is not None
               and r.get("crps_baseline") is not None]
    if not matched:
        return {"crps_candidate": None, "crps_baseline": None,
                "crps_n_matched": 0, "crps_paired_delta": None}
    cand = [float(r["crps_candidate"]) for r in matched]
    base = [float(r["crps_baseline"]) for r in matched]
    return {
        "crps_candidate": float(sum(cand) / len(cand)),
        "crps_baseline": float(sum(base) / len(base)),
        "crps_n_matched": len(matched),
        "crps_paired_delta": float(
            sum(c - b for c, b in zip(cand, base)) / len(matched)),
    }


def _index_outcomes(outcomes: list) -> dict:
    """Validate and index realized outcomes by (event, subject, market).

    Outcomes are unguarded external data: a value that is not a real,
    finite number (bool, string, NaN, +/-inf, None) is REFUSED, never
    coerced — bare float() coercion previously let "27" score, let NaN
    fall through both comparisons and silently score as a PUSH (the row
    vanished from win/loss, log loss and calibration), and let inf score
    as a win. A record missing event_id / market / value is refused
    instead of raising a raw KeyError/TypeError mid-run, and duplicate
    records for one key are refused instead of silently overwriting
    (last-wins). Per-market scale rules (integrality, non-negativity)
    belong to adapters/configs above this floor."""
    realized = {}
    for o in outcomes:
        if not isinstance(o, dict) or "event_id" not in o \
                or "market" not in o or "value" not in o:
            raise ForwardValidationRefusal(
                "OUTCOME_RECORD_INVALID", {"outcome": repr(o)[:200]})
        key = (o["event_id"], o.get("subject_id"), o["market"])
        value = o["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ForwardValidationRefusal(
                "OUTCOME_VALUE_INVALID", {"key": key, "value": repr(value)})
        try:
            finite = math.isfinite(value)
            fvalue = float(value)
        except OverflowError:
            # An int too large to represent as a float (reachable from
            # JSON, which parses arbitrary-precision integers) is refused
            # by name, never a raw OverflowError mid-run.
            raise ForwardValidationRefusal(
                "OUTCOME_VALUE_INVALID", {"key": key, "value": repr(value)})
        if not finite:
            raise ForwardValidationRefusal(
                "OUTCOME_VALUE_INVALID", {"key": key, "value": repr(value)})
        if key in realized:
            raise ForwardValidationRefusal("OUTCOME_DUPLICATE", {"key": key})
        realized[key] = fvalue
    return realized


def _verdict(cfg: FamilyConfig, *, sample_rows: int, distinct_events: int,
             slates_completed: int | None, clv_missing_share: float,
             clv_ci_lo: float | None,
             picked_beats_passed: bool | None = None) -> tuple[str, dict]:
    gates = {
        "min_rows": {"required": cfg.min_rows, "actual": sample_rows,
                     "pass": sample_rows >= cfg.min_rows},
        "min_events": {"required": cfg.min_events, "actual": distinct_events,
                       "pass": distinct_events >= cfg.min_events},
    }
    if cfg.min_slates is not None:
        gates["min_slates"] = {
            "required": cfg.min_slates, "actual": slates_completed,
            "pass": slates_completed is not None
                    and slates_completed >= cfg.min_slates}
    if not gates["min_rows"]["pass"] or not gates["min_events"]["pass"] \
            or (cfg.min_slates is not None and not gates["min_slates"]["pass"]):
        return "INSUFFICIENT_SAMPLE", gates
    if clv_missing_share > cfg.max_clv_missing_share:
        return "INSUFFICIENT_CLOSE_DATA", gates
    if clv_ci_lo is not None and clv_ci_lo > cfg.clv_beats_threshold \
            and picked_beats_passed is not False:
        return "BEATS_MARKET", gates
    return "DOES_NOT_BEAT_MARKET", gates


def evaluate_family(cfg: FamilyConfig, entry_rows: list, close_rows: list,
                    outcomes: list, *, slates_completed: int | None = None) -> dict:
    """Score one family's priced records. ``outcomes`` is a list of
    {"event_id", "subject_id", "market", "value"} realized values on the
    config's line scale (the over_side wins iff value > line). Returns the
    verdict record with one entry per market in the config. Raises
    ForwardValidationRefusal on any fail-closed condition."""
    prospective, excluded = _admit_rows(cfg, entry_rows)
    close_index, close_seen = _index_closes(close_rows)
    realized = _index_outcomes(outcomes)
    record = {
        "label": "FORWARD VALIDATION — verdict record (framework v1; "
                 "rules generalized from frozen NFL props Part 2 §3–§4)",
        "sport": cfg.sport, "family": cfg.family,
        "engine_id": cfg.engine_id, "model_version": cfg.model_version,
        "config_status": cfg.status, "config_sha256": cfg.sha256,
        "prereg": cfg.prereg, "prereg_sha256": cfg.prereg_sha256,
        "market_form": cfg.market_form,
        "excluded": {**excluded, "unscored_rows": []},
        "markets": {},
    }
    for market in cfg.markets:
        mrows = [r for r in prospective if r["market"] == market]
        scored, unscored = [], []
        for row in mrows:
            key = (row["event_id"], row.get("subject_id"), market)
            if key not in realized:
                unscored.append(row.get("row_id"))
                continue
            row = dict(row)
            _attach_close(cfg, row, close_index, close_seen)
            scored.append(_score_row(cfg, row, realized[key]))
        record["excluded"]["unscored_rows"].extend(unscored)
        record["markets"][market] = _aggregate_market(
            cfg, scored, slates_completed=slates_completed)
    return record


def _runner_disposition(row: dict) -> str | None:
    """The runner's picked/passed stamp on a priced row, for configs that
    declare ``picked_beats_passed_required`` (frozen NBA props prereg §5).
    PICKED = the runner surfaced the row as a research candidate
    (``RESEARCH_CANDIDATE_NOT_VALIDATED`` in the pricing lane's own
    vocabulary); PASSED = engine-priced but not surfaced
    (``PRICED_RESEARCH``). A row may carry the stamp either as an explicit
    ``disposition`` field or as the lane's ``status`` field. Anything else
    is unclassified — never guessed."""
    d = str(row.get("disposition") or "").upper()
    if d in ("PICKED", "PASSED"):
        return d
    status = str(row.get("status") or "")
    if status == "RESEARCH_CANDIDATE_NOT_VALIDATED":
        return "PICKED"
    if status == "PRICED_RESEARCH":
        return "PASSED"
    return None


def _aggregate_market(cfg: FamilyConfig, graded: list, *,
                      slates_completed: int | None) -> dict:
    if cfg.picked_beats_passed_required and cfg.market_form == "TWO_SIDED":
        return _aggregate_market_picked_passed(
            cfg, graded, slates_completed=slates_completed)
    if cfg.market_form == "YES_ONLY":
        sample = [r for r in graded if r["selected_side"] == "YES"]
    else:
        sample = graded
    clv_rows = [r for r in sample if r.get("clv") is not None]
    missing = [r for r in sample if r.get("close_status") == "CLV_MISSING"]
    n_sample = len(sample)
    share_missing = (len(missing) / n_sample) if n_sample else 0.0
    clv_stats = None
    if clv_rows:
        s = stats.boot([r["clv"] for r in clv_rows],
                       [r["event_id"] for r in clv_rows])  # clustered by event
        clv_stats = {"mean": s["mean"], "ci95_lo": s["ci95_lo"],
                     "ci95_hi": s["ci95_hi"], "n": s["n"],
                     "n_events_clustered": s["n_blocks"]}
    distinct_events = len({r["event_id"] for r in sample})
    verdict, gates = _verdict(
        cfg, sample_rows=n_sample, distinct_events=distinct_events,
        slates_completed=slates_completed, clv_missing_share=share_missing,
        clv_ci_lo=(clv_stats["ci95_lo"] if clv_stats else None))
    wins = sum(1 for r in graded if r.get("selected_result") == "WIN")
    losses = sum(1 for r in graded if r.get("selected_result") == "LOSS")
    pushes = sum(1 for r in graded if r.get("outcome_side") == "PUSH")
    ll = [r for r in graded if r.get("logloss_model") is not None]
    return {
        "verdict": verdict,
        "gates": gates,
        "graded_rows": len(graded),
        "verdict_sample_rows": n_sample,
        "distinct_events": distinct_events,
        "distinct_events_all_graded": len({r["event_id"] for r in graded}),
        "slates_completed": slates_completed,
        "clv_missing_rows": len(missing),
        "clv_missing_share": share_missing,
        "clv_missing_by_reason": {
            reason: sum(1 for r in missing
                        if (r.get("clv_missing_reason") or "UNSPECIFIED") == reason)
            for reason in sorted({r.get("clv_missing_reason") or "UNSPECIFIED"
                                  for r in missing})},
        "clv": clv_stats,
        "win_loss": {"wins": wins, "losses": losses, "pushes": pushes,
                     "win_rate_ex_pushes": (wins / (wins + losses))
                     if (wins + losses) else None},
        "logloss_model": (float(sum(r["logloss_model"] for r in ll) / len(ll))
                          if ll else None),
        "logloss_market_entry": (float(sum(r["logloss_market_entry"] for r in ll) / len(ll))
                                 if ll else None),
        "brier_model": (float(sum(r["brier_model"] for r in ll) / len(ll))
                        if ll else None),
        **_crps_summary(graded),
        "calibration_deciles": calibration_deciles(graded),
        "rows": graded,
    }


def _aggregate_market_picked_passed(cfg: FamilyConfig, graded: list, *,
                                    slates_completed: int | None) -> dict:
    """Picked/passed verdict mode (frozen NBA props prereg §5/§9; opt-in
    via ``picked_beats_passed_required``, TWO_SIDED only).

    The verdict sample is the market's classified engine rows: PICKED
    (the runner surfaced the row as a research candidate) and PASSED
    (engine-priced, not picked). The §4 gates and the §8 CLV_MISSING
    share bind on that sample. CLV (§6) is the per-row selected-side CLV
    the generic path computes; the §9 CLV leg is the PICKED rows' mean
    with its game-clustered 95% CI, and BEATS_MARKET additionally
    requires the picked mean CLV to exceed the passed mean CLV —
    beating only one of the market or the model's own passes is not
    beating the market. Rows with no runner disposition are reported
    unclassified and enter no denominator. Win/loss, log loss, Brier
    and the calibration deciles remain over ALL graded rows (the §9
    calibration leg covers picked and passed alike)."""
    picked, passed, unclassified = [], [], []
    for r in graded:
        d = _runner_disposition(r)
        if d == "PICKED":
            picked.append(r)
        elif d == "PASSED":
            passed.append(r)
        else:
            unclassified.append(r.get("row_id"))
    sample = picked + passed
    missing = [r for r in sample if r.get("close_status") == "CLV_MISSING"]
    n_sample = len(sample)
    share_missing = (len(missing) / n_sample) if n_sample else 0.0
    picked_clv_rows = [r for r in picked if r.get("clv") is not None]
    clv_stats = None
    if picked_clv_rows:
        s = stats.boot([r["clv"] for r in picked_clv_rows],
                       [r["event_id"] for r in picked_clv_rows])
        clv_stats = {"mean": s["mean"], "ci95_lo": s["ci95_lo"],
                     "ci95_hi": s["ci95_hi"], "n": s["n"],
                     "n_events_clustered": s["n_blocks"]}
    passed_clv_rows = [r for r in passed if r.get("clv") is not None]
    passed_clv = None
    if passed_clv_rows:
        passed_clv = {
            "mean": float(sum(r["clv"] for r in passed_clv_rows)
                          / len(passed_clv_rows)),
            "n": len(passed_clv_rows)}
    picked_beats_passed = bool(
        clv_stats is not None and passed_clv is not None
        and clv_stats["mean"] > passed_clv["mean"])
    distinct_events = len({r["event_id"] for r in sample})
    verdict, gates = _verdict(
        cfg, sample_rows=n_sample, distinct_events=distinct_events,
        slates_completed=slates_completed, clv_missing_share=share_missing,
        clv_ci_lo=(clv_stats["ci95_lo"] if clv_stats else None),
        picked_beats_passed=picked_beats_passed)
    wins = sum(1 for r in graded if r.get("selected_result") == "WIN")
    losses = sum(1 for r in graded if r.get("selected_result") == "LOSS")
    pushes = sum(1 for r in graded if r.get("outcome_side") == "PUSH")
    ll = [r for r in graded if r.get("logloss_model") is not None]
    return {
        "verdict": verdict,
        "gates": gates,
        "graded_rows": len(graded),
        "verdict_sample_rows": n_sample,
        "picked_rows": len(picked),
        "passed_rows": len(passed),
        "unclassified_rows": unclassified,
        "distinct_events": distinct_events,
        "distinct_events_all_graded": len({r["event_id"] for r in graded}),
        "slates_completed": slates_completed,
        "clv_missing_rows": len(missing),
        "clv_missing_share": share_missing,
        "clv_missing_by_reason": {
            reason: sum(1 for r in missing
                        if (r.get("clv_missing_reason") or "UNSPECIFIED") == reason)
            for reason in sorted({r.get("clv_missing_reason") or "UNSPECIFIED"
                                  for r in missing})},
        "clv": clv_stats,
        "clv_passed": passed_clv,
        "picked_beats_passed": picked_beats_passed,
        "win_loss": {"wins": wins, "losses": losses, "pushes": pushes,
                     "win_rate_ex_pushes": (wins / (wins + losses))
                     if (wins + losses) else None},
        "logloss_model": (float(sum(r["logloss_model"] for r in ll) / len(ll))
                          if ll else None),
        "logloss_market_entry": (float(sum(r["logloss_market_entry"] for r in ll) / len(ll))
                                 if ll else None),
        "brier_model": (float(sum(r["brier_model"] for r in ll) / len(ll))
                        if ll else None),
        **_crps_summary(graded),
        "calibration_deciles": calibration_deciles(graded),
        "rows": graded,
    }
