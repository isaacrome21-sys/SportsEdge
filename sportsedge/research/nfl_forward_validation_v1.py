"""Forward-validation harness for NFL_FORWARD_VALIDATION_DESIGN_V1.

Implements the *machinery* of the filed design
(``~/workspace/sportsedge/nfl_forward_validation_design_20261013/DESIGN.md``,
Oct 13 2026): capture-record intake validation under the strict paired-quote
contract, expected-vs-actual leg accounting with the section 3.1 watchdog
states, verdict threshold logic for the game leg and the prop leg, and the
section 3.3 two-slate dry-run proof.

ACTIVATION IS OFF. Owner ruling (Isaac, Oct 13 2026): implementation and
synthetic testing ONLY. This build:

* contains no network fetcher, no scheduler hook, and no code path that can
  consume real captured data as evidence;
* runs campaigns in DRY_RUN mode only, against records whose declared origin
  is ``SYNTHETIC`` — a record declaring any other origin is refused at
  intake with a named reason;
* refuses to open an evidence campaign by construction (the G2 attempt-2
  go/no-go ledger pattern): :func:`open_evidence_campaign` requires an
  owner activation approval artifact naming scope, legs, and freeze SHA
  (design section 4.1) at
  ``config/research/nfl_forward_validation_activation_v1.json``. No such
  artifact exists, creating one is an owner action outside this
  implementation, and even if one appeared this build still refuses
  (``FORWARD_VALIDATION_ACTIVATION_NOT_IMPLEMENTED_IN_THIS_BUILD``);
* stamps every dry-run record, refusal, and output ``DRY_RUN_NOT_EVIDENCE``
  and carries ``activation_state: ACTIVATION_OFF`` on every verdict or
  readout surface. Dry-run results are never evidence about the model and
  are never pooled with any cohort (design section 3.3).

Nothing here prices anything, promotes anything, or lifts any hold. The
Lane A promotion HOLD and the forward-capture activation HOLDs remain
exactly as they are.

Contract summary (design sections 1.2 / 2.3, Appendix A — verbatim):

* pair validity: same book (DraftKings), same event, same market, same
  line; each side carries its OWN captured-at timestamp (a price asserted
  as a field on the other side's row is not a quote —
  ``OPPOSITE_PRICE_NOT_A_TIMESTAMPED_QUOTE``); |side1 - side2| <= 120 s;
  each side <= 180 s old at pair assembly; both sides strictly before
  kickoff; a price of exactly -100 on either side refuses the pair.
* closing classification: the later side's timestamp within the final
  30 minutes before kickoff and before kickoff. An earlier pair is a
  pregame snapshot — admissible as a decision record, never as closing
  evidence.
* game-leg verdict target: n >= 300 games AND >= 20 week blocks, per
  family; one extension to n = 600 under the same freeze.
* prop-leg verdict: n >= 300 player-games AND >= 15 weeks, per family;
  150 <= n < 300 permits a provisional readout labeled
  ``PROVISIONAL_UNDERPOWERED`` with no verdict language.
* watchdog states (section 3.1): SATISFIED / REFUSED /
  MISSED_OR_BLOCKED / INDETERMINATE. A missed capture is NEVER backfilled;
  INDETERMINATE is terminal and is never silently converted.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import isfinite, log
from pathlib import Path
import random
from typing import Any, Mapping, Sequence

from sportsedge.devig import DevigError, multiplicative_devig, power_devig

DESIGN_ID = "NFL_FORWARD_VALIDATION_DESIGN_V1"
ACTIVATION_STATE = "ACTIVATION_OFF"
ACTIVATION_APPROVAL_PATH = Path(
    "config/research/nfl_forward_validation_activation_v1.json")
DRY_RUN_STAMP = "DRY_RUN_NOT_EVIDENCE"
ACCRUAL_LABEL = "ACCRUAL_ONLY_NOT_A_VERDICT"
PROVISIONAL_LABEL = "PROVISIONAL_UNDERPOWERED"
ML_TIE_DISCLOSURE = "ML_TIE_MASS_ZERO_KNOWN_DEFECT"

# --- Predeclared constants (design Appendix A, verbatim) -------------------
PAIR_SKEW_MAX_SECONDS = 120
QUOTE_FRESHNESS_MAX_SECONDS = 180
CLOSING_FINAL_WINDOW_SECONDS = 30 * 60
DECISION_WINDOW_SECONDS = (120 * 60, 45 * 60)   # T-120 min .. T-45 min
CLOSING_TARGET_WINDOW_SECONDS = (20 * 60, 2 * 60)  # T-20 min .. T-2 min
RECONCILE_GRACE = timedelta(minutes=15)
GAME_LEG_TARGET_GAMES = 300
GAME_LEG_TARGET_WEEK_BLOCKS = 20
GAME_LEG_EXTENSION_GAMES = 600
PROP_LEG_PROVISIONAL_MIN = 150
PROP_LEG_TARGET_PLAYER_GAMES = 300
PROP_LEG_TARGET_WEEKS = 15
PROP_LEG_EXTENSION_PLAYER_GAMES = 600
BOOTSTRAP_REPS = 10_000
BOOTSTRAP_SEED = 20261013  # placeholder: the seed is predeclared at lock time
COVERAGE_DISCLOSURE_BELOW = 0.90
COVERAGE_INCONCLUSIVE_BELOW = 0.75
REQUIRED_BOOK = "DraftKings"

GAME_FAMILIES = ("MONEYLINE", "SPREAD", "TOTAL")
PROP_OU_FAMILIES = (
    "PASS_YARDS", "PASS_TDS", "PASS_ATTEMPTS", "COMPLETIONS",
    "PASS_RUSH_YARDS", "QB_INTERCEPTIONS", "RECEIVING_YARDS", "RECEPTIONS",
    "RUSH_YARDS", "RUSH_ATTEMPTS", "RUSH_REC_YARDS",
)
# Anytime TD is in the design's prop leg (section 2.1) but has no two-sided
# O/U pair; see ambiguity A1 in IMPLEMENTATION.md.
PROP_FAMILIES = PROP_OU_FAMILIES + ("ANYTIME_TD",)

ITEM_KINDS = ("DECISION", "CLOSING", "S1", "S2")
ITEM_TERMINAL_STATES = ("SATISFIED", "REFUSED", "MISSED_OR_BLOCKED",
                        "INDETERMINATE")

_EPS = 1e-15


class ForwardValidationError(RuntimeError):
    """A fail-closed refusal carrying a named, machine-readable reason."""


class ForwardValidationNotActivated(ForwardValidationError):
    """Raised on every attempt to open an evidence (activated) campaign."""


class RecordRejected(ForwardValidationError):
    """A capture record failed intake validation; ``reason`` is named."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# --- Activation seam ---------------------------------------------------------

def assert_forward_validation_activated(repo_root: Path) -> None:
    """Refuse unless an owner activation approval artifact exists.

    It does not. Mirrors the G2 attempt-2 go/no-go ledger pattern: the
    check happens before any argument is acted on, and even the presence
    of an artifact does not activate this build — the activation
    implementation is added only by the separately approved activation
    step (design section 4.1: dry-run completion reported, then an
    explicit owner approval naming scope, legs, and freeze SHA).
    """
    ledger = Path(repo_root) / ACTIVATION_APPROVAL_PATH
    if not ledger.is_file():
        raise ForwardValidationNotActivated(
            "FORWARD_VALIDATION_NOT_ACTIVATED: no owner activation "
            f"approval artifact at {ACTIVATION_APPROVAL_PATH.as_posix()} "
            "— owner ruling (Oct 13 2026) approves implementation and "
            "synthetic testing only; activation requires the design "
            "section 4.1 sequence (dry-run proof reported, then an "
            "explicit approval naming scope, legs, and freeze SHA).")
    raise ForwardValidationNotActivated(
        "FORWARD_VALIDATION_ACTIVATION_NOT_IMPLEMENTED_IN_THIS_BUILD: "
        "an activation approval artifact is present, but this build "
        "contains no activation implementation; that code is added only "
        "by the separately approved activation step.")


