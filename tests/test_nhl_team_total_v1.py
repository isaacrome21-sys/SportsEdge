"""Family tests for NHL_TEAM_TOTAL_DIST_V1 (PR #2839 TT design build).

Every refusal path in the design/admission rails is exercised, plus
the distribution law's known values and the OT layer's mass
conservation. Fixture rates are stand-ins (no parent rate artifact
exists on main); they test machinery, not hockey.
"""

import math

import pytest

from sportsedge.nhl_team_total_v1 import (
    CONSTRUCTION_ID,
    ParentGameRates,
    TeamTotalRefusal,
    nb_pmf_grid,
    price_team_total,
    prob_over,
    prob_push,
    prob_under,
    team_total_pmf,
    validate_rates,
)


def _rates(**overrides):
    base = dict(
        game_id="2026020001",
        game_date=20261205,
        away_team="ANA",
        home_team="EDM",
        away_reg_mean=2.9,
        home_reg_mean=3.4,
        dispersion_cv=0.55,
        ot_home_win_prob=0.54,
        xg_vintages=("rebuilt_2026_27",),
        max_input_gamedate=20261204,
        pull_manifest_sha256="a" * 64,
        cross_vintage_treatment=None,
    )
    base.update(overrides)
    return ParentGameRates(**base)


# --- distribution law -------------------------------------------------

def test_pmf_sums_to_one_nb_and_poisson_paths():
    nb = nb_pmf_grid(3.1, 0.7)          # var = (0.7*3.1)^2 = 4.71 > mu
    pois = nb_pmf_grid(3.0, 0.1)        # var = 0.09 <= mu -> Poisson
    assert abs(sum(nb) - 1.0) < 1e-9
    assert abs(sum(pois) - 1.0) < 1e-9


def test_poisson_known_value():
    pmf = nb_pmf_grid(3.0, 0.1)         # Poisson path
    assert pmf[0] == pytest.approx(math.exp(-3.0), abs=1e-12)
    assert pmf[3] == pytest.approx(math.exp(-3.0) * 27.0 / 6.0, abs=1e-12)


def test_nb_known_value():
    # mu=3, c=1 -> var=9, r = 9/(9-3) = 1.5, p = 1.5/4.5 = 1/3
    # P(0) = p**r = (1/3)**1.5
    pmf = nb_pmf_grid(3.0, 1.0)
    assert pmf[0] == pytest.approx((1.0 / 3.0) ** 1.5, abs=1e-12)


def test_nb_mean_matches_mu():
    pmf = nb_pmf_grid(3.4, 0.55)
    mean = sum(k * v for k, v in enumerate(pmf))
    assert mean == pytest.approx(3.4, abs=1e-6)


# --- OT layer -----------------------------------------------------------

def test_incl_ot_mass_conserved_both_teams():
    rates = _rates()
    for side in ("away", "home"):
        pmf = team_total_pmf(rates, side, "incl_ot")
        assert abs(sum(pmf) - 1.0) < 1e-9


def test_incl_ot_mean_shift_equals_tie_mass_times_win_prob():
    rates = _rates()
    reg_h = team_total_pmf(rates, "home", "regulation")
    reg_a = team_total_pmf(rates, "away", "regulation")
    p_tie = sum(a * b for a, b in zip(reg_a, reg_h))
    incl_h = team_total_pmf(rates, "home", "incl_ot")
    mean_reg = sum(k * v for k, v in enumerate(reg_h))
    mean_incl = sum(k * v for k, v in enumerate(incl_h))
    assert mean_incl - mean_reg == pytest.approx(
        p_tie * rates.ot_home_win_prob, abs=1e-9)


def test_regulation_basis_is_the_raw_grid():
    rates = _rates()
    assert team_total_pmf(rates, "home", "regulation") == \
        nb_pmf_grid(rates.home_reg_mean, rates.dispersion_cv)


# --- settlement basis: recorded, never assumed --------------------------

def test_missing_basis_refuses():
    with pytest.raises(TeamTotalRefusal) as exc:
        price_team_total(_rates(), "home", 3.5, None)
    assert exc.value.code == "SETTLEMENT_BASIS_UNRECORDED"


def test_unrecorded_basis_string_refuses():
    with pytest.raises(TeamTotalRefusal) as exc:
        price_team_total(_rates(), "home", 3.5, "whatever_dk_usually_does")
    assert exc.value.code == "SETTLEMENT_BASIS_UNRECORDED"


# --- strictly-prior rail (admission section 2.2) -------------------------

