from sportsedge.core.simulate.nfl_possession_challenger import PossessionChallengerBaseline

def test_baseline_alternates_and_flips_halftime():
 s=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=7)
 p=s.simulate_one(0)
 assert p.second_half_receiver != p.opening_receiver
 for half in (1,2):
  xs=[x for x in p.possessions if x.half==half]
  assert xs[0].offense == (p.opening_receiver if half==1 else p.second_half_receiver)
  assert all(a.offense!=b.offense for a,b in zip(xs,xs[1:]))
  assert xs[-1].end_seconds==0

def test_baseline_is_seed_reproducible_and_conserves_score():
 a=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=11).simulate(20)
 b=PossessionChallengerBaseline(game_id="g",home_team="H",away_team="A",seed=11).simulate(20)
 assert a==b
 for p in a:
  assert p.total==p.home_score+p.away_score
  assert p.margin==p.home_score-p.away_score
