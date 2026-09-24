import pytest
from sportsedge.nfl_td_role_model import NflTdRoleError, estimate_anytime_td

def _p(**kw):
    row={"player":"RB One","game_id":"g1","expected_team_tds":3.0,"rush_share":.55,"target_share":.12,"goal_line_carry_share":.75,"close_target_share":.10,"team_rush_td_mix":.55,"context":{"availability_multiplier":1.0,"matchup_multiplier":1.0,"scoring_environment_multiplier":1.0}}
    row.update(kw); return row

def test_deterministic_bounded_and_role_sensitive():
    a=estimate_anytime_td(_p(),n_sims=5000,seed=7); b=estimate_anytime_td(_p(),n_sims=5000,seed=7)
    assert a==b and 0<a.estimate_p<1 and a.rushing_td_share==pytest.approx(.65)
    low=estimate_anytime_td(_p(goal_line_carry_share=.20),n_sims=10000,seed=9); high=estimate_anytime_td(_p(goal_line_carry_share=.90),n_sims=10000,seed=9)
    assert high.estimate_p>low.estimate_p

def test_context_and_missing_inputs_fail_closed():
    out=estimate_anytime_td(_p(context={"availability_multiplier":0.0,"matchup_multiplier":1.0,"scoring_environment_multiplier":1.0}),n_sims=1000)
    assert out.estimate_p==0.0
    row=_p(); del row["goal_line_carry_share"]
    with pytest.raises(NflTdRoleError,match="REQUIRED"): estimate_anytime_td(row)
