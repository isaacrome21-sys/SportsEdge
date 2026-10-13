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
    """Yield the given times in order, then keep returning the last one."""
    seq = list(times)

    def nxt():
        return seq.pop(0) if len(seq) > 1 else seq[0]
    return nxt


def _open(*a, **k):
    return _R(json.dumps(SCHED).encode())


def fetch(now=None, start=T0, end=T0 + timedelta(seconds=2), monkeypatch=None):
    import unittest.mock as um
    with um.patch.object(ms, "_trusted_now", _clock(start, end)):  # tests only
        return ms.fetch_schedule("2026-10-13", opener=_open, now=now)


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


def _trusted(*times):
    import unittest.mock as um
    return um.patch.object(ms, "_trusted_now", _clock(*times))


def test_fetch_schedule_has_no_injectable_clock():
    import inspect
    assert "clock" not in inspect.signature(ms.fetch_schedule).parameters


def test_recorder_valid_clock_within_trusted_window(tmp_path):
    with _trusted(T0, T0 + timedelta(seconds=1)):
        with ms.capture_mlb_source_bytes(tmp_path, clock=lambda: T0 + timedelta(milliseconds=500)) as cap:
            ms._get_json("https://x/api/v1/schedule", _open)
    assert cap.records[0].observed_at_utc == (T0 + timedelta(milliseconds=500)).isoformat()


def test_adversarial_year_2000_recorder_clock_rejected(tmp_path):
    y2k = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with _trusted(T0, T0 + timedelta(seconds=1)):
        with ms.capture_mlb_source_bytes(tmp_path, clock=lambda: y2k):
            with pytest.raises(ms.MLBSourceError, match="BEFORE_FETCH_START"):
                ms._get_json("https://x/api/v1/schedule", _open)
    # and with the REAL trusted clock (no patching at all)
    with ms.capture_mlb_source_bytes(tmp_path / "real", clock=lambda: y2k):
        with pytest.raises(ms.MLBSourceError, match="BEFORE_FETCH_START"):
            ms._get_json("https://x/api/v1/schedule", _open)


def test_adversarial_far_future_recorder_clock_rejected(tmp_path):
    far = datetime(2099, 1, 1, tzinfo=timezone.utc)
    with ms.capture_mlb_source_bytes(tmp_path, clock=lambda: far):
        with pytest.raises(ms.MLBSourceError, match="IN_FUTURE"):
            ms._get_json("https://x/api/v1/schedule", _open)


def test_adversarial_caller_now_year_2000_and_far_future_rejected():
    with pytest.raises(ms.MLBSourceError, match="BEFORE_FETCH_START"):
        ms.fetch_schedule("2026-10-13", opener=_open, now=datetime(2000, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(ms.MLBSourceError, match="IN_FUTURE"):
        ms.fetch_schedule("2026-10-13", opener=_open, now=datetime(2099, 1, 1, tzinfo=timezone.utc))


def test_recorder_requires_trusted_window_and_aware_clock(tmp_path):
    rec = ms.MLBSourceCapture(tmp_path, clock=lambda: T0)
    with pytest.raises(TypeError):
        rec.record(url="https://x/api/v1/schedule", raw=b"{}")
    with pytest.raises(ms.MLBSourceError, match="BACKWARDS"):
        rec.record(url="https://x/api/v1/schedule", raw=b"{}", fetch_started_at=T0,
                   received_at=T0 - timedelta(seconds=1))
    with pytest.raises(ms.MLBSourceError, match="timezone-aware"):
        ms.MLBSourceCapture(tmp_path, clock=lambda: datetime(2026, 10, 13)).record(
            url="https://x/api/v1/schedule", raw=b"{}", fetch_started_at=T0, received_at=T0)


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


def test_no_repo_caller_passes_pre_fetch_time_to_fetch_schedule():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    bad = []
    for p in list((root / "sportsedge").rglob("*.py")) + list((root / "scripts").rglob("*.py")):
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            code = line.split("#")[0]
            if "fetch_schedule(" in code and "def fetch_schedule" not in code and "now=" in code:
                bad.append(f"{p.relative_to(root)}:{i}")
    assert not bad, bad
