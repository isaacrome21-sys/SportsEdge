"""Regression cases for the October 7 MLB probability audit."""
from datetime import date
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from scripts import run_mlb_score_compatible_joint_research as runner
from sportsedge.mlb_context_adjusted_research import recent_starter_profile
from sportsedge.mlb_joint_features import _pitcher_pool, MLBJointFeatureError
from sportsedge.mlb_joint_card_coupled_research import simulate_score_compatible_joint_card


class TestMLBModelAudit(unittest.TestCase):
    def test_missing_or_invalid_pitcher_counts_are_not_zero(self):
        valid = dict(inningsPitched='5.2', strikeOuts=5, earnedRuns=0, hits=4, baseOnBalls=1)
        self.assertEqual(_pitcher_pool([{'stat': valid}])[0]['outs'], 17)
        for field in ('strikeOuts', 'earnedRuns', 'hits', 'baseOnBalls'):
            for bad in (None, -1, 1.5, True, float('nan')):
                with self.subTest(field=field, bad=bad):
                    with self.assertRaises(MLBJointFeatureError):
                        _pitcher_pool([{'stat': {**valid, field: bad}}])
            missing = dict(valid)
            del missing[field]
            with self.assertRaises(MLBJointFeatureError):
                _pitcher_pool([{'stat': missing}])

    def test_zero_out_start_contributes_runs_and_workload(self):
        rows = [{'stat': dict(gamesStarted=1, inningsPitched=ip, earnedRuns=er)}
                for ip, er in [('6.0', 1), ('6.0', 1), ('0.0', 4)]]
        history = SimpleNamespace(player_rows=lambda **kwargs: rows)
        result = recent_starter_profile(history=history, player_id=1, target_date=date(2026, 10, 7))
        self.assertEqual(result.starts, 3)
        self.assertEqual(result.er_per_9, 4.5)
        self.assertEqual(result.mean_outs, 12)
        del rows[-1]['stat']['earnedRuns']
        result = recent_starter_profile(history=history, player_id=1, target_date=date(2026, 10, 7))
        self.assertEqual(result.status, 'INVALID_PRIOR_START')
        self.assertIsNone(result.er_per_9)

    def _simulate(self, extra=False, **kwargs):
        pool = [dict(strikeouts=8, outs=18, earned_runs=0, hits_allowed=3, walks_allowed=1),
                dict(strikeouts=1, outs=3, earned_runs=8, hits_allowed=8, walks_allowed=3)] * 3
        pools = {'p': pool}
        sides = {'p': 'AWAY'}
        rows = [dict(selection_id='k', market='PITCHER_K', pitcher_id='p', side='OVER', line=2.5)]
        if extra:
            pools['q'] = pool
            sides['q'] = 'HOME'
            rows.append(dict(selection_id='q', market='PITCHER_ER', pitcher_id='q', side='UNDER', line=1.5))
        return simulate_score_compatible_joint_card(game_id='g', away_mean_runs=3, home_mean_runs=3,
            feature_source_hash='context', simulations=5000, pitcher_pools=pools,
            pitcher_team_sides=sides, selections=rows, **kwargs)

    def test_conditioning_distortion_and_sample_size_are_visible(self):
        row = self._simulate()['results'][0]
        audit = row['pitcher_conditioning_audit']
        self.assertEqual(audit['unconditioned_empirical_win_p'], .5)
        self.assertGreater(audit['conditioning_win_p_delta'], .3)
        self.assertEqual(audit['independent_observations'], 6)
        self.assertFalse(audit['postseason_workload_adjusted'])
        self.assertFalse(audit['fitted_pitcher_k_model_used'])

    def test_other_pitcher_does_not_change_existing_probabilities(self):
        a, b = self._simulate(), self._simulate(extra=True)
        self.assertEqual(a['score_distribution_sha256'], b['score_distribution_sha256'])
        self.assertEqual(a['results'][0]['research_p'], b['results'][0]['research_p'])

    def test_dispersion_changes_simulation_identity(self):
        a, b = self._simulate(), self._simulate(team_sigma=.5)
        self.assertNotEqual(a['simulation_id'], b['simulation_id'])

    def test_runner_binds_score_seed_to_game_context_only(self):
        snapshot = json.loads(Path('manual_inputs/mlb/2026-10-07_rays_yankees_supplied.json').read_text())
        snapshot['rows'] = snapshot['rows'][:1]
        key = snapshot['rows'][0]['game_id']
        game = SimpleNamespace(game_pk=1, official_date='2026-10-07', away_id=2, home_id=3,
                               away_name='Away', home_name='Home')
        context = {'games': [dict(game_id=key, adjusted_means=dict(away_mean_runs=3, home_mean_runs=4),
                    feature_source_hash='game-context-only', context_as_of_utc='2026-10-07T22:30:00+00:00')]}
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            path.write_text(json.dumps(snapshot))
            with patch.object(runner, 'run_context_adjusted', return_value=context), \
                 patch.object(runner, '_resolve_game', return_value=game), \
                 patch.object(runner, 'simulate_score_compatible_joint_card', wraps=simulate_score_compatible_joint_card) as sim:
                runner.run(path, simulations=1000)
                self.assertEqual(sim.call_args.kwargs['feature_source_hash'], 'game-context-only')


if __name__ == '__main__':
    unittest.main()
