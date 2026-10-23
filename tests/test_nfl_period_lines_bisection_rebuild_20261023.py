"""t249: run the verifier's bisection rebuild against every public period output.

Attack (from the t248 NOT CLEARED note): the engine's margin pmf is the public history's
pooled margin pmf moved by one shift d. Any public number that depends on d monotonically
(a spread price, a pmf mean, ...) can be bisected to recover d, and d gives the refused
moneyline exactly. Grok ruling 2026-10-23 Option 1: refuse every Q1-Q4 spread."""
import math

import pytest

from sportsedge import nfl_period_lines_empirical as E
from sportsedge.screen_only_guard import screen_only
from tests.test_nfl_period_lines_empirical_20261023 import _g
from tests.test_nfl_period_lines_no_rebuild_20261023 import KW, _mixed as _sym, _numbers, _pmfs


def _mixed():
    """Margins straddle zero and the teams are unequal, so the margin shift is a
    non-integer that no incidental public number (0, 1, a pmf key) equals."""
    rows = _sym()
    for i, (h, a) in enumerate([(7, 3), (3, 0), (10, 7), (6, 3), (7, 0), (3, 3)]):
        rows.append(_g(f"2024-09-{20 + i:02d}", 2024, "AAA", "CCC", h, a))
        rows.append(_g(f"2024-09-{20 + i:02d}", 2024, "DDD", "BBB", h - 2, a + 1))
    return rows

QUARTERS = ["q1", "q2", "q3", "q4"]
LINES = [x / 2 for x in range(-40, 41)]


def _pool_margin_pmf(history, period):
    rows = E._rows(history, period)
    pool = [r for r in rows if r[1] < KW["season"]]
    return E._pmf([r[4] - r[5] for r in pool]), E._pmf([r[4] + r[5] for r in pool])


def _ml(pmf):
    return (sum(p for k, p in pmf.items() if k > 0), pmf.get(0, 0.0),
            sum(p for k, p in pmf.items() if k < 0))


def _bisect(f, target, lo=-40.0, hi=40.0):
    """f is non-decreasing in d; return d with f(d) ~= target."""
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _mean(pmf):
    return sum(k * p for k, p in pmf.items()) / sum(pmf.values())


def _attack(out, history, period):
    """Every rebuild the attacker can try; yields candidate (home, tie, away)."""
    base, tbase = _pool_margin_pmf(history, period)
    mbar = _mean(base)
    shifted = lambda d: E._shift(base, d)  # noqa: E731
    # 1) bisect a shift against every public spread price
    for L in LINES:
        try:
            sp = E.spread_probs(out, L)
        except E.NflPeriodLinesError:
            continue
        d = _bisect(lambda d: sum(p for k, p in shifted(d).items() if k + L > 0), sp["home"])
        yield _ml(shifted(d))
    # 2) shifts read off any public pmf (its mean vs the pooled margin / total mean)
    for pmf in _pmfs(out):
        m = _mean(pmf)
        for d in (m - mbar, m - _mean(tbase)):
            yield _ml(shifted(d))
        yield _ml(shifted(_bisect(lambda d: _mean(shifted(d)), m)))
    # 3) every bare public number used directly as the shift
    for x in _numbers(out):
        if math.isfinite(x) and abs(x) < 40:
            yield _ml(shifted(x))


def _true_ml(history, period):
    with screen_only():
        full = E.price_period_unrestricted(history, period=period, **KW)
    ml = full["moneyline_3way"]
    return ml["home"], ml["tie"], ml["away"], full


@pytest.mark.parametrize("period", QUARTERS)
def test_attack_is_real_against_unrestricted_spreads(period):
    """Control: with a spread price available the bisection does rebuild the moneyline."""
    h = _mixed()
    home, tie, away, full = _true_ml(h, period)
    hits = [c for c in _attack(full, h, period)
            if all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(c, (home, tie, away)))]
    assert hits


@pytest.mark.parametrize("period", QUARTERS)
def test_bisection_cannot_rebuild_refused_moneyline_from_public_output(period):
    h = _mixed()
    home, tie, away, _ = _true_ml(h, period)
    assert 0.01 < home < 0.99 and 0.01 < away < 0.99
    out = E.price_period(h, period=period, **KW)
    for c in _attack(out, h, period):
        assert not all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(c, (home, tie, away))), c


@pytest.mark.parametrize("period", QUARTERS)
def test_public_quarter_output_exposes_only_q2_total(period):
    out = E.price_period(_mixed(), period=period, **KW)
    data = set(out) - {"engine_id", "engine_version", "period", "governance", "refused"}
    assert data == ({"total_pmf"} if period == "q2" else set())
    for L in LINES:
        with pytest.raises(E.NflPeriodLinesError, match=f"NAIVE_FAIL:{period.upper()}_MONEYLINE_DERIVABLE"):
            E.spread_probs(out, L)
    assert out["refused"]["spread"] == f"NAIVE_FAIL:{period.upper()}_MONEYLINE_DERIVABLE"


def test_q2_public_output_carries_no_margin_shift():
    """Two histories that differ only in the home/away split of one neutral game (same
    totals, league mean of margins moves) give the same public Q2 output (to float rounding) but
    different Q2 moneylines: nothing public pins the Q2 margin shift."""
    a = _mixed() + [_g("2023-11-20", 2023, "XXX", "YYY", 10, 0)]
    b = _mixed() + [_g("2023-11-20", 2023, "XXX", "YYY", 0, 10)]
    oa = E.price_period(a, period="q2", **KW)
    ob = E.price_period(b, period="q2", **KW)
    ta, tb = oa.pop("total_pmf"), ob.pop("total_pmf")
    assert oa == ob and set(ta) == set(tb)
    assert all(math.isclose(ta[k], tb[k], abs_tol=1e-12) for k in ta)  # float-sum order only
    assert _true_ml(a, "q2")[:3] != pytest.approx(_true_ml(b, "q2")[:3], abs=1e-6)


@pytest.mark.parametrize("period", ["h1", "h2"])
def test_halves_unchanged(period):
    out = E.price_period(_mixed(), period=period, **KW)
    assert {"margin_pmf", "total_pmf", "moneyline_3way"} <= set(out)
    assert sum(E.spread_probs(out, 0.5).values()) == pytest.approx(1.0)
