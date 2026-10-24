"""t235 RED-first regression tests (Grok ruling under owner delegation).

Earlier fix 9ce9824d landed tests and fix in one commit; this file is
committed on its own BEFORE any fix. New gaps found adversarially:
  * p_over returned an exact 0.0 for lines beyond the pmf support
    (line >= MAX_TD + 0.5) -- a manufactured probability; must refuse.
  * p_over / margin_band_probs / race_probs crashed (TypeError/ValueError)
    or silently priced on non-numeric, bool, NaN inputs or a tiny/empty
    residual pool (empty pool gave a uniform 1/13 per band).
Research only; nothing here is validated.
"""
import math

import pytest

from sportsedge import nfl_game_scoring_empirical as E

PMF = E._poisson(5.0)
RES = [float((i % 21) - 10) for i in range(200)]


def test_p_over_in_support_unchanged():
    assert E.p_over(PMF, 4.5) == pytest.approx(math.fsum(PMF[5:]))
    assert E.p_over(PMF, E.MAX_TD - 0.5) == PMF[E.MAX_TD]


@pytest.mark.parametrize("line", [E.MAX_TD + 0.5, 20.5, 99.5])
def test_p_over_beyond_support_refused(line):
    with pytest.raises(E.NflGameScoringError):
        E.p_over(PMF, line)


def test_p_over_short_pmf_beyond_support_refused():
    with pytest.raises(E.NflGameScoringError):
        E.p_over([0.5, 0.5], 2.5)


@pytest.mark.parametrize("line", ["4.5", None, True, [4.5]])
def test_p_over_non_numeric_line_coded(line):
    with pytest.raises(E.NflGameScoringError):
        E.p_over(PMF, line)


@pytest.mark.parametrize("mu", [float("nan"), float("inf"), True, "1.0", None])
def test_margin_mu_invalid_coded(mu):
    with pytest.raises(E.NflGameScoringError):
        E.margin_band_probs(mu, RES)


@pytest.mark.parametrize("res", [[], [1.0] * 99, RES[:150] + [float("nan")], RES + [True]])
def test_margin_residual_pool_invalid_coded(res):
    with pytest.raises(E.NflGameScoringError):
        E.margin_band_probs(0.0, res)


def test_margin_valid_sums_to_one():
    out = E.margin_band_probs(2.5, RES)
    assert math.fsum(out.values()) == pytest.approx(1.0)


@pytest.mark.parametrize("fit", [(True, 0.0), (0.1, False), (0.1,), (0.1, 0.0, 0.0), "ab"])
def test_race_fit_invalid_coded(fit):
    with pytest.raises(E.NflGameScoringError):
        E.race_probs(1.0, fit, 0.1)


@pytest.mark.parametrize("pn", [True, False, float("nan"), "0.1", None])
def test_race_neither_invalid_coded(pn):
    with pytest.raises(E.NflGameScoringError):
        E.race_probs(1.0, (0.1, 0.0), pn)
