import pytest

from sportsedge.core.simulate.football import KeyNumberMarginModel
from sportsedge.core.simulate.key_number_fit import (
    extract_signed_key_frequency_targets_from_audit,
    fit_signed_key_mass_from_audit,
)
from sportsedge.sports.nfl.real_history_audit import audit_nfl_history_rows


def _rows():
    rows = []
    margins = [3, 3, 3, -3, 7, 7, -7, -7, -7, 1, -1, 10]
    for season in (2023, 2024):
        for i, margin in enumerate(margins):
            away = 20
            home = away + margin
            rows.append({
                "season": season, "game_type": "REG",
                "home_score": home, "away_score": away,
                "spread_line": -2.5, "total_line": 44.5,
                "game_id": f"{season}-{i}",
            })
    return rows


def _audit(hash_char="a"):
    return audit_nfl_history_rows(
        _rows(), source_url="https://example.com/games.csv", source_sha256=hash_char * 64,
    )


def test_audit_reports_signed_and_absolute_key_number_pmf_separately():
    audit = _audit("a")
    assert audit["absolute_margin_pmf"]["3"] == pytest.approx(4 / 12)
    assert audit["signed_margin_pmf"]["3"] == pytest.approx(3 / 12)
    assert audit["signed_margin_pmf"]["-3"] == pytest.approx(1 / 12)
    assert audit["signed_margin_pmf"]["7"] == pytest.approx(2 / 12)
    assert audit["signed_margin_pmf"]["-7"] == pytest.approx(3 / 12)


def test_extractor_returns_signed_validation_targets_not_simulator_mass():
    targets = extract_signed_key_frequency_targets_from_audit(_audit("b"), keys=(3, 7))
    assert targets[3] == pytest.approx(3 / 12)
    assert targets[-3] == pytest.approx(1 / 12)
    assert targets[7] == pytest.approx(2 / 12)
    assert targets[-7] == pytest.approx(3 / 12)
    with pytest.raises(ValueError, match="IMPOSED_KEY_MASS_PROHIBITED"):
        KeyNumberMarginModel(mean=0.0, sigma=13.5, empirical_key_mass=targets)


def test_legacy_fit_name_is_compatibility_alias_only():
    audit = _audit("c")
    assert fit_signed_key_mass_from_audit(audit) == extract_signed_key_frequency_targets_from_audit(audit)


def test_target_extraction_fails_closed_without_real_hash_bound_signed_history():
    with pytest.raises(ValueError, match="SIGNED_MARGIN_PMF_REQUIRED"):
        extract_signed_key_frequency_targets_from_audit({
            "provenance": "REAL_PUBLIC_HISTORY",
            "source_url": "https://example.com/games.csv",
            "source_sha256": "d" * 64,
            "absolute_margin_pmf": {"3": 0.15, "7": 0.08},
            "seasons": [2023, 2024],
        })