# --- Small helpers -----------------------------------------------------------

def _parse_ts(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp; naive or unparseable -> None."""
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        out = datetime.fromisoformat(raw[:-1] + "+00:00"
                                     if raw.endswith("Z") else raw)
    except ValueError:
        return None
    if out.tzinfo is None or out.utcoffset() is None:
        return None
    return out.astimezone(timezone.utc)


def _canonical_id(payload: Mapping[str, Any]) -> str:
    """Deterministic content id (capture-receipt discipline)."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      default=str)
    return sha256(blob.encode("utf-8")).hexdigest()


def _clip(p: float) -> float:
    return min(max(p, _EPS), 1.0 - _EPS)


def _is_integer_line(line: float) -> bool:
    return float(line) == int(float(line))


# --- Paired-quote contract (design sections 1.2 / 2.3) -----------------------

def validate_quote_pair(pair: Mapping[str, Any], *, kickoff: datetime,
                        market: str) -> dict[str, Any]:
    """Validate one two-sided quote pair against the strict contract.

    Returns a normalized pair dict on success; raises RecordRejected with
    a named reason on the first failed clause. Never repairs anything.
    """
    if not isinstance(pair, Mapping):
        raise RecordRejected("PAIR_MISSING")
    book = str(pair.get("book") or "")
    if book != REQUIRED_BOOK:
        raise RecordRejected(f"BOOK_NOT_DRAFTKINGS:{book or 'MISSING'}")
    sides = pair.get("sides")
    if not isinstance(sides, Sequence) or isinstance(sides, (str, bytes)) \
            or len(sides) != 2:
        raise RecordRejected("PAIR_SIDES_NOT_TWO")
    side_a, side_b = sides[0], sides[1]
    for side in (side_a, side_b):
        if not isinstance(side, Mapping):
            raise RecordRejected("PAIR_SIDE_MALFORMED")
        side_book = side.get("book")
        if side_book is not None and str(side_book) != book:
            raise RecordRejected("PAIR_BOOK_MISMATCH")
        if side.get("event_id") is not None and pair.get("event_id") is not None \
                and str(side.get("event_id")) != str(pair.get("event_id")):
            raise RecordRejected("PAIR_EVENT_MISMATCH")
    selections = {str(side_a.get("selection") or "").upper(),
                  str(side_b.get("selection") or "").upper()}
    expected = {"TOTAL": {"OVER", "UNDER"},
                "PROP_OU": {"OVER", "UNDER"}}.get(
                    market, {"HOME", "AWAY"})
    if selections != expected:
        raise RecordRejected("PAIR_SIDES_NOT_COMPLEMENTARY")
    line_a, line_b = side_a.get("line"), side_b.get("line")
    if line_a is not None and line_b is not None \
            and float(line_a) != float(line_b):
        raise RecordRejected("PAIR_LINE_MISMATCH")
    if pair.get("line") is not None and line_a is not None \
            and float(pair.get("line")) != float(line_a):
        raise RecordRejected("PAIR_LINE_MISMATCH")

    parsed: list[tuple[Mapping[str, Any], datetime]] = []
    for side in (side_a, side_b):
        price = side.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)) \
                or not isfinite(float(price)):
            raise RecordRejected("PRICE_INVALID")
        if float(price) == -100.0:
            raise RecordRejected("PRICE_MINUS_100_INVALID")
        if -100.0 < float(price) < 100.0:
            raise RecordRejected("PRICE_INVALID")
        if side.get("captured_at") is None:
            # A price asserted without its own receipt timestamp is not
            # a quote (design section 1.2; the #2153 refusal semantics).
            raise RecordRejected("OPPOSITE_PRICE_NOT_A_TIMESTAMPED_QUOTE")
        ts = _parse_ts(side.get("captured_at"))
        if ts is None:
            raise RecordRejected("QUOTE_TIMESTAMP_INVALID")
        parsed.append((side, ts))
    (side_a, ts_a), (side_b, ts_b) = parsed

    if abs((ts_a - ts_b).total_seconds()) > PAIR_SKEW_MAX_SECONDS:
        raise RecordRejected("PAIR_SKEW_EXCEEDS_120S")
    for _, ts in parsed:
        if ts >= kickoff:
            raise RecordRejected("QUOTE_NOT_PREGAME")
    assembled = _parse_ts(pair.get("assembled_at"))
    if assembled is None:
        raise RecordRejected("PAIR_ASSEMBLED_AT_MISSING")
    for _, ts in parsed:
        if ts > assembled:
            raise RecordRejected("QUOTE_TIMESTAMP_AFTER_ASSEMBLY")
        if (assembled - ts).total_seconds() > QUOTE_FRESHNESS_MAX_SECONDS:
            raise RecordRejected("QUOTE_STALE_AT_ASSEMBLY")
    line = pair.get("line", line_a)
    return {
        "book": book,
        "event_id": pair.get("event_id"),
        "market": market,
        "line": None if line is None else float(line),
        "sides": [
            {"selection": str(s.get("selection")).upper(),
             "price": float(s.get("price")),
             "captured_at": ts.isoformat()}
            for s, ts in parsed
        ],
        "assembled_at": assembled.isoformat(),
    }


def classify_pair_timing(normalized_pair: Mapping[str, Any], *,
                         kickoff: datetime) -> str:
    """CLOSING iff the later side falls in the final 30 min pre-kickoff."""
    later = max(_parse_ts(s["captured_at"])
                for s in normalized_pair["sides"])
    if kickoff - timedelta(seconds=CLOSING_FINAL_WINDOW_SECONDS) \
            <= later < kickoff:
        return "CLOSING"
    return "PREGAME_SNAPSHOT"


def _devig_market_p(normalized_pair: Mapping[str, Any], *,
                    selection: str, method: str) -> float:
    """No-vig market probability for ``selection`` via sportsedge.devig."""
    sides = normalized_pair["sides"]
    cand = next(s for s in sides if s["selection"] == selection)
    opp = next(s for s in sides if s["selection"] != selection)
    line = normalized_pair.get("line")

    entity = str(normalized_pair.get("event_id") or "")

    def quote(side: Mapping[str, Any]) -> dict[str, Any]:
        q = {"game_id": entity,
             "market": str(normalized_pair.get("market") or ""),
             "entity_id": entity,
             "side": side["selection"],
             "american_odds": side["price"],
             # sportsedge.devig requires a line key on every quote;
             # moneyline pairs carry 0.0 on both sides.
             "line": 0.0 if line is None else line}
        return q

    fn = power_devig if method == "POWER_V1" else multiplicative_devig
    try:
        result = fn(quote(cand), quote(opp))
    except DevigError as exc:
        raise ForwardValidationError(f"DEVIG_FAILED:{exc}") from exc
    return float(result.candidate_fair_probability)


# --- Bootstrap / metrics -----------------------------------------------------

