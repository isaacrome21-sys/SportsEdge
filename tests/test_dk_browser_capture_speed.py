"""Offline synthetic speed diagnostics, no real browser/session/secret involved."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json

import pytest

from sportsedge.dk_browser_capture_speed_diag import (
    CaptureDiagError, diagnose_capture_timing, VERSION,
)


def log(*, slow=False, captcha=False):
    base = datetime(2026, 10, 21, 19, 0, tzinfo=timezone.utc)
    fixture = "NFL-TEST-GAME-NE-CHI"
    events = []
    def event(second, name, **extras):
        events.append({
            "fixture_id": fixture, "event": name,
            "timestamp_utc": (base + timedelta(seconds=second)).isoformat(),
            **extras,
        })
    event(0, "capture_started")
    event(5, "stage_begin", stage="navigate")
    event(40 if not slow else 140, "stage_end", stage="navigate")
    event(41 if not slow else 141, "stage_begin", stage="pairing")
    event(54 if not slow else 154, "stage_end", stage="pairing")
    event(58 if not slow else 158, "quote_pair_captured",
          pair_span_seconds=12, quote_receipt_hash="a" * 64)
    event(85 if not slow else 195, "final_quote_re_read")
    if captcha:
        event(87 if not slow else 197, "captcha_seen")
    event(100 if not slow else 210, "capture_finished")
    return {"version": VERSION, "events": events}


def test_good_measurement_only_never_attests_a_quote():
    r = diagnose_capture_timing(log())
    assert r["status"] == "CAPTURE_SPEED_DIAGNOSTICS_ONLY"
    assert r["aggregate"]["fixture_count"] == 1
    row = r["fixtures"][0]
    assert row["capture_span_seconds"] == 100
    assert row["quote_age_at_finish_seconds"] == 42
    assert row["dominant_measured_stage"] == "navigate"
    assert row["dominant_stage_seconds"] == 35
    assert row["outcome_pair_span_seconds"] == 12
    assert row["causes"] == ["TIMING_ONLY_WITHIN_BOUNDS_UNVERIFIED"]
    assert not row["quote_verified"]
    assert not row["play_authority"]
    assert r["governance"]["no_captcha_bypass"]
    assert "NFL-TEST-GAME-NE-CHI" not in json.dumps(r)


def test_capture_over_budget_and_captcha_have_named_causes():
    r = diagnose_capture_timing(log(slow=True, captcha=True))
    row = r["fixtures"][0]
    assert row["capture_span_seconds"] == 210
    assert "CAPTURE_SPAN_GT_150S" in row["causes"]
    assert "CAPTCHA_OBSERVED_OPERATOR_REQUIRED" in row["causes"]
    assert row["dominant_measured_stage"] == "navigate"


def test_stale_age_and_unpaired_quote_are_kept_refused():
    raw = log(slow=True)
    raw["events"][-2]["event"] = "throttle_seen"
    raw["events"][-1]["timestamp_utc"] = (
        "2026-10-21T19:07:00+00:00")
    r = diagnose_capture_timing(raw)
    row = r["fixtures"][0]
    assert "QUOTE_AGE_GT_180S" in row["causes"]
    assert "FINAL_RE_READ_MISSING_OR_PRE_QUOTE" in row["causes"]
    assert "PROVIDER_THROTTLE_OBSERVED" in row["causes"]


def test_pair_span_150_second_fence_is_not_weakened():
    raw = log()
    paired = next(e for e in raw["events"]
                  if e["event"] == "quote_pair_captured")
    paired["pair_span_seconds"] = 151
    r = diagnose_capture_timing(raw)
    assert "PAIR_SPAN_GT_150S" in r["fixtures"][0]["causes"]


@pytest.mark.parametrize("field", ["cookie", "api_key", "url", "client_ip", "raw_html"])
def test_sensitive_event_fields_refused(field):
    p = log()
    p["events"][0][field] = "SECRET-DONT-SAVE"
    with pytest.raises(CaptureDiagError,
                       match="FORBIDDEN_SENSITIVE_CAPTURE_FIELDS"):
        diagnose_capture_timing(p)


def test_negative_or_missing_pair_span_refused():
    p = log()
    pair = next(e for e in p["events"]
                if e["event"] == "quote_pair_captured")
    pair["pair_span_seconds"] = -1
    with pytest.raises(CaptureDiagError, match="PAIR_SPAN_REQUIRED"):
        diagnose_capture_timing(p)


def test_nonmonotonic_capture_timing_refused():
    p = log()
    p["events"][1], p["events"][2] = p["events"][2], p["events"][1]
    with pytest.raises(CaptureDiagError, match="NONMONOTONIC_TIMING_EVENTS"):
        diagnose_capture_timing(p)


def test_missing_stage_end_and_missing_final_capture_refused():
    p = log()
    p["events"] = [e for e in p["events"]
                   if not (e["event"] == "stage_end" and e["stage"] == "pairing")]
    with pytest.raises(CaptureDiagError, match="UNFINISHED_TIMING_STAGE"):
        diagnose_capture_timing(p)
    p = log()
    p["events"] = [e for e in p["events"]
                   if e["event"] != "capture_finished"]
    with pytest.raises(CaptureDiagError, match="INCOMPLETE_CAPTURE_TIMING_RECEIPT"):
        diagnose_capture_timing(p)


def test_summary_aggregation_for_distinct_fixtures():
    a = log()
    b = log(slow=True)
    for entry in b["events"]:
        entry["fixture_id"] = "NFL-TEST-SECOND-GAME"
    out = diagnose_capture_timing({
        "version": VERSION, "events": a["events"] + b["events"]})
    assert out["aggregate"]["fixture_count"] == 2
    assert out["aggregate"]["capture_p90_seconds"] == 210
    assert len(set(x["fixture_hash12"] for x in out["fixtures"])) == 2
