import copy
from datetime import datetime, timezone
import unittest

from sportsedge.research.nfl_card_integrity import (
    NFLCardIntegrityError,
    build_nfl_research_card,
)
from sportsedge.source_lineage import canonical_json_sha256

NOW = datetime(2026, 9, 28, 13, 5, tzinfo=timezone.utc)


def input_snapshot():
    return {
        'as_of': '2026-09-28T12:59:00+00:00',
        'game_id': 'PHI-CHI',
        'injuries': {'PHI': {'A.J. Brown': 'OUT', 'Dallas Goedert': 'OUT'}},
        'roles': {'CHI': {'DANDRE_SWIFT': {'carries': 16.5}, 'MONANGAI': {'carries': 10.5}}},
        'qb': {'CHI': {'starter': 'KEENUM', 'attempts': 29.0}},
    }


def forecast(snapshot=None, generated_at='2026-09-28T13:02:00+00:00'):
    snapshot = snapshot or input_snapshot()
    return {
        'input_sha256': canonical_json_sha256(snapshot),
        'generated_at': generated_at,
        'phi_points': 22.1,
        'chi_points': 19.7,
    }


def row(*, market='RUSH_YARDS', entity_id='DANDRE_SWIFT', team='CHI',
        win=.57, odds=-110, quote_at='2026-09-28T13:03:00+00:00', score=84):
    contract = dict(sport='NFL', event_id='PHI-CHI', market=market,
                    selection='OVER', entity_id=entity_id, line=62.5,
                    period='FULL_GAME', rules_id='DK_NFL_2026',
                    payout_type='WIN_LOSS_PUSH')
    item = {
        'team': team,
        'quote': dict(quote_id='dk-current', book='DraftKings', contract=contract,
                      american_odds=odds, quote_at=quote_at,
                      start='2026-09-28T17:00:00+00:00'),
        'estimate': dict(contract=copy.deepcopy(contract), win=win, push=0,
                         model_id='NFL_RESEARCH', model_version='v1',
                         artifact_sha256='a' * 64,
                         generated_at='2026-09-28T13:02:00+00:00',
                         features_as_of='2026-09-28T12:59:00+00:00',
                         valid_until='2026-09-28T13:15:00+00:00'),
    }
    if score is not None:
        item['qualification_score'] = score
    return item


class NFLCardIntegrityTests(unittest.TestCase):
    def base(self):
        snap = input_snapshot()
        return dict(now=NOW, forecast_provenance=forecast(snap),
                    current_input_snapshot=snap)

    def test_current_positive_edge_is_experimental_and_team_verified(self):
        card = build_nfl_research_card(
            [row()], roster_team_by_entity_id={'DANDRE_SWIFT': 'CHI'},
            splits_context={'source': 'ScoresAndOdds', 'tickets': 55}, **self.base())
        self.assertEqual(card['authority_label'], 'EXPERIMENTAL / NOT OFFICIAL')
        self.assertFalse(card['official'])
        self.assertFalse(card['governance']['crown_allowed'])
        self.assertEqual(card['splits']['source'], 'ScoresAndOdds')
        self.assertEqual(len(card['research_edges']), 1)
        edge = card['research_edges'][0]
        self.assertEqual(edge['display_team'], 'CHI')
        self.assertTrue(edge['team_binding_verified'])
        self.assertEqual(edge['display_label'], 'RESEARCH EDGE')

    def test_changed_injury_or_role_snapshot_blocks_reused_forecast(self):
        old = input_snapshot()
        current = copy.deepcopy(old)
        current['roles']['CHI']['DANDRE_SWIFT']['carries'] = 14.0
        with self.assertRaisesRegex(NFLCardIntegrityError, 'RECOMPUTE_OR_BLOCK'):
            build_nfl_research_card([row()], now=NOW,
                forecast_provenance=forecast(old), current_input_snapshot=current)

    def test_forecast_predating_current_snapshot_blocks(self):
        snap = input_snapshot()
        with self.assertRaisesRegex(NFLCardIntegrityError, 'FORECAST_PREDATES_INPUTS'):
            build_nfl_research_card([row()], now=NOW,
                forecast_provenance=forecast(snap, '2026-09-28T12:58:00+00:00'),
                current_input_snapshot=snap)

    def test_break_even_minus_112_is_excluded(self):
        p = 112 / 212
        card = build_nfl_research_card([row(win=p, odds=-112, score=100)], **self.base())
        self.assertEqual(card['research_edges'], [])
        reasons = set(card['excluded'][0]['reasons'])
        self.assertIn('NON_POSITIVE_EV', reasons)
        self.assertIn('NO_BREAK_EVEN_EDGE', reasons)

    def test_chicago_team_total_53_3_at_minus_115_is_excluded(self):
        item = row(market='TEAM_TOTAL', entity_id=None, team='CHI', win=.533, odds=-115)
        item['quote']['contract']['line'] = 19.5
        item['estimate']['contract']['line'] = 19.5
        card = build_nfl_research_card([item], **self.base())
        self.assertEqual(card['research_edges'], [])
        reasons = set(card['excluded'][0]['reasons'])
        self.assertIn('NON_POSITIVE_EV', reasons)
        self.assertIn('NO_BREAK_EVEN_EDGE', reasons)

    def test_stale_dk_quote_is_excluded(self):
        card = build_nfl_research_card(
            [row(quote_at='2026-09-28T12:50:00+00:00')], **self.base())
        self.assertEqual(card['research_edges'], [])
        reasons = set(card['excluded'][0]['reasons'])
        self.assertIn('STALE_QUOTE', reasons)

    def test_swift_wrong_team_binding_fails_closed(self):
        with self.assertRaisesRegex(NFLCardIntegrityError, 'PLAYER_TEAM_BINDING_MISMATCH'):
            build_nfl_research_card([row(team='PHI')],
                roster_team_by_entity_id={'DANDRE_SWIFT': 'CHI'}, **self.base())

    def test_unverified_player_has_no_logo_team(self):
        card = build_nfl_research_card([row()], **self.base())
        edge = card['research_edges'][0]
        self.assertIsNone(edge['display_team'])
        self.assertFalse(edge['team_binding_verified'])

    def test_splits_source_mismatch_fails(self):
        with self.assertRaisesRegex(NFLCardIntegrityError, 'SPLITS_SOURCE_MISMATCH'):
            build_nfl_research_card([row()], splits_context={'source': 'Unknown'}, **self.base())

    def test_non_nfl_contract_fails(self):
        item = row()
        item['quote']['contract']['sport'] = 'CFB'
        item['estimate']['contract']['sport'] = 'CFB'
        with self.assertRaisesRegex(NFLCardIntegrityError, 'NON_NFL_CONTRACT'):
            build_nfl_research_card([item], **self.base())


if __name__ == '__main__':
    unittest.main()
