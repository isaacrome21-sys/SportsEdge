"""t248: public period output for NAIVE_FAIL quarters must not carry any field that can
rebuild a refused market; spreads only via the checked spread_probs; period required."""
import itertools
import math

import pytest

from sportsedge import nfl_period_lines_empirical as E
from sportsedge.screen_only_guard import screen_only
from tests.test_nfl_period_lines_empirical_20261023 import _g, _hist


def _mixed():
    """Quarter margins straddle zero, so the moneyline is not trivially 0/1."""
    pts = [(3, 0), (0, 3), (7, 7), (0, 0), (7, 3), (3, 7), (10, 7), (7, 10), (6, 7), (1, 0)]
    rows = []
    for i, (h, a) in enumerate(pts * 2):
        rows.append(_g(f"2023-{9 + i // 25:02d}-{1 + i % 25:02d}", 2023, "AAA", "BBB", h, a))
        rows.append(_g(f"2023-{9 + i // 25:02d}-{1 + i % 25:02d}", 2023, "BBB", "AAA", a, h))
    for i, (h, a) in enumerate(pts[:6]):
        rows.append(_g(f"2024-09-{10 + i:02d}", 2024, "AAA", "BBB", h, a))
    return rows

KW = dict(date="2024-10-01", season=2024, home="AAA", away="BBB")
QUARTERS = ["q1", "q2", "q3", "q4"]
SAFE_KEYS = {"engine_id", "engine_version", "period", "governance", "refused", "spread_quote"}


def _numbers(obj):
    """Every number reachable from obj (dict keys/values, lists, object attributes)."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield float(obj); return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _numbers(k); yield from _numbers(v)
        return
    if isinstance(obj, (list, tuple, set, frozenset)):
        for v in obj:
            yield from _numbers(v)
        return
    for name in getattr(obj, "__slots__", ()) or ():
        yield from _numbers(getattr(obj, name, None))
    if hasattr(obj, "__dict__") and not isinstance(obj, type):
        yield from _numbers(vars(obj))


def _pmfs(obj):
    if isinstance(obj, dict):
        if obj and all(isinstance(k, (int, float)) and not isinstance(k, bool) for k in obj):
            yield obj
        for v in obj.values():
            yield from _pmfs(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _pmfs(v)
    elif hasattr(obj, "__slots__") or hasattr(obj, "__dict__"):
        for name in (getattr(obj, "__slots__", ()) or ()):
            yield from _pmfs(getattr(obj, name, None))
        if hasattr(obj, "__dict__"):
            yield from _pmfs(vars(obj))


@pytest.mark.parametrize("period", QUARTERS)
def test_refused_quarter_exposes_only_safe_fields(period):
    out = E.price_period(_hist(), period=period, **KW)
    allowed = set(SAFE_KEYS)
    if f"{period.upper()}_TOTAL" not in E.NAIVE_FAIL_FAMILIES:
        allowed.add("total_pmf")
    assert set(out) <= allowed, set(out) - allowed
    for k in ("margin_pmf", "moneyline_3way", "mu_home", "mu_away"):
        assert k not in out


@pytest.mark.parametrize("period", QUARTERS)
def test_no_field_rebuilds_refused_moneyline(period):
    out = E.price_period(_mixed(), period=period, **KW)
    with screen_only():
        full = E.price_period_unrestricted(_mixed(), period=period, **KW)
    ml = full["moneyline_3way"]
    assert all(0.01 < ml[s] < 0.99 for s in ("home", "away")), ml  # non-degenerate fixture
    # The full margin pmf (whose signed sums are the moneyline) must not be reachable.
    assert not any(pmf == full["margin_pmf"] for pmf in _pmfs(out))
    for pmf in _pmfs(out):
        home = sum(p for k, p in pmf.items() if k > 0)
        tie = pmf.get(0, 0.0)
        assert not (math.isclose(home, ml["home"], abs_tol=1e-12)
                    and math.isclose(tie, ml["tie"], abs_tol=1e-12))


@pytest.mark.parametrize("period", ["q1", "q3", "q4"])
def test_no_field_rebuilds_refused_total(period):
    out = E.price_period(_hist(), period=period, **KW)
    with screen_only():
        full = E.price_period_unrestricted(_hist(), period=period, **KW)
    for pmf in _pmfs(out):
        assert pmf != full["total_pmf"]
    with pytest.raises(E.NflPeriodLinesError, match=f"NAIVE_FAIL:{period.upper()}_TOTAL"):
        E.total_probs(out, 3.5)


@pytest.mark.parametrize("period", QUARTERS)
@pytest.mark.parametrize("line", [1.5, -1.5, 2, -2, 3.5, -7, 10.5])
def test_checked_spreads_match_unrestricted_beyond_one(period, line):
    out = E.price_period(_hist(), period=period, **KW)
    with screen_only():
        full = E.price_period_unrestricted(_hist(), period=period, **KW)
    got = E.spread_probs(out, line)
    pmf = full["margin_pmf"]
    want = {"home": sum(p for k, p in pmf.items() if k + line > 0),
            "push": sum(p for k, p in pmf.items() if k + line == 0),
            "away": sum(p for k, p in pmf.items() if k + line < 0)}
    for side in want:
        assert got[side] == pytest.approx(want[side], abs=1e-12)


def test_halves_unchanged_full_output():
    for period in ("h1", "h2"):
        out = E.price_period(_hist(), period=period, **KW)
        assert {"margin_pmf", "total_pmf", "moneyline_3way"} <= set(out)


@pytest.mark.parametrize("bad", [None, "", "Q1", "q5", "game", 1])
@pytest.mark.parametrize("fn,line", [(E.spread_probs, 3.5), (E.total_probs, 3.5)])
def test_missing_or_unknown_period_refused(fn, line, bad):
    out = E.price_period(_hist(), period="h1", **KW)
    if bad is None:
        out.pop("period")
    else:
        out["period"] = bad
    with pytest.raises(E.NflPeriodLinesError, match="PERIOD_MISSING|UNKNOWN_PERIOD"):
        fn(out, line)


def test_handbuilt_margin_pmf_without_period_refused():
    with pytest.raises(E.NflPeriodLinesError, match="PERIOD_MISSING"):
        E.spread_probs({"margin_pmf": {3: 1.0}}, 3.5)


def test_spread_state_identical_when_only_moneyline_differs():
    """Two margin pmfs that agree beyond +/-1 but have different moneylines must yield
    indistinguishable public spread state: nothing in it identifies the moneyline."""
    a = {-3: 0.2, -1: 0.1, 0: 0.2, 1: 0.1, 3: 0.4}
    b = {-3: 0.2, -1: 0.25, 0: 0.0, 1: 0.15, 3: 0.4}
    qa, qb = E._SpreadQuote("q1", a), E._SpreadQuote("q1", b)
    assert sorted(_numbers(qa)) == pytest.approx(sorted(_numbers(qb)))
    for line in (1.5, -1.5, 2.5, -3, 3, 7):
        pa = E.spread_probs({"period": "q1", "spread_quote": qa}, line)
        pb = E.spread_probs({"period": "q1", "spread_quote": qb}, line)
        assert pa == pytest.approx(pb)
