from sportsedge.sports.cfb.early_season_uncertainty import (
    CFBPersonnelUncertainty,
    assess_early_season_uncertainty,
    adjusted_decision_edge,
)


def test_week_three_no_adjustment():
    decision = assess_early_season_uncertainty(
        week=3,
        personnel=CFBPersonnelUncertainty(new_starting_qb=True, depth_chart_unsettled=True),
        is_favorite=True,
        spread_abs=21.0,
    )
    assert decision.risk_score == 0.0
    assert decision.uncertainty_multiplier == 1.0
    assert decision.hard_pass is False


def test_new_qb_low_ol_large_favorite_gets_material_haircut():
    decision = assess_early_season_uncertainty(
        week=1,
        personnel=CFBPersonnelUncertainty(
            new_starting_qb=True,
            qb_career_starts=1,
            transfer_qb=True,
            returning_ol_starters=2,
            portal_turnover_rate=0.42,
            depth_chart_unsettled=True,
        ),
        is_favorite=True,
        spread_abs=28.5,
    )
    assert decision.risk_score >= 0.72
    assert decision.uncertainty_multiplier > 1.25
    assert decision.hard_pass is True
    assert adjusted_decision_edge(0.08, decision) <= 0.0


def test_raw_model_probability_is_not_part_of_policy():
    decision = assess_early_season_uncertainty(
        week=1,
        personnel=CFBPersonnelUncertainty(new_starting_qb=True, qb_career_starts=8),
        is_favorite=False,
        spread_abs=0.0,
    )
    assert 0.0 < decision.edge_haircut < 0.03
    assert decision.favorite_extra_haircut == 0.0
    assert adjusted_decision_edge(0.05, decision) < 0.05
