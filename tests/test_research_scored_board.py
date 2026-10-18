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


def fixture(market='NRFI', win=.6, odds=100, qualification_score=80):
    contract = dict(sport='MLB', event_id='SYNTHETIC-GAME', market=market,
                    selection='YES', entity_id=None, line=None, period='FIRST_INNING',
                    rules_id='SYNTHETIC_CONFIRMED_STARTERS', payout_type='WIN_LOSS_PUSH')
    row = dict(quote=dict(quote_id='q1', book='SYNTHETIC', contract=contract,
                          american_odds=odds, quote_at='2026-09-21T11:59:00Z',
                          start='2026-09-21T13:00:00Z'),
                estimate=dict(contract=copy.deepcopy(contract), win=win, push=0,
                              model_id='SYNTHETIC_TEST_ONLY', model_version='v1',
                              artifact_sha256='a' * 64, generated_at='2026-09-21T11:58:00Z',
                              features_as_of='2026-09-21T11:57:00Z',
                              valid_until='2026-09-21T12:05:00Z'))
    if qualification_score is not None:
        row['qualification_score'] = qualification_score
    return row


def board(rows):
    return build_scored_board(rows, now=NOW)


class ScoredBoardTests(unittest.TestCase):
    def test_score_is_upstream_qualification_only_not_economics(self):
        result = board([fixture()]); row = result['rows'][0]
        self.assertAlmostEqual(row['expected_profit_per_unit'], .2)
        self.assertEqual(row['score'], 80.0)
        self.assertEqual(row['score_components'], {'source': 'UPSTREAM_QUALIFICATION_ONLY'})
        self.assertEqual(row['model_win_probability'], .6)
        self.assertEqual(result['score_formula'], 'UPSTREAM_QUALIFICATION_ONLY; EV_AND_EDGE_EXCLUDED')
        self.assertFalse(result['audit']['score_uses_ev'])
        self.assertFalse(result['audit']['score_uses_edge'])
        self.assertFalse(result['audit']['score_calibrated'])
        self.assertFalse(result['audit']['official_eligible'])

    def test_price_or_ev_change_does_not_change_score(self):
        rows = [fixture(odds=-130), fixture(odds=130)]
        result = board(rows)
        self.assertEqual([r['score'] for r in result['rows']], [80.0, 80.0])
        self.assertNotEqual(result['rows'][0]['expected_profit_per_unit'],
                            result['rows'][1]['expected_profit_per_unit'])

    def test_score_can_be_absent_without_inventing_fallback(self):
        result = board([fixture(qualification_score=None)])
        row = result['rows'][0]
        self.assertIsNone(row['score'])
        self.assertEqual(result['scored_rows'], 0)
        self.assertEqual(result['valued_rows'], 1)
        self.assertIn('Research edges', render_scored_board(result))

    def test_best_card_excludes_negative_zero_and_missing_value(self):
        rows = [fixture('POSITIVE'), fixture('NEGATIVE', .4), fixture('ZERO', .5), fixture('MISSING')]
        del rows[-1]['estimate']
        result = board(rows); rendered = render_scored_board(result)
        self.assertEqual(result['submitted_rows'], 4)
        self.assertEqual(result['valued_rows'], 3)
        self.assertEqual(result['scored_rows'], 3)
        self.assertIn('POSITIVE /', rendered)
        for name in ('NEGATIVE /', 'ZERO /', 'MISSING /'):
            self.assertNotIn(name, rendered)
        self.assertIn('EXPERIMENTAL / NOT OFFICIAL', rendered)
        self.assertIn('MISSING /', render_scored_board(result, show_all=True))

    def test_order_best_price_and_limit_and_dedup(self):
        weaker = fixture(odds=-110); stronger = fixture(odds=110)
        stronger['quote']['book'] = 'BETTER_PRICE'
        other = fixture('OTHER', win=.7)
        result = board([weaker, stronger, other])
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
        self.assertEqual(result['valued_rows'], 1)

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

    def test_invalid_qualification_score_fails_row_closed(self):
        for value in (-1, 101, True, float('inf')):
            with self.subTest(value=value):
                row = fixture(qualification_score=value)
                result = board([row])['rows'][0]
                self.assertIsNone(result['score'])
                self.assertEqual(result['note'], 'INVALID_QUALIFICATION_SCORE')

    def test_push_economics_and_no_independence_parlay(self):
        row = fixture(win=.5); row['estimate']['push'] = .2
        result = board([row]); scored = result['rows'][0]
        self.assertAlmostEqual(scored['expected_profit_per_unit'], .2)
        self.assertEqual(scored['score'], 80.0)
        self.assertEqual(scored['score_components']['source'], 'UPSTREAM_QUALIFICATION_ONLY')
        self.assertNotIn('parlay', result)

    def test_price_edge_is_not_expected_return_or_no_vig_edge(self):
        result = board([fixture(win=.6, odds=-130)])
        row = result['rows'][0]
        self.assertAlmostEqual(row['fair_american'], -150)
        self.assertAlmostEqual(row['break_even_probability'], 130 / 230)
        self.assertAlmostEqual(row['raw_price_edge'], .6 - 130 / 230)
        self.assertAlmostEqual(row['expected_profit_per_unit'], .6 * 100 / 130 - .4)
        self.assertIsNone(row['no_vig_edge'])
        text = render_scored_board(result, min_score=0)
        self.assertIn('Raw edge (pp)', text)
        self.assertIn('+3.48', text)
        self.assertIn('+0.062', text)
        self.assertIn('2026-09-21T11:59:00Z', text)
        self.assertIn('2026-09-21T13:00:00Z', text)

    def test_push_fair_odds_use_conditional_probability(self):
        item = fixture(win=.5, odds=100)
        item['estimate']['push'] = .2
        row = board([item])['rows'][0]
        self.assertAlmostEqual(row['conditional_win_probability'], .625)
        self.assertAlmostEqual(row['fair_american'], -166.6666666667)
        self.assertAlmostEqual(row['raw_price_edge'], .125)
        self.assertAlmostEqual(row['expected_profit_per_unit'], .2)

    def test_stale_price_has_no_display_edge_but_retains_quote_time(self):
        item = fixture()
        item['quote']['quote_at'] = '2026-09-21T11:00:00Z'
        result = board([item]); row = result['rows'][0]
        self.assertIsNone(row['raw_price_edge'])
        self.assertIsNone(row['expected_profit_per_unit'])
        self.assertIsNone(row['score'])
        self.assertIn('11:00:00', render_scored_board(result, show_all=True))

    def test_all_push_has_no_finite_fair_odds_or_ranking(self):
        item = fixture(win=0)
        item['estimate']['push'] = 1
        row = board([item])['rows'][0]
        self.assertIsNone(row['fair_american'])
        self.assertIsNone(row['raw_price_edge'])
        self.assertIsNone(row['score'])
        self.assertEqual(row['note'], 'ALL_PUSH')

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

    def test_no_positive_value_means_no_forced_research_edge(self):
        text = render_scored_board(board([fixture(win=.4)]))
        self.assertIn('No current positive-EV research edges', text)

    def test_small_positive_edge_needs_qualification_cutoff_only_when_score_exists(self):
        result = board([fixture(win=.501, qualification_score=50)])
        self.assertGreater(result['rows'][0]['expected_profit_per_unit'], 0)
        self.assertIn('No current positive-EV research edges', render_scored_board(result))
        self.assertIn('| NRFI /', render_scored_board(result, min_score=0))

    def test_exact_break_even_never_renders_as_research_edge(self):
        p = 112 / 212
        result = board([fixture(win=p, odds=-112, qualification_score=100)])
        row = result['rows'][0]
        self.assertAlmostEqual(row['raw_price_edge'], 0.0)
        self.assertAlmostEqual(row['expected_profit_per_unit'], 0.0)
        self.assertNotIn('| NRFI /', render_scored_board(result, min_score=0))

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
        self.assertIn('80.0', proc.stdout)
        self.assertIn('EXPERIMENTAL / NOT OFFICIAL', proc.stdout)
        self.assertIn('Research edges', proc.stdout)


if __name__ == '__main__':
    unittest.main()
