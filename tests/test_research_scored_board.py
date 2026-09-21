import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sportsedge.research.scored_board import build_scored_board, render_scored_board

NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


def fixture(market='NRFI', win=.6, odds=100):
    contract = dict(sport='MLB', event_id='SYNTHETIC-GAME', market=market,
                    selection='YES', entity_id=None, line=None, period='FIRST_INNING',
                    rules_id='SYNTHETIC_CONFIRMED_STARTERS', payout_type='WIN_LOSS_PUSH')
    return dict(quote=dict(quote_id='q1', book='SYNTHETIC', contract=contract,
                          american_odds=odds, quote_at='2026-09-21T11:59:00Z',
                          start='2026-09-21T13:00:00Z'),
                estimate=dict(contract=copy.deepcopy(contract), win=win, push=0,
                              model_id='SYNTHETIC_TEST_ONLY', model_version='v1',
                              artifact_sha256='a' * 64, generated_at='2026-09-21T11:58:00Z',
                              features_as_of='2026-09-21T11:57:00Z',
                              valid_until='2026-09-21T12:05:00Z'))


def board(rows):
    return build_scored_board(rows, now=NOW)


class ScoredBoardTests(unittest.TestCase):
    def test_score_is_disclosed_value_plus_likelihood_not_probability(self):
        result = board([fixture()]); row = result['rows'][0]
        self.assertAlmostEqual(row['expected_profit_per_unit'], .2)
        self.assertEqual(row['score'], 64.7)
        self.assertEqual(row['model_win_probability'], .6)
        self.assertFalse(result['audit']['score_calibrated'])
        self.assertFalse(result['audit']['official_eligible'])

    def test_best_card_excludes_negative_zero_and_missing_value(self):
        rows = [fixture('POSITIVE'), fixture('NEGATIVE', .4), fixture('ZERO', .5), fixture('MISSING')]
        del rows[-1]['estimate']
        result = board(rows); rendered = render_scored_board(result)
        self.assertEqual(result['submitted_rows'], 4)
        self.assertEqual(result['scored_rows'], 3)
        self.assertIn('POSITIVE /', rendered)
        for name in ('NEGATIVE /', 'ZERO /', 'MISSING /', 'OFFICIAL', 'Truth Gate'):
            self.assertNotIn(name, rendered)
        self.assertIn('MISSING /', render_scored_board(result, show_all=True))

    def test_order_best_price_and_limit_and_dedup(self):
        weaker = fixture(odds=-110); stronger = fixture(odds=110)
        stronger['quote']['book'] = 'BETTER_PRICE'
        other = fixture('OTHER', win=.7)
        result = board([weaker, stronger, other])
        self.assertGreater(result['rows'][0]['score'], result['rows'][1]['score'])
        text = render_scored_board(result)
        self.assertIn('BETTER_PRICE', text)
        self.assertNotIn('SYNTHETIC / -110', text)
        self.assertEqual(text.count('| NRFI /'), 1)
        self.assertNotIn('| NRFI /', render_scored_board(result, limit=1))

    def test_every_identity_field_must_match(self):
        for field, value in dict(sport='NFL', event_id='OTHER', market='YRFI',
                                 selection='NO', entity_id='PLAYER', line=.5,
                                 period='FULL_GAME', rules_id='OTHER', payout_type='DEAD_HEAT').items():
            with self.subTest(field=field):
                row = fixture(); row['estimate']['contract'][field] = value
                result = board([row])['rows'][0]
                self.assertIsNone(result['score'])
                self.assertEqual(result['note'], 'MARKET_IDENTITY_MISMATCH')

    def test_bad_rows_remain_and_do_not_hide_valid_rows(self):
        rows = [None, {}, fixture()]
        rows[1]['quote'] = {'contract': {}}
        result = board(rows)
        self.assertEqual(len(result['rows']), 3)
        self.assertEqual(result['scored_rows'], 1)

    def test_stale_future_started_and_source_fail_closed(self):
        cases = [('quote', 'quote_at', '2026-09-21T11:00:00Z'),
                 ('quote', 'quote_at', '2026-09-21T12:01:00Z'),
                 ('quote', 'start', NOW.isoformat()),
                 ('estimate', 'generated_at', '2026-09-21T12:01:00Z'),
                 ('estimate', 'features_as_of', '2026-09-21T11:59:00Z'),
                 ('estimate', 'features_as_of', '2026-09-21T09:59:00Z'),
                 ('estimate', 'valid_until', NOW.isoformat()),
                 ('estimate', 'artifact_sha256', 'missing'),
                 ('estimate', 'push', .8), ('estimate', 'win', True)]
        for section, field, value in cases:
            with self.subTest(field=field, value=value):
                row = fixture(); row[section][field] = value
                self.assertIsNone(board([row])['rows'][0]['score'])

    def test_push_economics_and_no_independence_parlay(self):
        row = fixture(win=.5); row['estimate']['push'] = .2
        result = board([row]); scored = result['rows'][0]
        self.assertAlmostEqual(scored['expected_profit_per_unit'], .2)
        self.assertAlmostEqual(scored['score_components']['likelihood_points'], 18.75)
        self.assertNotIn('parlay', result)

    def test_other_markets_need_their_own_estimate_and_settlement(self):
        rows = []
        for sport, market, period in [('NFL', 'OFFENSIVE_TD_1+', 'REGULATION'),
                                      ('CFB', 'PASS_YARDS', 'FULL_GAME'),
                                      ('MLB', 'YRFI', 'FIRST_INNING')]:
            row = fixture(market)
            for obj in (row['quote'], row['estimate']):
                obj['contract'].update(sport=sport, period=period)
            rows.append(row)
        self.assertEqual(board(rows)['scored_rows'], 3)
        for obj in (rows[0]['quote'], rows[0]['estimate']):
            obj['contract']['payout_type'] = 'DEAD_HEAT'
        self.assertEqual(board(rows)['scored_rows'], 2)

    def test_no_positive_value_means_no_forced_pick(self):
        self.assertIn('No current positive-EV', render_scored_board(board([fixture(win=.4)])))

    def test_small_positive_edge_does_not_fill_best_card(self):
        result = board([fixture(win=.501)])
        self.assertGreater(result['rows'][0]['expected_profit_per_unit'], 0)
        self.assertIn('No current positive-EV', render_scored_board(result))
        self.assertIn('| NRFI /', render_scored_board(result, min_score=0))

    def test_gate_flags_do_not_hide_research_data(self):
        row = fixture(); row.update(official_eligible=False, predictive_gate='FAIL', stake=0)
        self.assertEqual(board([row])['scored_rows'], 1)

    def test_markdown_escapes_labels(self):
        row = fixture('NRFI|extra\nline')
        text = render_scored_board(board([row]))
        self.assertIn('NRFI\\|extra line', text)

    def test_cli_renders_scored_card(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input.json'
            path.write_text(json.dumps({'rows': [fixture()], 'now': NOW.isoformat()}))
            proc = subprocess.run([sys.executable, str(root / 'scripts/run_matchup_research.py'),
                                   'board', str(path), '--format', 'markdown'],
                                  cwd=root, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn('64.7', proc.stdout)
        self.assertIn('Top positive-EV', proc.stdout)


if __name__ == '__main__':
    unittest.main()