def test_same_day_input_refuses_lookahead():
    rates = _rates(max_input_gamedate=20261205)   # == game date
    with pytest.raises(TeamTotalRefusal) as exc:
        validate_rates(rates)
    assert exc.value.code == "LOOKAHEAD_RISK"


def test_future_input_refuses_lookahead():
    rates = _rates(max_input_gamedate=20261206)   # > game date
    with pytest.raises(TeamTotalRefusal) as exc:
        price_team_total(rates, "away", 2.5, "regulation")
    assert exc.value.code == "LOOKAHEAD_RISK"


def test_strictly_prior_input_accepted():
    validate_rates(_rates(max_input_gamedate=20261204))  # day before: fine


# --- vintage rail (admission section 4.1) --------------------------------

def test_cross_vintage_without_treatment_refuses():
    rates = _rates(xg_vintages=("undisclosed_legacy", "rebuilt_2026_27"))
    with pytest.raises(TeamTotalRefusal) as exc:
        validate_rates(rates)
    assert exc.value.code == "CROSS_VINTAGE_UNTREATED"


def test_cross_vintage_with_declared_treatment_accepted():
    rates = _rates(
        xg_vintages=("undisclosed_legacy", "rebuilt_2026_27"),
        cross_vintage_treatment="declared-in-prereg-token")
    validate_rates(rates)
    row = price_team_total(rates, "home", 3.5, "regulation")
    assert row.xg_vintages == ("undisclosed_legacy", "rebuilt_2026_27")


def test_single_vintage_accepted_without_treatment():
    validate_rates(_rates(xg_vintages=("undisclosed_legacy",)))


# --- rates validity -------------------------------------------------------

@pytest.mark.parametrize("overrides", [
    {"away_reg_mean": 0.0},
    {"home_reg_mean": -1.0},
    {"dispersion_cv": 0.0},
    {"ot_home_win_prob": 1.5},
    {"ot_home_win_prob": -0.1},
    {"pull_manifest_sha256": ""},
    {"xg_vintages": ()},
])
def test_invalid_rates_refuse(overrides):
    with pytest.raises(TeamTotalRefusal) as exc:
        validate_rates(_rates(**overrides))
    assert exc.value.code == "RATES_INVALID"


# --- pricing --------------------------------------------------------------

def test_half_line_probabilities_partition():
    row = price_team_total(_rates(), "home", 3.5, "regulation")
    assert row.prob_push == 0.0
    assert row.prob_over + row.prob_under == pytest.approx(1.0, abs=1e-9)


def test_integer_line_push_is_the_pmf_mass():
    rates = _rates()
    pmf = team_total_pmf(rates, "home", "regulation")
    row = price_team_total(rates, "home", 3.0, "regulation")
    assert row.prob_push == pytest.approx(pmf[3], abs=1e-12)
    total = row.prob_over + row.prob_under + row.prob_push
    assert total == pytest.approx(1.0, abs=1e-9)


def test_higher_mean_prices_over_higher():
    lo = price_team_total(_rates(home_reg_mean=2.2), "home", 3.5,
                          "regulation")
    hi = price_team_total(_rates(home_reg_mean=3.8), "home", 3.5,
                          "regulation")
    assert hi.prob_over > lo.prob_over


def test_incl_ot_prices_over_at_least_regulation_for_favorite():
    rates = _rates()
    reg = price_team_total(rates, "home", 3.5, "regulation")
    incl = price_team_total(rates, "home", 3.5, "incl_ot")
    # the OT layer can only add goals, never remove them
    assert incl.prob_over >= reg.prob_over - 1e-12


def test_row_echoes_basis_and_provenance():
    rates = _rates()
    row = price_team_total(rates, "away", 2.5, "incl_ot")
    assert row.construction_id == CONSTRUCTION_ID
    assert row.settlement_basis == "incl_ot"
    assert row.team == "ANA"
    assert row.pull_manifest_sha256 == rates.pull_manifest_sha256
    assert row.xg_vintages == rates.xg_vintages


def test_invalid_line_refuses():
    with pytest.raises(TeamTotalRefusal) as exc:
        price_team_total(_rates(), "home", -0.5, "regulation")
    assert exc.value.code == "LINE_INVALID"


def test_prob_helpers_on_known_grid():
    pmf = [0.1, 0.2, 0.4, 0.3]
    assert prob_over(pmf, 1.5) == pytest.approx(0.7)
    assert prob_under(pmf, 1.5) == pytest.approx(0.3)
    assert prob_push(pmf, 2.0) == pytest.approx(0.4)
    assert prob_push(pmf, 2.5) == 0.0
