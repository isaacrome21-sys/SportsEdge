"""Count-admission gate — NBA Team Totals Forward Test V1.

The pinned evaluator (`eval_nba_team_totals_v1.py`, sha256 attested in
`EVALUATOR_PIN.md`) is a pure scoring function of caller-supplied records
and config. It is NOT a count boundary: a direct caller could supply a
backdated `first_counted_slate` or non-frozen statistical settings and
obtain scored output for rows the frozen test never authorized.

This module is the mandatory forward-ledger write boundary for counted
publication. Every counted row/metric/verdict for this forward test is
published exclusively through `publish_counted`, which:

1. requires a trusted, immutable pin-push receipt (canonical path beside
   this module; the receipt file's sha256 must equal the hash pinned in
   this module and in `COUNT_GATE_PIN.md`). No receipt is installed by
   default: `RECEIPT_SHA256 is None` and the gate fails closed. A receipt
   is installed only by a governed act — receipt file, this module's
   pinned hash, and `COUNT_GATE_PIN.md` updated in one reviewed commit;
2. verifies the evaluator's actual bytes against the pinned sha256
   attested in `EVALUATOR_PIN.md` before any scoring;
3. derives the evaluation config itself — the frozen k / seed / resamples
   from the evaluator's frozen constants, the clock identities recorded
   in `FREEZE_RECORD.md`, and the first counted slate named by the
   receipt. Caller config may only repeat those values exactly; any
   deviation or extra key (including any caller-supplied pin time)
   refuses the publication;
4. requires every submitted row's `priced_at` and every entry quote's
   `captured_at` to be strictly AFTER the receipt's pin-push time, and
   every slate to be on/after the receipt's first counted slate — the
   evaluator pin's rule: nothing priced at or before the pin-push time
   counts. One pre-pin row refuses the whole publication;
5. only then invokes the pinned evaluator, and appends exactly one
   publication record to the forward ledger.

On any refusal the gate raises `CountAdmissionRefused` with a named
`code`, the evaluator is never invoked, and zero counted rows/metrics
are emitted (nothing is written to the ledger). Research-only;
play_allowed=false; PAPER / 0u.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import eval_nba_team_totals_v1 as ev

HERE = Path(__file__).resolve().parent

GATE_VERSION = "NBA_TT_COUNT_GATE_V1_1"

# The evaluator identity this gate admits: the sha256 attested in
# EVALUATOR_PIN.md for the evaluator pinned at commit PIN_COMMIT.
PINNED_EVALUATOR_SHA256 = (
    "63db53129556de7a2d007020aebda9b1a5ed2ede7e4a5a0053ba6aaa2b761be9")
PIN_COMMIT = "37b541745154fb73985e761f7b21a7ba7a8b2381"

# Trusted pin-push receipt: canonical location and pinned content hash.
# No receipt has been issued under governance yet, so the pinned hash is
# None and every counted publication is refused (fail closed) until a
# receipt is installed by a reviewed commit (see COUNT_GATE_PIN.md).
RECEIPT_PATH = HERE / "PIN_PUSH_RECEIPT.json"
RECEIPT_SHA256 = None

DEFAULT_LEDGER_PATH = HERE / "forward_ledger_nba_team_totals_v1.jsonl"

# Canonical clock identities, recorded in FREEZE_RECORD.md at freeze
# (k = 9). The counted config is derived from this record and the
# evaluator's frozen constants — never from caller preference.
CANONICAL_CLOCK_IDS = [
    "NFL_PROPS_PART2_FORWARD_V1",
    "NFL_PROPS_PART2B_FORWARD_V1",
    "NFL_PROPS_V1_1_MOVED_LINE_AMENDMENT",
    "NBA_PROPS_FORWARD_V1",
    "NFL_TOTALS_LEVEL_V2_FORWARD",
    "MLB_PITCHER_PROP_PROMOTION_V2",
    "NFL_ANYTIME_TD_FORWARD_V1",
    "NFL_PASSYDS_V2_FORWARD_SCREEN",
    "NBA_TEAM_TOTALS_FORWARD_V1",
]

_CONFIG_KEYS = {"first_counted_slate", "k", "seed", "resamples",
                "clock_ids"}


class CountAdmissionRefused(RuntimeError):
    """Named fail-closed refusal at the counted-publication boundary."""

    def __init__(self, code, detail=""):
        self.code = code
        super().__init__(code if not detail else f"{code}: {detail}")


def _aware(t):
    """Aware datetime or None (unparseable / zoneless is untrusted)."""
    try:
        dt = datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo is not None else None


def _load_receipt(receipt_path, receipt_sha256):
    """Return the validated receipt dict, or raise a named refusal."""
    if receipt_sha256 is None:
        raise CountAdmissionRefused("TRUSTED_PIN_PUSH_RECEIPT_UNAVAILABLE",
                                    "no receipt hash pinned in gate")
    if not receipt_path.is_file():
        raise CountAdmissionRefused("TRUSTED_PIN_PUSH_RECEIPT_UNAVAILABLE",
                                    f"no receipt at {receipt_path.name}")
    raw = receipt_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != receipt_sha256:
        raise CountAdmissionRefused("PIN_PUSH_RECEIPT_HASH_MISMATCH",
                                    f"receipt sha256 {digest}")
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise CountAdmissionRefused("PIN_PUSH_RECEIPT_MALFORMED")
    if receipt.get("evaluator_sha256") != PINNED_EVALUATOR_SHA256:
        raise CountAdmissionRefused("PIN_PUSH_RECEIPT_CONTENT_MISMATCH",
                                    "evaluator_sha256")
    if receipt.get("pin_commit") != PIN_COMMIT:
        raise CountAdmissionRefused("PIN_PUSH_RECEIPT_CONTENT_MISMATCH",
                                    "pin_commit")
    pin_time = _aware(receipt.get("pin_push_time_utc"))
    if pin_time is None:
        raise CountAdmissionRefused("PIN_PUSH_RECEIPT_CONTENT_MISMATCH",
                                    "pin_push_time_utc")
    first = str(receipt.get("first_counted_slate") or "")
    try:
        datetime.strptime(first, "%Y-%m-%d")
    except ValueError:
        raise CountAdmissionRefused("PIN_PUSH_RECEIPT_CONTENT_MISMATCH",
                                    "first_counted_slate")
    receipt["_pin_time"] = pin_time
    receipt["_sha256"] = digest
    return receipt


def _canonical_config(receipt):
    return {"first_counted_slate": receipt["first_counted_slate"],
            "k": ev.FROZEN_K, "seed": ev.FROZEN_SEED,
            "resamples": ev.FROZEN_RESAMPLES,
            "clock_ids": list(CANONICAL_CLOCK_IDS)}


def _check_caller_config(caller_config, canonical):
    if caller_config is None:
        return
    if not isinstance(caller_config, dict):
        raise CountAdmissionRefused("FROZEN_EVALUATION_CONFIG_UNAUTHORIZED",
                                    "config is not a mapping")
    for key, value in caller_config.items():
        if key not in _CONFIG_KEYS or value != canonical.get(key):
            raise CountAdmissionRefused(
                "FROZEN_EVALUATION_CONFIG_UNAUTHORIZED",
                f"caller config key {key!r} deviates from the frozen "
                "record / receipt")


def _check_provenance(rows, entry_quotes, receipt):
    pin_time = receipt["_pin_time"]
    first = receipt["first_counted_slate"]
    for r in rows:
        if str(r.get("slate_date")) < first:
            raise CountAdmissionRefused(
                "COUNTED_ROW_PRE_PIN",
                f"slate {r.get('slate_date')} before first counted "
                f"slate {first}")
        pat = _aware(r.get("priced_at"))
        if pat is None:
            raise CountAdmissionRefused(
                "COUNTED_PROVENANCE_TIMESTAMP_INVALID",
                "row priced_at unparseable or zoneless")
        if pat <= pin_time:
            raise CountAdmissionRefused(
                "COUNTED_ROW_PRE_PIN",
                "row priced at or before the pin-push time")
    for q in entry_quotes:
        cat = _aware(q.get("captured_at"))
        if cat is None:
            raise CountAdmissionRefused(
                "COUNTED_PROVENANCE_TIMESTAMP_INVALID",
                "entry quote captured_at unparseable or zoneless")
        if cat <= pin_time:
            raise CountAdmissionRefused(
                "COUNTED_ROW_PRE_PIN",
                "entry quote captured at or before the pin-push time")


def publish_counted(rows, entry_quotes, close_quotes, results, slates,
                    missing_offers, caller_config=None, *,
                    ledger_path=None, receipt_path=None,
                    receipt_sha256=None):
    """The mandatory counted-publication boundary for this forward test.

    Refuses caller-supplied receipt locations/digests by name before scoring.
    Verifies the internally pinned pin-push receipt, the pinned evaluator bytes,
    the frozen config, and per-row post-pin provenance; only then runs
    the pinned evaluator and appends one publication record to the
    forward ledger. Any failure raises CountAdmissionRefused before the
    evaluator is invoked and writes nothing.
    """
    # Explicit caller overrides are never receipt authority. The arguments
    # remain only so legacy callers get a named refusal before any scoring.
    if receipt_path is not None or receipt_sha256 is not None:
        raise CountAdmissionRefused("CALLER_RECEIPT_OVERRIDE_FORBIDDEN")
    receipt = _load_receipt(RECEIPT_PATH, RECEIPT_SHA256)
    evaluator_sha = hashlib.sha256(
        Path(ev.__file__).read_bytes()).hexdigest()
    if evaluator_sha != PINNED_EVALUATOR_SHA256:
        raise CountAdmissionRefused("EVALUATOR_PIN_MISMATCH",
                                    f"evaluator sha256 {evaluator_sha}")
    config = _canonical_config(receipt)
    _check_caller_config(caller_config, config)
    _check_provenance(rows, entry_quotes, receipt)
    out = ev.evaluate(rows, entry_quotes, close_quotes, results, slates,
                      missing_offers, config)
    if out.get("binding") is not True:
        raise CountAdmissionRefused("COUNTED_EVALUATION_NOT_BINDING")
    record = {
        "gate": GATE_VERSION,
        "gate_evaluator_sha256": evaluator_sha,
        "pin_commit": PIN_COMMIT,
        "pin_push_receipt_sha256": receipt["_sha256"],
        "first_counted_slate": receipt["first_counted_slate"],
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
        "counts": out["counts"],
        "verdict": out.get("verdict"),
        "verdict_reason": out.get("verdict_reason"),
        "review_slate": out.get("review_slate"),
        "metrics": out.get("metrics"),
        "play_authority": False,
        "eligible": False,
    }
    path = DEFAULT_LEDGER_PATH if ledger_path is None else ledger_path
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return {"gate": GATE_VERSION, "ledger_path": str(path),
            "record": record, "evaluation": out}
