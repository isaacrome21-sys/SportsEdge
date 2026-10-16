"""RED battery for #2359 A: capture-span preflight (180s bound UNCHANGED).

A never rescues a stale row. It (1) measures genuine first-to-last
verification span against a 150s target / 30s margin, (2) orders
candidate-critical sections last, (3) requires a genuine final re-read
record for every stamped quote, (4) anchors as-of to the actual final
verification instant and refuses every row >180s against it.
"""
from datetime import datetime, timedelta, timezone

import pytest

from _capture_receipt_fixtures import receipts_for
from sportsedge import capture_preflight as cp
from sportsedge.quote_freshness import MAX_QUOTE_AGE_SECONDS

import re
from datetime import datetime as _dt_
T0 = datetime(2026, 10, 15, 23, 0, 0, tzinfo=timezone.utc)

def _ev(rows):
    from datetime import datetime as _dt
    best = None
    for r in rows:
        if not isinstance(r.get("verification"), dict):
            continue
        try:
            t = _dt.fromisoformat(str(r["quote_captured_at"]).replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if t.tzinfo is None:
            continue
        best = t if best is None or t > best else best
    return (best or T0).isoformat()


def _clock_for(rows):
    finals = {}
    for r in rows:
        g = re.sub(r"\s+", "", str(r.get("game_id"))).upper()
        try:
            t = _dt_.fromisoformat(str(r["quote_captured_at"]).replace("Z", "+00:00"))
        except (ValueError, KeyError):
            continue
        if t.tzinfo is None or not isinstance(r.get("verification"), dict):
            continue
        finals[g] = max(finals.get(g, t), t)
    return lambda g: finals.get(g, T0)



def iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def row(rid, sec, *, critical=False, verified=True, read_id=None, game="NLCS-G5"):
    cap = T0 + timedelta(seconds=sec)
    r = {"row_id": rid, "game_id": game, "market": "m", "quote_captured_at": iso(cap),
         "candidate_critical": critical}
    if verified:
        r["verification"] = {"read_id": read_id or f"read-{rid}", "verified_at": iso(cap),
                             "row_id": rid, "reread": True}
    return r


def test_bound_and_target_constants_unchanged():
    assert MAX_QUOTE_AGE_SECONDS == 180
    assert cp.TARGET_CAPTURE_SPAN_SECONDS == 150
    assert cp.SAFETY_MARGIN_SECONDS == 30
    assert cp.TARGET_CAPTURE_SPAN_SECONDS + cp.SAFETY_MARGIN_SECONDS == MAX_QUOTE_AGE_SECONDS


def test_oct15_217s_capture_refuses_197s_rows_reordering_cannot_rescue():
    rows = [row("tt", 20, critical=True), row("fi", 20, critical=True),
            row("gl", 177), row("p", 136), row("last", 217)]
    out = cp.preflight(rows, receipts=receipts_for(rows), evaluated_at=_ev(rows))
    assert out["as_of_utc"] == iso(T0 + timedelta(seconds=217))
    status = {r["row_id"]: r["freshness_code"] for r in out["rows"]}
    assert status["tt"] == "QUOTE_STALE_OVER_180S"
    assert status["fi"] == "QUOTE_STALE_OVER_180S"
    assert status["gl"] == "QUOTE_FRESH_UNDER_180S"
    assert out["span_seconds"] == 197.0
    assert out["span_status"] == cp.SPAN_OVER_BOUND
    assert {r["row_id"] for r in out["refused"]} == {"tt", "fi"}
    # Reordering the same timestamps changes nothing.
    out2 = cp.preflight(list(reversed(rows)), receipts=receipts_for(list(reversed(rows))), evaluated_at=_ev(list(reversed(rows))))
    assert {r["row_id"] for r in out2["refused"]} == {"tt", "fi"}


def test_boundaries_180_000_fresh_180_001_stale():
    out = (lambda _r: cp.preflight(_r, receipts=receipts_for(_r), evaluated_at=_ev(_r)))([row("a", 0), row("z", 180)])
    assert not out["refused"]
    assert out["span_status"] == cp.SPAN_OVER_TARGET  # 180 > 150 target, still legal
    r = [row("a", 0), row("z", 180.001)]
    out = cp.preflight(r, receipts=receipts_for(r), evaluated_at=_ev(r))
    assert [x["row_id"] for x in out["refused"]] == ["a"]


def test_span_within_target():
    out = (lambda _r: cp.preflight(_r, receipts=receipts_for(_r), evaluated_at=_ev(_r)))([row("a", 0), row("z", 150)])
    assert out["span_status"] == cp.SPAN_WITHIN_TARGET
    assert not out["refused"]


def test_unverified_row_refused_never_stamped():
    rows = [row("a", 0), row("b", 10, verified=False)]
    out = cp.preflight(rows, receipts=receipts_for(rows), evaluated_at=_ev(rows))
    ref = {r["row_id"]: r["refusal_code"] for r in out["refused"]}
    assert ref == {"b": cp.REFUSE_NO_FINAL_VERIFICATION}


def test_verification_must_match_capture_and_row():
    a = row("a", 0)
    a["verification"]["verified_at"] = iso(T0 + timedelta(seconds=30))  # redated
    b = row("b", 5)
    b["verification"]["row_id"] = "other"
    c = row("c", 6)
    c["verification"]["reread"] = False
    out = (lambda _r: cp.preflight(_r, receipts=receipts_for(_r), evaluated_at=_ev(_r)))([a, b, c, row("d", 7)])
    ref = {r["row_id"]: r["refusal_code"] for r in out["refused"]}
    assert ref["a"] == cp.REFUSE_VERIFICATION_TIMESTAMP_MISMATCH
    assert ref["b"] == cp.REFUSE_VERIFICATION_ROW_MISMATCH
    assert ref["c"] == cp.REFUSE_NO_FINAL_VERIFICATION
    assert "d" not in ref


def test_as_of_is_final_verification_instant_not_wall_clock():
    rows = [row("a", 0), row("b", 60)]
    out = cp.preflight(rows, receipts=receipts_for(rows), evaluated_at=_ev(rows))
    assert out["as_of_utc"] == iso(T0 + timedelta(seconds=60))
    with pytest.raises(ValueError, match="AS_OF_NOT_FINAL_VERIFICATION"):
        cp.preflight(rows, receipts=receipts_for(rows), evaluated_at=_ev(rows), declared_as_of=iso(T0 + timedelta(seconds=90)))
    # Declaring exactly the final read instant is accepted.
    assert cp.preflight(rows, receipts=receipts_for(rows), evaluated_at=_ev(rows), declared_as_of=iso(T0 + timedelta(seconds=60)))["as_of_utc"]


def test_future_negative_and_malformed_timezone_refuse():
    a = row("a", 0)
    bad = row("tz", 5)
    bad["quote_captured_at"] = "2026-10-15T23:00:05"
    bad["verification"]["verified_at"] = "2026-10-15T23:00:05"
    out = (lambda _r: cp.preflight(_r, receipts=receipts_for(_r), evaluated_at=_ev(_r)))([a, bad, row("z", 10)])
    ref = {r["row_id"]: r["refusal_code"] for r in out["refused"]}
    assert ref["tz"].startswith("QUOTE_TIMESTAMP_INVALID")


def test_input_timestamps_never_mutated():
    rows = [row("a", 0), row("z", 200)]
    receipts_for(rows)  # adapter stamps raw-read hashes at capture time
    before = [dict(r, verification=dict(r["verification"])) for r in rows]
    out = cp.preflight(rows, receipts=receipts_for(rows), evaluated_at=_ev(rows))
    assert rows == before
    for r in out["rows"]:
        src = next(x for x in rows if x["row_id"] == r["row_id"])
        assert r["quote_captured_at"] == src["quote_captured_at"]


def test_capture_order_puts_candidate_critical_last():
    sections = [{"section": "tt", "candidate_critical": True},
                {"section": "gl", "candidate_critical": False},
                {"section": "fi", "candidate_critical": True},
                {"section": "pk", "candidate_critical": False}]
    order = [s["section"] for s in cp.capture_order(sections)]
    assert order == ["gl", "pk", "tt", "fi"]


def test_preflight_is_research_only_and_records_failed_refresh():
    rows = [row("a", 0), row("z", 200)]
    out = cp.preflight(rows, receipts=receipts_for(rows), evaluated_at=_ev(rows), failed_refresh_attempts=[{"row_id": "a", "at": iso(T0 + timedelta(seconds=199)), "reason": "tile_gone"}])
    assert out["research_only"] is True
    assert out["failed_refresh_attempts"][0]["row_id"] == "a"
    assert "stake" not in out and "ev" not in out


def test_empty_capture_refuses():
    with pytest.raises(ValueError, match="NO_VERIFIED_ROWS"):
        (lambda _r: cp.preflight(_r, receipts=receipts_for(_r), evaluated_at=_ev(_r)))([row("a", 0, verified=False)])
