import pytest

from sportsedge.core.simulate.football import KeyNumberMarginModel
from sportsedge.core.simulate.key_number_fit import fit_signed_key_mass_from_audit
from sportsedge.sports.nfl.real_history_audit import audit_nfl_history_rows


def _rows():
    rows = []
    # Deliberately asymmetric signed margins so absolute PMF cannot pass as signed PMF.
    margins = [3, 3, 3, -3, 7, 7, -7, -7, -7, 1, -1, 10]
    for season in (2023, 2024):
        for i, margin in enumerate(margins):
            away = 20
            home = away + margin
            rows.append({
                "season": season,
                "game_type": "REG",
                "home_score": home,
                "away_score": away,
                "spread_line": -2.5,
                "total_line": 44.5,
                "game_id": f"{season}-{i}",
            })
    return rows


def test_audit_reports_signed_and_absolute_key_number_pmf_separately():
    audit = audit_nfl_history_rows(
        _rows(),
        source_url="https://example.com/games.csv",
        source_sha256="a" * 64,
    )
    assert audit["absolute_margin_pmf"]["3"] == pytest.approx(4 / 12)
    assert audit["signed_margin_pmf"]["3"] == pytest.approx(3 / 12)
    assert audit["signed_margin_pmf"]["-3"] == pytest.approx(1 / 12)
    assert audit["signed_margin_pmf"]["7"] == pytest.approx(2 / 12)
    assert audit["signed_margin_pmf"]["-7"] == pytest.approx(3 / 12)


def test_fit_uses_signed_pmf_and_never_maps_absolute_mass_to_both_sides():
    audit = audit_nfl_history_rows(
        _rows(),
        source_url="https://example.com/games.csv",
        source_sha256="b" * 64,
    )
    fit = fit_signed_key_mass_from_audit(audit, keys=(3, 7))
    assert fit[3] == pytest.approx(3 / 12)
    assert fit[-3] == pytest.approx(1 / 12)
    assert fit[7] == pytest.approx(2 / 12)
    assert fit[-7] == pytest.approx(3 / 12)
    assert sum(fit.values()) < 1.0


def test_fit_fails_closed_without_real_hash_bound_signed_history():
    with pytest.raises(ValueError, match="SIGNED_MARGIN_PMF_REQUIRED"):
        fit_signed_key_mass_from_audit({
            "provenance": "REAL_PUBLIC_HISTORY",
            "source_url": "https://example.com/games.csv",
            "source_sha256": "c" * 64,
            "absolute_margin_pmf": {"3": 0.15, "7": 0.08},
            "seasons": [2023, 2024],
        })


def test_fitted_mass_round_trips_through_margin_model_exactly_at_keys():
    audit = audit_nfl_history_rows(
        _rows(),
        source_url="https://example.com/games.csv",
        source_sha256="d" * 64,
    )
    fit = fit_signed_key_mass_from_audit(audit, keys=(3, 7))
    model = KeyNumberMarginModel(mean=0.0, sigma=13.5, empirical_key_mass=fit)
    pmf = model.margin_pmf(range(-40, 41))
    for margin, expected in fit.items():
        assert pmf[margin] == pytest.approx(expected)