def _cluster_bootstrap_ci(block_deltas: Mapping[Any, Sequence[float]], *,
                          reps: int, seed: int) -> tuple[float, float, float]:
    """Week-cluster bootstrap CI for the mean paired delta.

    Resamples whole week blocks with replacement (design section 1.4:
    games sharing a kickoff week are one block). Returns
    (point_mean, ci_low, ci_high). Deterministic under ``seed``.
    """
    blocks = [list(v) for v in block_deltas.values() if v]
    if not blocks:
        raise ForwardValidationError("BOOTSTRAP_NO_BLOCKS")
    total_n = sum(len(b) for b in blocks)
    point = sum(sum(b) for b in blocks) / total_n
    block_sums = [sum(b) for b in blocks]
    block_ns = [len(b) for b in blocks]
    rng = random.Random(seed)
    k = len(blocks)
    means: list[float] = []
    for _ in range(reps):
        s = 0.0
        n = 0
        for _ in range(k):
            i = rng.randrange(k)
            s += block_sums[i]
            n += block_ns[i]
        means.append(s / n)
    means.sort()
    lo = means[int(0.025 * reps)]
    hi = means[min(reps - 1, int(0.975 * reps))]
    return point, lo, hi


def _verdict_from_cis(brier: tuple[float, float, float],
                      logloss: tuple[float, float, float]) -> str:
    """Section 1.5 verdict rules on primary-metric CIs."""
    if brier[2] < 0 and logloss[2] < 0:
        return "DEMONSTRATED_EDGE_RESEARCH_ONLY"
    if brier[1] > 0 or logloss[1] > 0:
        return "REFUTED"
    return "INCONCLUSIVE"


def _brier(p: float, y: float) -> float:
    return (p - y) ** 2


def _logloss(p: float, y: float) -> float:
    p = _clip(p)
    return -(y * log(p) + (1.0 - y) * log(1.0 - p))


# --- Campaign: intake, accounting, watchdog reconciliation -------------------

