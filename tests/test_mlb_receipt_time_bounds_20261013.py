"""Receipt time is always the post-fetch clock; caller times are bounded and separate."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge import mlb_source as ms

T0 = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
SCHED = {"dates": [{"date": "2026-10-13", "games": [{
    "gamePk": 1, "gameDate": "2026-10-13T23:08:00Z", "gameType": "L", "status": {"abstractGameState": "Preview"},
    "teams": {"away": {"team": {"id": 10, "name": "A"}}, "home": {"team": {"id": 20, "name": "H"}}}}]}]}


class _R:
    def __init__(self, raw): self.raw = raw
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return self.raw


def _clock(*times):
    it = iter(times)
    return lambda: next(it)


def _open(*a, **k):
    return _R(json.dumps(SCHED).encode())


def fetch(now=None, start=T0, end=T0 + timedelta(seconds=2)):
    return ms.fetch_schedule("2026-10-13", opener=_open, now=now, clock=_clock(start, end))


def test_retrieved_at_is_post_fetch_clock_even_when_caller_supplies_now():
    g = fetch(now=T0 + timedelta(seconds=1))[0]
    assert g.retrieved_at == (T0 + timedelta(seconds=2)).isoformat()
    assert g.caller_asserted_at == (T0 + timedelta(seconds=1)).isoformat()
    assert g.game_type == "L"


def test_no_caller_time_leaves_field_empty():
    assert fetch()[0].caller_asserted_at is None


def test_naive_caller_time_fails_closed():
    with pytest.raises(ms.MLBSourceError, match="timezone-aware"):
        fetch(now=datetime(2026, 10, 13, 16, 0, 1))


def test_caller_time_before_fetch_start_fails_closed():
    with pytest.raises(ms.MLBSourceError, match="BEFORE_FETCH_START"):
        fetch(now=T0 - timedelta(seconds=1))


def test_future_caller_time_fails_closed_beyond_skew():
    assert fetch(now=T0 + timedelta(seconds=2) + ms.RECEIPT_CLOCK_SKEW)  # at the bound: allowed
    with pytest.raises(ms.MLBSourceError, match="IN_FUTURE"):
        fetch(now=T0 + timedelta(seconds=2) + ms.RECEIPT_CLOCK_SKEW + timedelta(microseconds=1))


def test_naive_or_backwards_receipt_clock_fails_closed():
    with pytest.raises(ms.MLBSourceError):
        fetch(start=datetime(2026, 10, 13, 16, 0))
    with pytest.raises(ms.MLBSourceError, match="BACKWARDS"):
        fetch(start=T0, end=T0 - timedelta(seconds=1))


def test_recorder_clock_bounded(tmp_path):
    ok = ms.MLBSourceCapture(tmp_path, clock=_clock(T0))
    ok.record(url="https://x/api/v1/schedule", raw=b"{}", fetch_started_at=T0)
    with pytest.raises(ms.MLBSourceError, match="BEFORE_FETCH_START"):
        ms.MLBSourceCapture(tmp_path, clock=_clock(T0 - timedelta(seconds=1))).record(
            url="https://x/api/v1/schedule", raw=b"{}", fetch_started_at=T0)
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    with pytest.raises(ms.MLBSourceError, match="IN_FUTURE"):
        ms.MLBSourceCapture(tmp_path, clock=_clock(future)).record(
            url="https://x/api/v1/schedule", raw=b"{}", fetch_started_at=future - timedelta(seconds=1))
    with pytest.raises(ms.MLBSourceError, match="timezone-aware"):
        ms.MLBSourceCapture(tmp_path, clock=_clock(datetime(2026, 10, 13))).record(
            url="https://x/api/v1/schedule", raw=b"{}")


def test_recorder_reads_fetch_start_from_its_own_clock(tmp_path):
    seq = _clock(T0, T0 + timedelta(seconds=1))
    with ms.capture_mlb_source_bytes(tmp_path, clock=seq) as cap:
        ms._get_json("https://x/api/v1/schedule", _open)
    assert cap.records[0].observed_at_utc == (T0 + timedelta(seconds=1)).isoformat()


def test_six_runner_callers_no_longer_pass_pre_fetch_time():
    import inspect
    from sportsedge import (auto_espn_odds, auto_joint_runner, auto_native_odds, auto_runner,
                            canonical_manual_mlb, manual_mlb_snapshot)
    for mod in (auto_runner, auto_joint_runner, auto_espn_odds, auto_native_odds,
                manual_mlb_snapshot, canonical_manual_mlb):
        src = inspect.getsource(mod)
        for line in src.splitlines():
            if "fetch_schedule(" in line and "def " not in line and "import" not in line:
                assert "now=" not in line.split("#")[0], (mod.__name__, line)
