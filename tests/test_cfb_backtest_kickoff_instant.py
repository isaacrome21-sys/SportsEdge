"""Regression: kickoff grouping/order must use the UTC instant, not the raw string."""
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "backtest_cfb_matchup_blend.py"
spec = importlib.util.spec_from_file_location("cfb_matchup_backtest_instant", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _prior():
    return [dict(season=2026, start=f"2026-09-0{i+1}T12:00:00Z", id=f"{t}{i}", home=t,
                 away=f"{t}o{i}", hs=28, **{"as": 21}, spread=0.0, total=49.0)
            for i in range(3) for t in ("A", "B")]


def _g(gid, start, hs, as_):
    return dict(season=2026, start=start, id=gid, home="A", away="B", hs=hs,
                **{"as": as_}, spread=0.0, total=49.0)


def _margin(rows, gid):
    return [r for r in rows if r["id"] == gid][0]["model_margin"]


def test_same_instant_different_encoding_is_one_kickoff():
    rows = module.project(_prior() + [_g("1", "2026-09-10T12:00:00Z", 10, 10),
                                      _g("2", "2026-09-10T12:00:00.000Z", 60, 0)])
    assert _margin(rows, "1") == _margin(rows, "2")


def test_later_instant_with_offset_cannot_leak_into_earlier_game():
    base = _margin(module.project(_prior() + [_g("E", "2026-09-10T16:00:00Z", 10, 10)]), "E")
    rows = module.project(_prior() + [_g("E", "2026-09-10T16:00:00Z", 10, 10),
                                      _g("L", "2026-09-10T12:00:00-05:00", 70, 0)])
    assert _margin(rows, "E") == base


@pytest.mark.parametrize("bad", ["", None, "not-a-date", "2026-09-10T12:00:00"])
def test_project_rejects_invalid_clock(bad):
    with pytest.raises(ValueError):
        module.project(_prior() + [_g("X", bad, 1, 1)])