class Campaign:
    """One forward-validation campaign (cohort) under one freeze.

    This build constructs DRY_RUN campaigns only. Evidence campaigns are
    refused by :func:`open_evidence_campaign`. Records are append-only
    and content-addressed; a submitted record is never mutated or
    removed — corrections are new records (design section 5.2).
    """

    def __init__(self, *, mode: str = "DRY_RUN",
                 freeze_sha256: str | None = None):
        if mode != "DRY_RUN":
            raise ForwardValidationNotActivated(
                "FORWARD_VALIDATION_NOT_ACTIVATED: this build constructs "
                "DRY_RUN campaigns only; evidence campaigns require the "
                "owner activation approval of design section 4.1.")
        self.mode = mode
        self.freeze_sha256 = freeze_sha256
        self.records: dict[str, dict[str, Any]] = {}
        self.refusals: list[dict[str, Any]] = []
        self.settlements: dict[str, dict[str, Any]] = {}
        self.prop_settlements: dict[str, dict[str, Any]] = {}
        self.prop_exclusions: list[dict[str, Any]] = []
        self.items: dict[str, dict[str, Any]] = {}
        self.alerts: list[dict[str, Any]] = []
        self._slate_alerts_fired: set[str] = set()

    # -- expected schedule (watchdog, design section 3.1) --------------------
    def register_expected(self, item: Mapping[str, Any]) -> str:
        kind = str(item.get("kind") or "")
        if kind not in ITEM_KINDS:
            raise ForwardValidationError(f"EXPECTED_ITEM_KIND_INVALID:{kind}")
        window_close = _parse_ts(item.get("window_close_utc"))
        if window_close is None:
            raise ForwardValidationError("EXPECTED_ITEM_WINDOW_CLOSE_INVALID")
        item_id = str(item.get("item_id") or "")
        if not item_id:
            raise ForwardValidationError("EXPECTED_ITEM_ID_MISSING")
        if item_id in self.items:
            raise ForwardValidationError(f"EXPECTED_ITEM_DUPLICATE:{item_id}")
        self.items[item_id] = {
            "item_id": item_id,
            "kind": kind,
            "game_id": item.get("game_id"),
            "slate_id": item.get("slate_id"),
            "week_block": item.get("week_block"),
            "window_close_utc": window_close.isoformat(),
            "freeze_sha256": item.get("freeze_sha256"),
            "state": "PENDING",
            "record_id": None,
            "refusal_reason": None,
            "gap_record": False,
        }
        return item_id

    def record_refusal(self, item_id: str, reason: str, *,
                       at: str | None = None) -> None:
        """Record a capture-time contract refusal for an expected item."""
        item = self.items.get(item_id)
        if item is None:
            raise ForwardValidationError(f"EXPECTED_ITEM_UNKNOWN:{item_id}")
        if item["state"] not in ("PENDING",):
            raise ForwardValidationError(
                f"ITEM_ALREADY_TERMINAL:{item_id}:{item['state']}")
        item["state"] = "REFUSED"
        item["refusal_reason"] = reason
        self.refusals.append({
            "item_id": item_id, "reason": reason, "at": at,
            "stamp": DRY_RUN_STAMP if self.mode == "DRY_RUN" else None,
        })

    def record_gap(self, item_id: str) -> None:
        """Record the gap auditor's immutable record of absence."""
        item = self.items.get(item_id)
        if item is None:
            raise ForwardValidationError(f"EXPECTED_ITEM_UNKNOWN:{item_id}")
        if item["state"] != "PENDING":
            raise ForwardValidationError(
                f"ITEM_ALREADY_TERMINAL:{item_id}:{item['state']}")
        item["gap_record"] = True

    def reconcile(self, *, now: datetime) -> dict[str, Any]:
        """Resolve every due PENDING item to exactly one terminal state.

        INDETERMINATE is assigned only here, only when the window plus
        the 15-minute grace has elapsed with no valid record, no refusal,
        and no gap record — and it is permanent (design section 3.1).
        """
        for item in self.items.values():
            if item["state"] != "PENDING":
                continue
            close = _parse_ts(item["window_close_utc"])
            if now < close + RECONCILE_GRACE:
                continue
            if item["record_id"] is not None:
                item["state"] = "SATISFIED"
            elif item["gap_record"]:
                item["state"] = "MISSED_OR_BLOCKED"
            else:
                item["state"] = "INDETERMINATE"
                self.alerts.append({
                    "alert": "INDETERMINATE_UNRESOLVED",
                    "item_id": item["item_id"],
                    "stamp": DRY_RUN_STAMP if self.mode == "DRY_RUN"
                             else None,
                })
        # Full-slate miss: every item of a slate unsatisfied.
        slates: dict[str, list[dict[str, Any]]] = {}
        for item in self.items.values():
            if item.get("slate_id"):
                slates.setdefault(str(item["slate_id"]), []).append(item)
        for slate_id, members in slates.items():
            if slate_id in self._slate_alerts_fired:
                continue
            terminal = [m for m in members
                        if m["state"] in ITEM_TERMINAL_STATES]
            if terminal and all(m["state"] != "SATISFIED" for m in terminal) \
                    and len(terminal) == len(members):
                self._slate_alerts_fired.add(slate_id)
                self.alerts.append({"alert": "FULL_SLATE_MISS",
                                    "slate_id": slate_id,
                                    "stamp": DRY_RUN_STAMP
                                    if self.mode == "DRY_RUN" else None})
        counts = {s: 0 for s in ITEM_TERMINAL_STATES}
        counts["PENDING"] = 0
        for item in self.items.values():
            counts[item["state"]] = counts.get(item["state"], 0) + 1
        return counts

    def slate_state(self, slate_id: str) -> str:
        """Slate rollup: any INDETERMINATE item marks the slate, stickily."""
        members = [i for i in self.items.values()
                   if str(i.get("slate_id")) == slate_id]
        if not members:
            return "UNKNOWN_SLATE"
        if any(i["state"] == "INDETERMINATE" for i in members):
            return "INDETERMINATE"
        if all(i["state"] in ITEM_TERMINAL_STATES for i in members):
            if all(i["state"] == "SATISFIED" for i in members):
                return "SATISFIED"
            return "COMPLETED_WITH_GAPS"
        return "PENDING"

    # -- intake ---------------------------------------------------------------
    def _check_origin(self, record: Mapping[str, Any]) -> None:
        origin = record.get("origin")
        if origin is None:
            raise RecordRejected("RECORD_ORIGIN_MISSING")
        if self.mode == "DRY_RUN" and origin != "SYNTHETIC":
            raise RecordRejected(
                f"NON_SYNTHETIC_RECORD_REFUSED_IN_DRY_RUN:{origin}")

    def _check_item_admissible(self, record: Mapping[str, Any]) -> dict:
        item_id = record.get("expected_item_id")
        if item_id is None:
            raise RecordRejected("EXPECTED_ITEM_ID_MISSING")
        item = self.items.get(str(item_id))
        if item is None:
            raise RecordRejected(f"EXPECTED_ITEM_UNKNOWN:{item_id}")
        if item["state"] == "INDETERMINATE":
            raise RecordRejected(
                "LATE_RECORD_AFTER_TERMINAL_STATE:INDETERMINATE")
        if item["state"] == "MISSED_OR_BLOCKED":
            raise RecordRejected(
                "LATE_RECORD_AFTER_TERMINAL_STATE:MISSED_OR_BLOCKED")
        if item["state"] == "REFUSED":
            raise RecordRejected("ITEM_ALREADY_REFUSED")
        if item["state"] == "SATISFIED" or item.get("record_id") is not None:
            # One expected item binds exactly one capture record; the
            # binding exists from admission, the SATISFIED state is
            # confirmed at reconciliation.
            raise RecordRejected("ITEM_ALREADY_SATISFIED")
        expected_freeze = item.get("freeze_sha256") or self.freeze_sha256
        if expected_freeze and record.get("freeze_sha256") \
                and str(record["freeze_sha256"]) != str(expected_freeze):
            self.alerts.append({"alert": "FREEZE_MANIFEST_MISMATCH",
                                "item_id": str(item_id)})
            raise RecordRejected("FREEZE_MANIFEST_MISMATCH")
        return item

    def _admit(self, record: Mapping[str, Any],
               normalized: dict[str, Any],
               item: dict[str, Any]) -> dict[str, Any]:
        record_id = _canonical_id(normalized)
        if record_id in self.records:
            return {"accepted": False, "reason": "DUPLICATE_RECORD",
                    "record_id": record_id}
        stored = deepcopy(normalized)
        stored["record_id"] = record_id
        stored["stamp"] = DRY_RUN_STAMP if self.mode == "DRY_RUN" else None
        self.records[record_id] = stored
        if item is not None:
            item["record_id"] = record_id
        return {"accepted": True, "reason": None, "record_id": record_id}

    def _refuse(self, record: Mapping[str, Any], reason: str) -> dict:
        item_id = record.get("expected_item_id")
        entry = {"item_id": item_id, "reason": reason,
                 "stamp": DRY_RUN_STAMP if self.mode == "DRY_RUN" else None}
        self.refusals.append(entry)
        if item_id is not None:
            item = self.items.get(str(item_id))
            if item is not None and item["state"] == "PENDING":
                item["state"] = "REFUSED"
                item["refusal_reason"] = reason
        return {"accepted": False, "reason": reason, "record_id": None}

    def submit_game_record(self, record: Mapping[str, Any]) -> dict:
        """Intake one game-leg capture record (DECISION or CLOSING)."""
        try:
            normalized = self._validate_game_record(record)
        except RecordRejected as exc:
            return self._refuse(record, exc.reason)
        record_id = _canonical_id(normalized)
        if record_id in self.records:
            # Deterministic-id resubmission: detected, never duplicated.
            return {"accepted": False, "reason": "DUPLICATE_RECORD",
                    "record_id": record_id}
        try:
            item = self._check_item_admissible(record)
        except RecordRejected as exc:
            return self._refuse(record, exc.reason)
        return self._admit(record, normalized, item)

    def _validate_game_record(self, record: Mapping[str, Any]) -> dict:
        self._check_origin(record)
        if record.get("record_kind") != "GAME_CAPTURE":
            raise RecordRejected("RECORD_KIND_INVALID")
        if str(record.get("season_phase") or "REGULAR") != "REGULAR":
            raise RecordRejected("POPULATION_POSTSEASON_EXCLUDED")
        kickoff = _parse_ts(record.get("kickoff_utc"))
        if kickoff is None:
            raise RecordRejected("KICKOFF_INVALID")
        capture_kind = str(record.get("capture_kind") or "")
        if capture_kind not in ("DECISION", "CLOSING"):
            raise RecordRejected("CAPTURE_KIND_INVALID")
        model = record.get("model") or {}
        if str(model.get("lane") or "LANE_A_INDEPENDENT") \
                == "MARKET_ANCHORED":
            raise RecordRejected("CANDIDATE_MUST_BE_INDEPENDENT_LANE_A")
        for fam, key in (("MONEYLINE", "moneyline_home_p"),
                         ("SPREAD", "spread_home_cover_p"),
                         ("TOTAL", "total_over_p")):
            p = model.get(key)
            if isinstance(p, bool) or not isinstance(p, (int, float)) \
                    or not (0.0 < float(p) < 1.0):
                raise RecordRejected(f"MODEL_PROB_INVALID:{fam}")
        pairs_in = record.get("pairs") or {}
        pairs_out: dict[str, Any] = {}
        for fam in GAME_FAMILIES:
            if fam not in pairs_in:
                raise RecordRejected(f"PAIR_MISSING:{fam}")
            pairs_out[fam] = validate_quote_pair(
                pairs_in[fam], kickoff=kickoff, market=fam)
        # Decision-capture window discipline (see ambiguity A2 in the
        # implementation report): a DECISION record's pairs must have
        # been assembled inside T-120..T-45. CLOSING records are not
        # window-refused; their pairs are timing-classified per pair.
        if capture_kind == "DECISION":
            hi, lo = DECISION_WINDOW_SECONDS
            for fam, pair in pairs_out.items():
                assembled = _parse_ts(pair["assembled_at"])
                delta = (kickoff - assembled).total_seconds()
                if not (lo <= delta <= hi):
                    raise RecordRejected(
                        f"DECISION_CAPTURE_OUTSIDE_WINDOW:{fam}")
        classifications = {
            fam: classify_pair_timing(pair, kickoff=kickoff)
            for fam, pair in pairs_out.items()
        }
        normalized = {
            "record_kind": "GAME_CAPTURE",
            "origin": record.get("origin"),
            "game_id": record.get("game_id"),
            "week_block": record.get("week_block"),
            "kickoff_utc": kickoff.isoformat(),
            "capture_kind": capture_kind,
            "season_phase": "REGULAR",
            "freeze_sha256": record.get("freeze_sha256"),
            "model": {k: float(model[k]) for k in
                      ("moneyline_home_p", "spread_home_cover_p",
                       "total_over_p")},
            "pairs": pairs_out,
            "pair_classifications": classifications,
            "expected_item_id": record.get("expected_item_id"),
        }
        return normalized

    def submit_settlement(self, record_id: str, *, home_score: int,
                          away_score: int) -> None:
        """Attach settlement-side final scores (append-only, postgame)."""
        if record_id not in self.records:
            raise ForwardValidationError(f"SETTLEMENT_UNKNOWN_RECORD:"
                                         f"{record_id}")
        if record_id in self.settlements:
            raise ForwardValidationError("SETTLEMENT_ALREADY_RECORDED:"
                                         f"{record_id}")
        self.settlements[record_id] = {"home_score": int(home_score),
                                       "away_score": int(away_score)}

    # -- prop leg intake ------------------------------------------------------
    def submit_prop_record(self, record: Mapping[str, Any]) -> dict:
        """Intake one prop-leg capture record for a scoped family."""
        try:
            normalized, partial = self._validate_prop_record(record)
        except RecordRejected as exc:
            return self._refuse(record, exc.reason)
        record_id = _canonical_id(normalized)
        if record_id in self.records:
            return {"accepted": False, "reason": "DUPLICATE_RECORD",
                    "record_id": record_id}
        try:
            item = self._check_item_admissible(record)
        except RecordRejected as exc:
            return self._refuse(record, exc.reason)
        result = self._admit(record, normalized, item)
        if result["accepted"]:
            self.records[result["record_id"]]["verdict_eligible"] = \
                not partial
        return result

    def _validate_prop_record(self, record: Mapping[str, Any]) \
            -> tuple[dict[str, Any], bool]:
        self._check_origin(record)
        if record.get("record_kind") != "PROP_CAPTURE":
            raise RecordRejected("RECORD_KIND_INVALID")
        family = str(record.get("family") or "")
        if family not in PROP_FAMILIES:
            raise RecordRejected(f"FAMILY_OUT_OF_SCOPE:{family}")
        kickoff = _parse_ts(record.get("kickoff_utc"))
        if kickoff is None:
            raise RecordRejected("KICKOFF_INVALID")
        participation = record.get("participation") or {}
        if not participation.get("s2"):
            # Excluded from evidence, but counted (design section 2.2).
            self.prop_exclusions.append({
                "family": family,
                "player_id": record.get("player_id"),
                "reason": "PARTICIPATION_S2_MISSING_EXCLUDED"})
            raise RecordRejected("PARTICIPATION_S2_MISSING_EXCLUDED")
        partial = not participation.get("s1")
        if family == "ANYTIME_TD":
            quote = record.get("quote") or {}
            ts = _parse_ts(quote.get("captured_at"))
            if ts is None:
                raise RecordRejected("OPPOSITE_PRICE_NOT_A_TIMESTAMPED_QUOTE")
            if ts >= kickoff:
                raise RecordRejected("QUOTE_NOT_PREGAME")
            price = quote.get("price")
            if isinstance(price, bool) or not isinstance(price, (int, float)):
                raise RecordRejected("PRICE_INVALID")
            if float(price) == -100.0:
                raise RecordRejected("PRICE_MINUS_100_INVALID")
            normalized = {
                "record_kind": "PROP_CAPTURE",
                "origin": record.get("origin"),
                "game_id": record.get("game_id"),
                "week_block": record.get("week_block"),
                "kickoff_utc": kickoff.isoformat(),
                "player_id": record.get("player_id"),
                "family": family,
                "pair": None,
                "pair_classification": "SINGLE_SIDED_NO_PAIR_CONTRACT",
                "participation_partial": partial,
                "expected_item_id": record.get("expected_item_id"),
            }
            return normalized, partial
        pair = validate_quote_pair(record.get("pair") or {},
                                   kickoff=kickoff, market="PROP_OU")
        engine_p = record.get("engine_p_over")
        if isinstance(engine_p, bool) \
                or not isinstance(engine_p, (int, float)) \
                or not (0.0 < float(engine_p) < 1.0):
            raise RecordRejected("ENGINE_PROB_INVALID")
        engine_line = record.get("engine_line")
        if engine_line is None or float(engine_line) != float(pair["line"]):
            if not record.get("recomputed_at_captured_line"):
                raise RecordRejected("ENGINE_PROB_NOT_AT_CAPTURED_LINE")
        normalized = {
            "record_kind": "PROP_CAPTURE",
            "origin": record.get("origin"),
            "game_id": record.get("game_id"),
            "week_block": record.get("week_block"),
            "kickoff_utc": kickoff.isoformat(),
            "player_id": record.get("player_id"),
            "family": family,
            "line": pair["line"],
            "pair": pair,
            "pair_classification": classify_pair_timing(pair,
                                                        kickoff=kickoff),
            "engine_p_over": float(engine_p),
            "participation_partial": partial,
            "expected_item_id": record.get("expected_item_id"),
        }
        return normalized, partial

    def submit_prop_settlement(self, record_id: str, *,
                               stat_value: float | None,
                               dnp: bool = False) -> None:
        if record_id not in self.records:
            raise ForwardValidationError(f"SETTLEMENT_UNKNOWN_RECORD:"
                                         f"{record_id}")
        if record_id in self.prop_settlements:
            raise ForwardValidationError("SETTLEMENT_ALREADY_RECORDED:"
                                         f"{record_id}")
        self.prop_settlements[record_id] = {
            "stat_value": None if stat_value is None else float(stat_value),
            "dnp": bool(dnp)}


