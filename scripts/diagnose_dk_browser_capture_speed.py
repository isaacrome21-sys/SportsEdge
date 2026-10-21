"""Offline, read-only timing diagnosis for rendered-browser DK capture receipts.

Consumes ONLY sanitized timing events, never cookies, pages, URLs,
screen captures, prices or authentication material. It does not make
browser requests and cannot attest to a DK quote. It measures the
agreed <=150s capture window and <=180s quote-age boundary, and names
the stage contributing the most measured delay.

Never change capture governance on these diagnostics; a timed-out or
stale capture stays refused until a new independently verified capture.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping

VERSION = "DK_CAPTURE_SPEED_DIAG_V1"
CAPTURE_SPAN_TARGET_S = 150.0
QUOTE_MAX_AGE_S = 180.0
PAIR_SPAN_MAX_S = 150.0
STAGES = frozenset({
    "navigate", "render_wait", "market_expand", "quote_transcription",
    "pairing", "final_re_read", "receipt_write",
})
EVENTS = frozenset({
    "capture_started", "stage_begin", "stage_end",
    "quote_pair_captured", "capture_finished",
    "throttle_seen", "captcha_seen", "final_quote_re_read",
})
EVENT_FIELDS = frozenset({
    "fixture_id", "event", "timestamp_utc", "stage",
    "pair_span_seconds", "quote_receipt_hash",
})


class CaptureDiagError(ValueError):
    """Safe non-sensitive validation refusal."""


def _time(raw: Any) -> datetime:
    if not isinstance(raw, str) or not raw.strip():
        raise CaptureDiagError("MISSING_EVENT_TIMESTAMP")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CaptureDiagError("INVALID_EVENT_TIMESTAMP") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise CaptureDiagError("TIMESTAMP_UTC_OFFSET_REQUIRED")
    return dt.astimezone(timezone.utc)


def _percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    # nearest rank is explicit and deterministic for short samples.
    rank = max(0, math.ceil(len(ordered) * percent / 100) - 1)
    return round(float(ordered[rank]), 3)


def diagnose_capture_timing(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate timing only; hash raw fixture IDs before returning."""
    if not isinstance(payload, Mapping) or payload.get("version") != VERSION:
        raise CaptureDiagError("VERSIONED_TIMING_ENVELOPE_REQUIRED")
    if set(payload) != {"version", "events"}:
        raise CaptureDiagError("UNEXPECTED_TIMING_ENVELOPE_FIELDS")
    events = payload["events"]
    if not isinstance(events, list) or not events:
        raise CaptureDiagError("NONEMPTY_TIMING_EVENTS_REQUIRED")
    grouped = defaultdict(list)
    for item in events:
        if not isinstance(item, Mapping) or set(item) - EVENT_FIELDS:
            raise CaptureDiagError("FORBIDDEN_SENSITIVE_CAPTURE_FIELDS")
        fixture = item.get("fixture_id")
        if not isinstance(fixture, str) or not fixture or len(fixture) > 256:
            raise CaptureDiagError("FIXTURE_ID_REQUIRED")
        event = item.get("event")
        if event not in EVENTS:
            raise CaptureDiagError("UNKNOWN_TIMING_EVENT")
        stage = item.get("stage")
        if event in {"stage_begin", "stage_end"}:
            if stage not in STAGES:
                raise CaptureDiagError("UNKNOWN_TIMING_STAGE")
        elif stage is not None:
            raise CaptureDiagError("STAGE_ONLY_ON_BEGIN_END")
        span = item.get("pair_span_seconds")
        if event == "quote_pair_captured":
            if isinstance(span, bool) or not isinstance(span, (int, float)) or (
                    not math.isfinite(span) or span < 0):
                raise CaptureDiagError("PAIR_SPAN_REQUIRED")
            digest = item.get("quote_receipt_hash")
            if not isinstance(digest, str) or len(digest) != 64 or (
                    any(c not in "0123456789abcdefABCDEF" for c in digest)):
                raise CaptureDiagError("QUOTE_RECEIPT_HASH_REQUIRED")
        elif span is not None or item.get("quote_receipt_hash") is not None:
            raise CaptureDiagError("PAIR_DATA_ONLY_ON_CAPTURE")
        grouped[fixture].append((_time(item.get("timestamp_utc")), event,
                                 stage, span))
    results = []
    per_stage = defaultdict(list)
    global_causes = defaultdict(int)
    for fixture, records in grouped.items():
        if records != sorted(records, key=lambda x: x[0]):
            raise CaptureDiagError("NONMONOTONIC_TIMING_EVENTS")
        started = None
        finished = None
        last_pair = None
        pair_span = None
        active = {}
        stage_durations = defaultdict(float)
        throttle = 0
        captcha = 0
        reread = None
        for instant, event, stage, span in records:
            if event == "capture_started":
                if started is not None or finished is not None:
                    raise CaptureDiagError("MULTIPLE_CAPTURE_STARTS")
                started = instant
            elif started is None or finished is not None:
                raise CaptureDiagError("EVENT_OUTSIDE_CAPTURE_WINDOW")
            elif event == "capture_finished":
                if active:
                    raise CaptureDiagError("UNFINISHED_TIMING_STAGE")
                finished = instant
            elif event == "stage_begin":
                if stage in active:
                    raise CaptureDiagError("DUPLICATE_ACTIVE_STAGE")
                active[stage] = instant
            elif event == "stage_end":
                if stage not in active:
                    raise CaptureDiagError("STAGE_END_WITHOUT_BEGIN")
                elapsed = (instant - active.pop(stage)).total_seconds()
                if elapsed < 0:
                    raise CaptureDiagError("NEGATIVE_STAGE_DURATION")
                stage_durations[stage] += elapsed
                per_stage[stage].append(elapsed)
            elif event == "quote_pair_captured":
                last_pair, pair_span = instant, float(span)
            elif event == "final_quote_re_read":
                reread = instant
            elif event == "throttle_seen":
                throttle += 1
            elif event == "captcha_seen":
                captcha += 1
        if started is None or finished is None or last_pair is None:
            raise CaptureDiagError("INCOMPLETE_CAPTURE_TIMING_RECEIPT")
        duration = (finished - started).total_seconds()
        quote_age = (finished - last_pair).total_seconds()
        if duration < 0 or quote_age < 0:
            raise CaptureDiagError("CAPTURE_TIMING_CHRONOLOGY_INVALID")
        causes = []
        if duration > CAPTURE_SPAN_TARGET_S:
            causes.append("CAPTURE_SPAN_GT_150S")
        if quote_age > QUOTE_MAX_AGE_S:
            causes.append("QUOTE_AGE_GT_180S")
        if pair_span > PAIR_SPAN_MAX_S:
            causes.append("PAIR_SPAN_GT_150S")
        if reread is None or reread < last_pair:
            causes.append("FINAL_RE_READ_MISSING_OR_PRE_QUOTE")
        if throttle:
            causes.append("PROVIDER_THROTTLE_OBSERVED")
        if captcha:
            causes.append("CAPTCHA_OBSERVED_OPERATOR_REQUIRED")
        if not causes:
            causes.append("TIMING_ONLY_WITHIN_BOUNDS_UNVERIFIED")
        for code in causes:
            global_causes[code] += 1
        slowest = max(stage_durations, key=stage_durations.get) if stage_durations else None
        results.append({
            "fixture_hash12": hashlib.sha256(fixture.encode()).hexdigest()[:12],
            "capture_span_seconds": duration,
            "quote_age_at_finish_seconds": quote_age,
            "outcome_pair_span_seconds": pair_span,
            "dominant_measured_stage": slowest,
            "dominant_stage_seconds": stage_durations.get(slowest, 0.0),
            "stage_seconds": dict(sorted(stage_durations.items())),
            "causes": causes,
            "research_only": True,
            "quote_verified": False, "play_authority": False,
        })
    return {
        "version": VERSION, "status": "CAPTURE_SPEED_DIAGNOSTICS_ONLY",
        "fixtures": sorted(results, key=lambda x: x["fixture_hash12"]),
        "aggregate": {
            "fixture_count": len(results),
            "capture_p50_seconds": median(
                [f["capture_span_seconds"] for f in results]),
            "capture_p90_seconds": _percentile(
                [f["capture_span_seconds"] for f in results], 90),
            "cause_counts": dict(sorted(global_causes.items())),
            "stage_p90_seconds": {
                name: _percentile(samples, 90)
                for name, samples in sorted(per_stage.items())},
        },
        "governance": {
            "not_a_quote_receipt": True,
            "provider_capture_not_performed": True,
            "capture_freshness_not_attested": True,
            "no_captcha_bypass": True,
            "no_gates_or_eligibility_changes": True,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(
        "Sanitized offline rendered-browser timing diagnostics only"))
    parser.add_argument("--timing-json", required=True)
    parser.add_argument("--output-json")
    args = parser.parse_args(argv)
    try:
        with open(args.timing_json, "r", encoding="utf-8") as file:
            payload = json.load(file)
        report = diagnose_capture_timing(payload)
        if args.output_json:
            dest = Path(args.output_json)
            dest.parent.mkdir(parents=True, exist_ok=True)
            temp = dest.with_suffix(dest.suffix + ".tmp")
            temp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
            temp.replace(dest)
        print(json.dumps({
            "status": report["status"],
            "fixture_count": report["aggregate"]["fixture_count"],
            "cause_counts": report["aggregate"]["cause_counts"],
        }, sort_keys=True))
        return 0
    except CaptureDiagError as exc:
        print(json.dumps({"status": str(exc), "research_only": True}))
        return 78
    except (OSError, ValueError, TypeError):
        print(json.dumps({"status": "INVALID_TIMING_SOURCE", "research_only": True}))
        return 79


if __name__ == "__main__":
    raise SystemExit(main())
