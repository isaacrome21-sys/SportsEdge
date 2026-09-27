import unittest
import json
from dataclasses import asdict, is_dataclass, replace
from datetime import datetime, timedelta, timezone

from sportsedge.research.first_inning_matchup import (
    BatterOBP, FirstInningParameters, PitcherFirstInning, predict_first_inning, shrink_rate,
)
from sportsedge.research.market_value import compare_price
from sportsedge.research.preplay_td_roles import (
    PreplayRoleAllocator, ZoneRole, stabilized_role_shares,
    summarize_offensive_touchdowns,
)
from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
from sportsedge.core.simulate.usage import PlayerUsageProfile, TeamUsageProfile
from sportsedge.core.simulate.player_markets import derive_player_stat_market


NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


class FirstInningTests(unittest.TestCase):
    def inputs(self):
        # Artificial coefficients exercise mechanics only, never a fitted artifact.
        return dict(away_pitcher=PitcherFirstInning('AP', 27, 81, 0, 0),
                    home_pitcher=PitcherFirstInning('HP', 27, 81, 0, 0),
                    away_top3=[BatterOBP('A'+str(i), 33, 100) for i in range(3)],
                    home_top3=[BatterOBP('H'+str(i), 33, 100) for i in range(3)],
                    parameters=FirstInningParameters('SYNTHETIC_TEST_ONLY', NOW-timedelta(days=1),
                        0, .1, -3, -1, 20, 100, .33, .5),
                    environment_scenarios=[(1., 1.)], features_as_of=NOW,
                    prediction_at=NOW, first_pitch=NOW+timedelta(hours=1),
                    starters_confirmed=True, lineups_confirmed=True,
                    source_sha256='a'*64, game_id='synthetic')

    def test_small_sample_shrinkage(self):
        self.assertEqual(shrink_rate(0, 0, .33, 100), .33)
        self.assertAlmostEqual(shrink_rate(1, 1, .33, 100), 34/101)

    def test_counts_do_not_accept_fractional_or_boolean(self):
        for args in ((1.5, 2), (True, 2), (3, 2), (-1, 2)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                shrink_rate(*args, .33, 100)

    def test_complements_and_reproducibility(self):
        result = predict_first_inning(**self.inputs())
        self.assertEqual(result, predict_first_inning(**self.inputs()))
        self.assertEqual(sum(result['research_probability'].values()), 1)
        self.assertFalse(result['official_eligible'])
        self.assertEqual(result['stake'], 0)

    def test_opposing_lineup_is_bound_to_correct_pitcher(self):
        args = self.inputs()
        args['away_top3'] = [BatterOBP('A'+str(i), 80, 100) for i in range(3)]
        halves = predict_first_inning(**args)['half_innings'][0]
        self.assertGreater(halves['top']['stabilized_top3_obp'], halves['bottom']['stabilized_top3_obp'])
        self.assertLess(halves['top']['hold_probability'], halves['bottom']['hold_probability'])

    def test_shared_environment_mixture_is_not_product_of_marginals(self):
        args = self.inputs()
        args['environment_scenarios'] = [(.5, .5), (.5, 2)]
        result = predict_first_inning(**args)
        rows = result['half_innings']
        product_of_marginals = (sum(r['weight']*r['top']['hold_probability'] for r in rows)
                               * sum(r['weight']*r['bottom']['hold_probability'] for r in rows))
        self.assertGreater(result['research_probability']['NRFI'], product_of_marginals)

    def test_history_never_overwhelms_baseline(self):
        args = self.inputs()
        args['home_pitcher'] = PitcherFirstInning('HP', 27, 81, 1000, 1000)
        result = predict_first_inning(**args)
        self.assertEqual(result['half_innings'][0]['top']['history_weight'], .5)

    def test_unconfirmed_future_or_started_input_rejected(self):
        for key, value in [('starters_confirmed', False), ('lineups_confirmed', False),
                           ('features_as_of', NOW+timedelta(seconds=1)),
                           ('first_pitch', NOW), ('prediction_at', NOW.replace(tzinfo=None))]:
            args = self.inputs(); args[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                predict_first_inning(**args)

    def test_training_cutoff_and_scenario_mass(self):
        args = self.inputs()
        args['parameters'] = replace(args['parameters'], training_end=NOW)
        with self.assertRaises(ValueError):
            predict_first_inning(**args)
        args = self.inputs(); args['environment_scenarios'] = [(.5, 1)]
        with self.assertRaises(ValueError):
            predict_first_inning(**args)

    def test_source_hash_and_lineup_identity_bind_result(self):
        args = self.inputs(); old = predict_first_inning(**args)
        args['source_sha256'] = 'b'*64
        self.assertNotEqual(old['input_sha256'], predict_first_inning(**args)['input_sha256'])
        args['away_top3'] = args['home_top3']
        with self.assertRaises(ValueError):
            predict_first_inning(**args)


class RoleTests(unittest.TestCase):
    def usage(self, team):
        return TeamUsageProfile(team, (
            PlayerUsageProfile(team+'Q', team, 'QB', True, 1, 0, 0, 0, 0),
            PlayerUsageProfile(team+'A', team, 'RB', True, 1, 1, .99, .99, .5),
            PlayerUsageProfile(team+'B', team, 'RB', True, 1, 1, .01, .01, .5),
        ), team+'Q')

    def allocator(self, seed=1):
        # Rusher B owns goal line; receiver A owns inside-10 targets.
        roles = {team+p: role for team in ('H','A') for p,role in (
            ('Q', ZoneRole(0,0,0,0)), ('A', ZoneRole(0,.3,1,.6)),
            ('B', ZoneRole(1,.7,0,.4)))}
        return PreplayRoleAllocator(self.usage('H'), self.usage('A'), roles=roles, seed=seed)

    def path(self, yardline, td=True, pass_play=False, sim=1):
        points = 6 if td else 0
        event = PlayEvent(1,1,1,850,'H',0,0,points,0,1,10,yardline,
            'PASS' if pass_play else 'RUSH', yardline if td else 1, points,
            score_type='TOUCHDOWN_CANDIDATE' if td else None,
            pass_complete=True if pass_play else None)
        return FootballPlayPath('test',sim,'H','A',(event,))

    def test_goal_line_role_differs_for_rush_and_target(self):
        rush = self.allocator().attribute(self.path(5)).plays[0]
        target = self.allocator().attribute(self.path(5, pass_play=True)).plays[0]
        self.assertEqual(rush.touchdown_scorer_id, 'HB')
        self.assertEqual(target.touchdown_scorer_id, 'HA')
        self.assertNotEqual(target.touchdown_scorer_id, target.passer_id)

    def test_long_td_does_not_retroactively_change_usage_zone(self):
        for seed in range(30):
            for is_pass in (False, True):
                scored = self.allocator(seed).attribute(self.path(75, pass_play=is_pass)).plays[0]
                ordinary = self.allocator(seed).attribute(self.path(75, td=False, pass_play=is_pass)).plays[0]
                self.assertEqual(scored.target_id, ordinary.target_id)
                self.assertEqual(scored.rusher_id, ordinary.rusher_id)

    def test_existing_market_readouts_consume_same_paths(self):
        paths = [self.allocator().attribute(self.path(5, sim=1)),
                 self.allocator().attribute(self.path(5, td=False, sim=2))]
        td = derive_player_stat_market(paths, player_id='HB', stat='touchdowns', line=.5)
        rushing = derive_player_stat_market(paths, player_id='HB', stat='rushing_yards', line=3)
        self.assertEqual(td, {'over': .5, 'under': .5, 'push': 0.})
        self.assertEqual(td, rushing)
        for path in paths:
            path.assert_reconciliation()

    def test_sparse_role_shares_conserve_team_opportunities(self):
        prior = {'a': .7, 'b': .3}
        self.assertEqual(stabilized_role_shares({'a':0,'b':0}, prior, prior_strength=10), prior)
        shares = stabilized_role_shares({'a':0,'b':1}, prior, prior_strength=10)
        self.assertAlmostEqual(sum(shares.values()), 1)
        self.assertAlmostEqual(shares['b'], 4/11)

    def test_td_joint_uses_paths_not_product_of_marginals(self):
        paths = [self.allocator().attribute(self.path(5, sim=1)),
                 self.allocator().attribute(self.path(5, pass_play=True, sim=2))]
        result = summarize_offensive_touchdowns(paths, player_ids=['HA','HB'])
        self.assertEqual(result['probabilities']['HA']['1+'], .5)
        self.assertEqual(result['probabilities']['HB']['1+'], .5)
        self.assertEqual(result['probabilities']['HB']['2+'], 0)
        self.assertEqual(result['all_selected_score_probability'], 0)
        self.assertNotEqual(result['all_selected_score_probability'], .5*.5)
        self.assertFalse(result['official_eligible'])
        self.assertEqual(result['scope'], 'OFFENSIVE_REGULATION_ONLY')

    def test_td_joint_rejects_duplicate_samples_and_inactive_players(self):
        path = self.allocator().attribute(self.path(5))
        with self.assertRaises(ValueError):
            summarize_offensive_touchdowns([path,path], player_ids=['HA'])
        with self.assertRaises(ValueError):
            summarize_offensive_touchdowns([path], player_ids=['UNKNOWN'])

    def test_missing_or_invalid_roles_fail(self):
        with self.assertRaises(ValueError):
            self.allocator().roles['HA'] = ZoneRole(float('nan'),0,0,0)
        with self.assertRaises(ValueError):
            PreplayRoleAllocator(self.usage('H'), self.usage('A'), roles={}, seed=1)
        with self.assertRaises(ValueError):
            stabilized_role_shares({'a':1}, {'b':1.}, prior_strength=10)


class PriceTests(unittest.TestCase):
    def price(self, **changes):
        args = dict(win=.7, push=0., american_odds=-400, quote_at=NOW, now=NOW,
                    start=NOW+timedelta(hours=1), ttl_seconds=180)
        args.update(changes)
        return compare_price(**args)

    def test_likely_outcome_can_be_bad_value(self):
        result = self.price()
        self.assertEqual(result['status'], 'RESEARCH_NO_VALUE')
        self.assertAlmostEqual(result['expected_profit_per_unit'], -.125)

    def test_plus_money_can_be_value_below_fifty_percent(self):
        result = self.price(win=.4, american_odds=200)
        self.assertAlmostEqual(result['expected_profit_per_unit'], .2)
        self.assertIsNone(result['no_vig_edge'])

    def test_push_uses_conditional_fair_price_and_unconditional_ev(self):
        result = self.price(win=.4, push=.2, american_odds=110)
        self.assertAlmostEqual(result['conditional_win_probability'], .5)
        self.assertAlmostEqual(result['expected_profit_per_unit'], .04)
        self.assertAlmostEqual(result['fair_american'], -100)

    def test_unpriced_and_unusable_quotes_cannot_show_value(self):
        for changes, status in [({'american_odds':None}, 'UNPRICED'),
            ({'quote_at':None}, 'QUOTE_TIME_MISSING'),
            ({'quote_at':NOW-timedelta(seconds=181)}, 'STALE_QUOTE'),
            ({'quote_at':NOW+timedelta(seconds=1)}, 'FUTURE_QUOTE'),
            ({'start':NOW}, 'GAME_STARTED'), ({'win':0.,'push':1.}, 'ALL_PUSH')]:
            result = self.price(**changes)
            self.assertEqual(result['status'], status)
            self.assertIsNone(result['expected_profit_per_unit'])
            self.assertFalse(result['official_eligible'])

    def test_invalid_inputs(self):
        for changes in ({'win':float('nan')}, {'win':.9,'push':.2},
                        {'american_odds':-50}, {'ttl_seconds':0}):
            with self.assertRaises(ValueError):
                self.price(**changes)


class ResearchRunnerTests(unittest.TestCase):
    def json_roundtrip(self, data):
        def encode(value):
            return asdict(value) if is_dataclass(value) else value.isoformat()
        return json.loads(json.dumps(data, default=encode))

    def test_nrfi_runner_deserializes_sources_and_parameters(self):
        from scripts.run_matchup_research import run
        source = FirstInningTests().inputs()
        result = run('nrfi', self.json_roundtrip(source))
        self.assertEqual(result, predict_first_inning(**source))

    def test_td_runner_connects_existing_paths_to_scorer_output(self):
        from scripts.run_matchup_research import run
        fixture = RoleTests()
        allocator = fixture.allocator()
        source = dict(home_usage=fixture.usage('H'), away_usage=fixture.usage('A'),
                      roles=dict(allocator.roles), seed=1,
                      paths=[fixture.path(5, sim=1), fixture.path(5, td=False, sim=2)],
                      player_ids=['HB'])
        result = run('td', self.json_roundtrip(source))
        self.assertEqual(result['probabilities']['HB']['1+'], .5)
        self.assertEqual(len(result['input_sha256']), 64)
        self.assertFalse(result['official_eligible'])


if __name__ == '__main__':
    unittest.main()