def open_evidence_campaign(repo_root: Path, **kwargs: Any) -> Campaign:
    """Open an activated evidence campaign. Refused in this build."""
    assert_forward_validation_activated(Path(repo_root))
    raise ForwardValidationNotActivated(
        "FORWARD_VALIDATION_ACTIVATION_NOT_IMPLEMENTED_IN_THIS_BUILD")


# --- Readouts and verdicts -----------------------------------------------------

def _base_output(campaign: Campaign) -> dict[str, Any]:
    return {
        "design_id": DESIGN_ID,
        "activation_state": ACTIVATION_STATE,
        "research_only": True,
        "stamp": DRY_RUN_STAMP if campaign.mode == "DRY_RUN" else None,
        "evidence_admissible": False,
    }


def _game_scored_triples(campaign: Campaign, family: str, *,
                         method: str) -> tuple[dict[Any, list[tuple[float, float, float]]], dict[str, int]]:
    """(model_p, market_p, y) triples by week block for one family.

    Only CLOSING-classified pairs on CLOSING captures with a settlement
    count as evaluation rows; pushes and ML ties are excluded and
    counted (design section 1.4 — no silent scoring).
    """
    counts = {"rows": 0, "excluded_pushes": 0, "excluded_ties": 0}
    blocks: dict[Any, list[tuple[float, float, float]]] = {}
    model_key = {"MONEYLINE": "moneyline_home_p",
                 "SPREAD": "spread_home_cover_p",
                 "TOTAL": "total_over_p"}[family]
    selection = {"MONEYLINE": "HOME", "SPREAD": "HOME",
                 "TOTAL": "OVER"}[family]
    for record_id, rec in campaign.records.items():
        if rec.get("record_kind") != "GAME_CAPTURE":
            continue
        if rec.get("capture_kind") != "CLOSING":
            continue
        if rec["pair_classifications"].get(family) != "CLOSING":
            continue
        settlement = campaign.settlements.get(record_id)
        if settlement is None:
            continue
        home, away = settlement["home_score"], settlement["away_score"]
        pair = rec["pairs"][family]
        line = pair.get("line")
        if family == "MONEYLINE":
            if home == away:
                counts["excluded_ties"] += 1
                continue
            y = 1.0 if home > away else 0.0
        elif family == "SPREAD":
            margin = home - away
            if line is not None and _is_integer_line(line) \
                    and margin == -line:
                counts["excluded_pushes"] += 1
                continue
            y = 1.0 if margin + float(line or 0.0) > 0 else 0.0
        else:  # TOTAL
            total = home + away
            if line is not None and _is_integer_line(line) \
                    and total == line:
                counts["excluded_pushes"] += 1
                continue
            y = 1.0 if total > float(line or 0.0) else 0.0
        market_p = _devig_market_p(pair, selection=selection,
                                   method=method)
        model_p = float(rec["model"][model_key])
        blocks.setdefault(rec.get("week_block"), []).append(
            (model_p, market_p, y))
        counts["rows"] += 1
    return blocks, counts


