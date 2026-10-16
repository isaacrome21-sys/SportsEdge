"""NFL totals LEVEL model — research candidate (NOT production).

Preregistration: research/nfl_totals_level_model_20261016/
PREREG_NFL_TOTALS_LEVEL_MODEL.md (hash-locked in SPEC_HASHES.txt).

The shipped NFL totals construction has no level model: its total
mean is a frozen 22-points-per-team prior adjusted only by a
margin-form rating split, and card rows land at
WATCH_NFL_TOTAL_PRIOR_ONLY (NFL_ABSOLUTE_SCORING_RATE_MODEL_MISSING).
Stage 2 item N3 measured the cost (DOES_NOT_BEAT_BASELINE vs league
climatology). This module is the preregistered candidate that tests
whether a point-in-time per-team scoring-rate level model closes
that gap. It is a research module: nothing in the production path
imports it, and no verdict here wires it anywhere.

Construction (prereg §3 — the constants below are the preregistered
ones; changing them forks the preregistration):

* Trailing samples: each team's ALL completed same-season games
  strictly before kickoff.
* League rate L: expanding points per team-game over all
  strictly-prior same-season games; 22.0 if the pool is empty.
* Shrunk rates with kappa = 4.0 games of prior weight:
  off_T = (PF_T + kappa*L) / (n_T + kappa);
  def_T = (PA_T + kappa*L) / (n_T + kappa).
* Expected scores (additive-average form):
  E_home = (off_home + def_away)/2 + 0.75;
  E_away = (off_away + def_home)/2 - 0.75.
* Predicted total distribution: Normal(E_home + E_away, 13.5) —
  the sd is FIXED at the production value so the evaluation
  isolates the level effect.

All functions are pure and deterministic. Callers own the PIT
discipline: pass only games strictly before the fixture's kickoff
(the evaluator enforces the identical-kickoff batch rule).
"""
from __future__ import annotations

KAPPA = 4.0            # shrinkage prior weight, in games (prereg §3)
LEAGUE_FALLBACK = 22.0  # points per team-game when the pool is empty
HFA_HALF = 0.75        # half the production HFA of 1.5 (prereg §3)
TOTAL_SD = 13.5        # production total sd, FIXED (prereg §3)


def league_rate(prior_games):
    """Points per team-game over strictly-prior same-season games.

    prior_games: iterable of (away_score, home_score) for completed
    games strictly before the fixture (batch rule applied by the
    caller). Returns LEAGUE_FALLBACK when the pool is empty.
    """
    games = list(prior_games)
    if not games:
        return LEAGUE_FALLBACK
    total_points = sum(a + h for a, h in games)
    return total_points / (2.0 * len(games))


def team_record(games_for_team):
    """(n, points_for, points_against) from a team's trailing games.

    games_for_team: iterable of (points_for, points_against) from
    that team's perspective, strictly prior games only.
    """
    games = list(games_for_team)
    return (len(games),
            sum(pf for pf, _ in games),
            sum(pa for _, pa in games))


def shrunk_rate(points, n, league, kappa=KAPPA):
    """(points + kappa*league) / (n + kappa); equals league at n=0."""
    return (points + kappa * league) / (n + kappa)


def expected_scores(home_record, away_record, league,
                    kappa=KAPPA, hfa_half=HFA_HALF):
    """(E_home, E_away) from trailing records and the league rate.

    home_record / away_record: (n, points_for, points_against) as
    returned by team_record(). Additive-average form (prereg §3):
    a team's expected score against an opponent is the average of
    its shrunk offensive rate and the opponent's shrunk defensive
    rate, split by home field.
    """
    hn, hpf, hpa = home_record
    an, apf, apa = away_record
    off_home = shrunk_rate(hpf, hn, league, kappa)
    def_home = shrunk_rate(hpa, hn, league, kappa)
    off_away = shrunk_rate(apf, an, league, kappa)
    def_away = shrunk_rate(apa, an, league, kappa)
    e_home = (off_home + def_away) / 2.0 + hfa_half
    e_away = (off_away + def_home) / 2.0 - hfa_half
    return e_home, e_away


def total_mean(e_home, e_away):
    return e_home + e_away