def _deltas_by_block(triples: Mapping[Any, Sequence[tuple[float, float, float]]],
                     which: int) -> dict[Any, list[float]]:
    out: dict[Any, list[float]] = {}
    for block, rows in triples.items():
        vals = []
        for model_p, market_p, y in rows:
            if which == 0:
                vals.append(_brier(model_p, y) - _brier(market_p, y))
            else:
                vals.append(_logloss(model_p, y) - _logloss(market_p, y))
        out[block] = vals
    return out


def _leg_status(*, n: int, blocks: int, target_n: int, target_blocks: int,
                extension_n: int, extension_used: bool) -> str:
    """Threshold state machine for the game leg.

    Without the extension, the verdict point is (n >= target_n AND
    blocks >= target_blocks). Once the single extension is used, the
    verdict point moves to the extension target: n in
    [target_n, extension_n) remains accrual — no interim verdicts
    (design section 1.3).
    """
    if extension_used:
        if n >= extension_n and blocks >= target_blocks:
            return "EXTENSION_TARGET"
        return "ACCRUAL"
    if n >= target_n and blocks >= target_blocks:
        return "TARGET"
    return "ACCRUAL"


def game_leg_readout(campaign: Campaign, family: str, *,
                     reps: int = BOOTSTRAP_REPS, seed: int = BOOTSTRAP_SEED,
                     extension_used: bool = False) -> dict[str, Any]:
    """Per-family game-leg readout (design sections 1.3-1.5).

    Below target this is an accrual report labeled
    ``ACCRUAL_ONLY_NOT_A_VERDICT`` and carries no verdict. At target it
    computes the paired-delta CIs and the section 1.5 verdict, with the
    proportional-devig sensitivity and the coverage presumption applied.
    """
    if family not in GAME_FAMILIES:
        raise ForwardValidationError(f"GAME_FAMILY_INVALID:{family}")
    out = _base_output(campaign)
    out.update({"leg": "GAME", "family": family,
                "label": ACCRUAL_LABEL, "verdict": None,
                "disclosures": [ML_TIE_DISCLOSURE]})
    triples, counts = _game_scored_triples(campaign, family,
                                           method="POWER_V1")
    n = counts["rows"]
    blocks = len(triples)
    expected = sum(1 for i in campaign.items.values()
                   if i["kind"] == "CLOSING")
    satisfied = sum(1 for i in campaign.items.values()
                    if i["kind"] == "CLOSING"
                    and i["state"] == "SATISFIED")
    ratio = (satisfied / expected) if expected else None
    out["counts"] = {**counts, "week_blocks": blocks,
                     "expected_closing_items": expected,
                     "satisfied_closing_items": satisfied,
                     "satisfied_ratio": ratio}
    state = _leg_status(
        n=n, blocks=blocks, target_n=GAME_LEG_TARGET_GAMES,
        target_blocks=GAME_LEG_TARGET_WEEK_BLOCKS,
        extension_n=GAME_LEG_EXTENSION_GAMES,
        extension_used=extension_used)
    if state == "ACCRUAL":
        out["status"] = "NOT_YET"
        if ratio is not None and ratio < COVERAGE_DISCLOSURE_BELOW:
            out["coverage_disclosure"] = (
                f"SATISFIED_RATIO_{ratio:.3f}_BELOW_0.90")
        return out
    # At target: compute CIs (primary POWER_V1 + proportional sensitivity).
    brier = _cluster_bootstrap_ci(_deltas_by_block(triples, 0),
                                  reps=reps, seed=seed)
    logloss = _cluster_bootstrap_ci(_deltas_by_block(triples, 1),
                                    reps=reps, seed=seed)
    triples_s, _ = _game_scored_triples(campaign, family,
                                        method="MULTIPLICATIVE_V1")
    brier_s = _cluster_bootstrap_ci(_deltas_by_block(triples_s, 0),
                                    reps=reps, seed=seed)
    logloss_s = _cluster_bootstrap_ci(_deltas_by_block(triples_s, 1),
                                      reps=reps, seed=seed)
    verdict = _verdict_from_cis(brier, logloss)
    sens_verdict = _verdict_from_cis(brier_s, logloss_s)
    method_sensitive = sens_verdict != verdict
    out["metrics"] = {
        "delta_brier": {"mean": brier[0], "ci_low": brier[1],
                        "ci_high": brier[2]},
        "delta_logloss": {"mean": logloss[0], "ci_low": logloss[1],
                          "ci_high": logloss[2]},
        "sensitivity_multiplicative": {
            "delta_brier_mean": brier_s[0],
            "delta_logloss_mean": logloss_s[0],
            "verdict": sens_verdict},
    }
    out["method_sensitive"] = method_sensitive
    out["temporal_split"] = _temporal_split(triples)
    favorable = brier[0] < 0 and logloss[0] < 0
    if ratio is not None and ratio < COVERAGE_INCONCLUSIVE_BELOW:
        out["verdict"] = "INCONCLUSIVE"
        out["verdict_detail"] = "COVERAGE"
        out["label"] = "INCONCLUSIVE"
    elif method_sensitive:
        out["verdict"] = "INCONCLUSIVE"
        out["verdict_detail"] = "METHOD_SENSITIVE_SIGN"
        out["label"] = "INCONCLUSIVE"
    else:
        out["verdict"] = verdict
        out["label"] = verdict
    out["status"] = "VERDICT_COMPUTED"
    if out["verdict"] == "INCONCLUSIVE" and state == "TARGET" \
            and favorable and not method_sensitive \
            and out.get("verdict_detail") != "COVERAGE":
        out["extension_available"] = True
        out["extension_target_n"] = GAME_LEG_EXTENSION_GAMES
    else:
        out["extension_available"] = False
    return out


def _temporal_split(triples: Mapping[Any, Sequence[tuple[float, float, float]]]) -> dict[str, Any]:
    """First-half / second-half descriptive split (section 1.3)."""
    rows: list[tuple[Any, float, float]] = []
    for block in sorted(triples, key=lambda b: (str(type(b)), b)):
        for model_p, market_p, y in triples[block]:
            rows.append((block, _brier(model_p, y) - _brier(market_p, y),
                         _logloss(model_p, y) - _logloss(market_p, y)))
    if not rows:
        return {"first_half": None, "second_half": None}
    half = len(rows) // 2
    def agg(part):
        if not part:
            return None
        return {"n": len(part),
                "delta_brier_mean": sum(r[1] for r in part) / len(part),
                "delta_logloss_mean": sum(r[2] for r in part) / len(part)}
    return {"first_half": agg(rows[:half]), "second_half": agg(rows[half:])}


def prop_leg_readout(campaign: Campaign, family: str, *,
                     reps: int = BOOTSTRAP_REPS, seed: int = BOOTSTRAP_SEED,
                     extension_used: bool = False) -> dict[str, Any]:
    """Per-family prop-leg readout (design section 2.5).

    n < 150: accrual only. 150 <= n < 300 (or weeks short): provisional
    readout labeled PROVISIONAL_UNDERPOWERED in every surface, mean
    deltas only, no verdict. n >= 300 AND >= 15 weeks: section 1.5 CI
    verdict rules, per family (no pooled cross-family verdict exists).
    """
    if family not in PROP_FAMILIES:
        raise ForwardValidationError(f"PROP_FAMILY_INVALID:{family}")
    out = _base_output(campaign)
    out.update({"leg": "PROP", "family": family,
                "label": ACCRUAL_LABEL, "verdict": None,
                "disclosures": []})
    if family == "ANYTIME_TD":
        # Ambiguity A1: the design scopes Anytime TD into this leg but
        # the section 2.3 pairing contract is defined for two-sided O/U
        # quotes; a single-sided price has no no-vig pair. Fail closed:
        # accrual counts only, never a provisional readout or verdict.
        n = sum(1 for r in campaign.records.values()
                if r.get("record_kind") == "PROP_CAPTURE"
                and r.get("family") == family)
        out["counts"] = {"records": n}
        out["status"] = "PAIR_CONTRACT_UNDEFINED_FOR_SINGLE_SIDED_MARKET"
        return out
    counts = {"rows": 0, "excluded_pushes": 0, "void_dnp": 0,
              "partial_participation": 0}
    triples: dict[Any, list[tuple[float, float, float]]] = {}
    for record_id, rec in campaign.records.items():
        if rec.get("record_kind") != "PROP_CAPTURE" \
                or rec.get("family") != family:
            continue
        if rec.get("pair_classification") != "CLOSING":
            continue
        if rec.get("participation_partial"):
            counts["partial_participation"] += 1
            continue
        if not rec.get("verdict_eligible", True):
            continue
        settlement = campaign.prop_settlements.get(record_id)
        if settlement is None:
            continue
        if settlement["dnp"]:
            counts["void_dnp"] += 1
            continue
        stat = settlement["stat_value"]
        line = float(rec["line"])
        if _is_integer_line(line) and stat == line:
            counts["excluded_pushes"] += 1
            continue
        y = 1.0 if stat > line else 0.0
        market_p = _devig_market_p(rec["pair"], selection="OVER",
                                   method="POWER_V1")
        triples.setdefault(rec.get("week_block"), []).append(
            (float(rec["engine_p_over"]), market_p, y))
        counts["rows"] += 1
    n = counts["rows"]
    weeks = len(triples)
    out["counts"] = {**counts, "weeks": weeks}
    if n < PROP_LEG_PROVISIONAL_MIN:
        out["status"] = "NOT_YET"
        return out
    # Descriptive mean deltas (both provisional and verdict surfaces).
    flat = [t for rows in triples.values() for t in rows]
    out["descriptive"] = {
        "delta_brier_mean": sum(_brier(m, y) - _brier(k, y)
                                for m, k, y in flat) / n,
        "delta_logloss_mean": sum(_logloss(m, y) - _logloss(k, y)
                                  for m, k, y in flat) / n,
    }
    verdict_ready = n >= PROP_LEG_TARGET_PLAYER_GAMES \
        and weeks >= PROP_LEG_TARGET_WEEKS
    if extension_used:
        verdict_ready = n >= PROP_LEG_EXTENSION_PLAYER_GAMES \
            and weeks >= PROP_LEG_TARGET_WEEKS
    if not verdict_ready:
        out["label"] = PROVISIONAL_LABEL
        out["status"] = "PROVISIONAL"
        if n >= PROP_LEG_TARGET_PLAYER_GAMES \
                and weeks < PROP_LEG_TARGET_WEEKS:
            out["provisional_reason"] = "WEEK_BLOCKS_BELOW_15"
        return out
    brier = _cluster_bootstrap_ci(_deltas_by_block(triples, 0),
                                  reps=reps, seed=seed)
    logloss = _cluster_bootstrap_ci(_deltas_by_block(triples, 1),
                                    reps=reps, seed=seed)
    triples_s: dict[Any, list[tuple[float, float, float]]] = {}
    for record_id, rec in campaign.records.items():
        if rec.get("record_kind") != "PROP_CAPTURE" \
                or rec.get("family") != family \
                or rec.get("pair_classification") != "CLOSING" \
                or rec.get("participation_partial") \
                or not rec.get("verdict_eligible", True):
            continue
        settlement = campaign.prop_settlements.get(record_id)
        if settlement is None or settlement["dnp"]:
            continue
        stat = settlement["stat_value"]
        line = float(rec["line"])
        if _is_integer_line(line) and stat == line:
            continue
        y = 1.0 if stat > line else 0.0
        triples_s.setdefault(rec.get("week_block"), []).append(
            (float(rec["engine_p_over"]),
             _devig_market_p(rec["pair"], selection="OVER",
                             method="MULTIPLICATIVE_V1"), y))
    brier_s = _cluster_bootstrap_ci(_deltas_by_block(triples_s, 0),
                                    reps=reps, seed=seed)
    logloss_s = _cluster_bootstrap_ci(_deltas_by_block(triples_s, 1),
                                      reps=reps, seed=seed)
    verdict = _verdict_from_cis(brier, logloss)
    method_sensitive = _verdict_from_cis(brier_s, logloss_s) != verdict
    out["metrics"] = {
        "delta_brier": {"mean": brier[0], "ci_low": brier[1],
                        "ci_high": brier[2]},
        "delta_logloss": {"mean": logloss[0], "ci_low": logloss[1],
                          "ci_high": logloss[2]},
    }
    out["method_sensitive"] = method_sensitive
    if method_sensitive:
        out["verdict"] = "INCONCLUSIVE"
        out["verdict_detail"] = "METHOD_SENSITIVE_SIGN"
        out["label"] = "INCONCLUSIVE"
    else:
        out["verdict"] = verdict
        out["label"] = verdict
    out["status"] = "VERDICT_COMPUTED"
    favorable = brier[0] < 0 and logloss[0] < 0
    out["extension_available"] = bool(
        out["verdict"] == "INCONCLUSIVE" and favorable
        and not method_sensitive and not extension_used)
    if out["extension_available"]:
        out["extension_target_n"] = PROP_LEG_EXTENSION_PLAYER_GAMES
    return out


def render_readout_text(readout: Mapping[str, Any]) -> str:
    """Text surface for a readout — carries the same labels as the dict."""
    lines = [
        f"{readout.get('design_id')} {readout.get('leg')} "
        f"{readout.get('family')}",
        f"activation_state: {readout.get('activation_state')}",
        f"label: {readout.get('label')}",
        f"status: {readout.get('status')}",
    ]
    if readout.get("stamp"):
        lines.append(f"stamp: {readout['stamp']}")
    if readout.get("verdict"):
        lines.append(f"verdict: {readout['verdict']}")
    if readout.get("verdict_detail"):
        lines.append(f"verdict_detail: {readout['verdict_detail']}")
    for d in readout.get("disclosures") or []:
        lines.append(f"disclosure: {d}")
    lines.append(f"counts: {json.dumps(readout.get('counts') or {}, sort_keys=True)}")
    lines.append("research_only: True")
    return "\n".join(lines)


def require_evidence_admissible(report: Mapping[str, Any]) -> None:
    """Refuse dry-run-stamped output presented as evidence (section 3.3)."""
    if report.get("stamp") == DRY_RUN_STAMP \
            or report.get("evidence_admissible") is False:
        raise ForwardValidationError(
            "DRY_RUN_NOT_EVIDENCE: dry-run output is never evidence "
            "about the model and is never pooled with a cohort.")


# --- Synthetic fabrication + the two-slate dry-run proof (section 3.3) -------

def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def make_synthetic_pair(*, kickoff: datetime, market: str,
                        line: float | None, minutes_before: float = 10.0,
                        skew_seconds: float = 20.0,
                        price_a: float = -110.0, price_b: float = -110.0,
                        selections: tuple[str, str] = ("HOME", "AWAY"),
                        event_id: str = "SYN-EVENT") -> dict[str, Any]:
    """Fabricate a contract-valid two-sided pair (synthetic data only)."""
    later = kickoff - timedelta(minutes=minutes_before)
    earlier = later - timedelta(seconds=skew_seconds)
    assembled = later + timedelta(seconds=5)
    sides = [
        {"selection": selections[0], "price": price_a,
         "captured_at": _iso(earlier)},
        {"selection": selections[1], "price": price_b,
         "captured_at": _iso(later)},
    ]
    if line is not None:
        for s in sides:
            s["line"] = line
    return {"book": REQUIRED_BOOK, "event_id": event_id, "market": market,
            "line": line, "sides": sides, "assembled_at": _iso(assembled)}


def make_synthetic_game_record(*, game_id: str, week_block: int,
                               kickoff: datetime, capture_kind: str,
                               item_id: str,
                               model_home_p: float = 0.55,
                               minutes_before: float | None = None,
                               spread_line: float = -3.5,
                               total_line: float = 44.5) -> dict[str, Any]:
    """Fabricate a synthetic game-leg capture record (not real data)."""
    if minutes_before is None:
        minutes_before = 90.0 if capture_kind == "DECISION" else 10.0
    pairs = {
        "MONEYLINE": make_synthetic_pair(
            kickoff=kickoff, market="MONEYLINE", line=None,
            minutes_before=minutes_before, event_id=game_id),
        "SPREAD": make_synthetic_pair(
            kickoff=kickoff, market="SPREAD", line=spread_line,
            minutes_before=minutes_before, event_id=game_id),
        "TOTAL": make_synthetic_pair(
            kickoff=kickoff, market="TOTAL", line=total_line,
            minutes_before=minutes_before, selections=("OVER", "UNDER"),
            event_id=game_id),
    }
    return {
        "record_kind": "GAME_CAPTURE", "origin": "SYNTHETIC",
        "game_id": game_id, "week_block": week_block,
        "kickoff_utc": _iso(kickoff), "capture_kind": capture_kind,
        "season_phase": "REGULAR",
        "model": {"moneyline_home_p": model_home_p,
                  "spread_home_cover_p": 0.53,
                  "total_over_p": 0.51},
        "pairs": pairs, "expected_item_id": item_id,
    }


def run_two_slate_dry_run_proof(*, games_per_slate: int = 4,
                                seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Section 3.3 dry-run proof: two complete synthetic slates end to end.

    Exercises the real code paths — expected-schedule registration,
    DECISION and CLOSING intake, pair-validity refusals, watchdog
    reconciliation with a deliberately induced miss, and readout
    generation — against fabricated records only. Slate 2 contains the
    induced miss (watchdog must mark the item INDETERMINATE and fire an
    alert) and both slates contain a contract refusal (a dry run with
    zero refusals across two slates is itself suspicious, section 3.3).

    Returns the proof report; every surface is stamped
    DRY_RUN_NOT_EVIDENCE and the verdict field is NOT_YET by
    construction (accrual counts only — no verdict exists at this size,
    and dry-run output is never model evidence).
    """
    campaign = Campaign(mode="DRY_RUN")
    base = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)  # a Sunday
    slate_reports: list[dict[str, Any]] = []
    for slate_idx, week in ((1, 1), (2, 2)):
        slate_id = f"SYN-SLATE-{slate_idx}"
        kickoff = base + timedelta(days=7 * (slate_idx - 1))
        expected = satisfied = 0
        for g in range(games_per_slate):
            game_id = f"SYN-G{slate_idx}-{g}"
            for kind in ("DECISION", "CLOSING"):
                item_id = f"{game_id}:{kind}"
                campaign.register_expected({
                    "item_id": item_id, "kind": kind, "game_id": game_id,
                    "slate_id": slate_id, "week_block": week,
                    "window_close_utc": _iso(
                        kickoff - timedelta(minutes=45)
                        if kind == "DECISION"
                        else kickoff - timedelta(minutes=2))})
                expected += 1
                if slate_idx == 2 and g == games_per_slate - 1 \
                        and kind == "CLOSING":
                    continue  # the deliberately induced miss
                rec = make_synthetic_game_record(
                    game_id=game_id, week_block=week, kickoff=kickoff,
                    capture_kind=kind, item_id=item_id)
                result = campaign.submit_game_record(rec)
                if result["accepted"]:
                    satisfied += 1
                    if kind == "CLOSING":
                        campaign.submit_settlement(
                            result["record_id"], home_score=27,
                            away_score=20)
        # One contract refusal per slate: a -100 price refuses the pair.
        bad_item = f"SYN-G{slate_idx}-0:DECISION-RETRY"
        campaign.register_expected({
            "item_id": bad_item, "kind": "DECISION",
            "game_id": f"SYN-G{slate_idx}-0", "slate_id": slate_id,
            "week_block": week,
            "window_close_utc": _iso(kickoff - timedelta(minutes=45))})
        expected += 1
        bad = make_synthetic_game_record(
            game_id=f"SYN-G{slate_idx}-0", week_block=week, kickoff=kickoff,
            capture_kind="DECISION", item_id=bad_item)
        bad["pairs"]["MONEYLINE"]["sides"][0]["price"] = -100
        result = campaign.submit_game_record(bad)
        assert not result["accepted"]  # refusal occurred and logged
        slate_reports.append({"slate_id": slate_id, "expected": expected,
                              "submitted_satisfied": satisfied})
    counts = campaign.reconcile(now=base + timedelta(days=8))
    readouts = {fam: game_leg_readout(campaign, fam)
                for fam in GAME_FAMILIES}
    refusals = [r for r in campaign.refusals]
    report: dict[str, Any] = {
        "proof": "TWO_SLATE_DRY_RUN",
        "design_id": DESIGN_ID,
        "activation_state": ACTIVATION_STATE,
        "stamp": DRY_RUN_STAMP,
        "evidence_admissible": False,
        "research_only": True,
        "verdict": "NOT_YET",
        "label": ACCRUAL_LABEL,
        "slates": slate_reports,
        "reconciliation_counts": counts,
        "refusals": refusals,
        "alerts": campaign.alerts,
        "readouts": {fam: {"status": r["status"], "label": r["label"],
                           "counts": r["counts"]}
                     for fam, r in readouts.items()},
    }
    if not refusals:
        report["warning"] = "DRY_RUN_ZERO_REFUSALS_SUSPICIOUS"
    return report
