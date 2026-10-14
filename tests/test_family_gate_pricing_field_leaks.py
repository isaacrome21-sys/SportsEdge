import unittest
from unittest.mock import patch
from sportsedge.registry_gate import gate_payload


FIELDS = ('ev_per_dollar', 'fair_decimal', 'model_conditional_p', 'model_push_p',
          'push_p', 'loss_p', 'edge_pp', 'edge_over_break_even_pp',
          'edge_vs_dk_no_vig_pp', 'home_mean', 'away_mean', 'projected_total',
          'projected_home_margin')


class FamilyPricingFieldTests(unittest.TestCase):
    def test_each_production_pricing_field_triggers_refusal(self):
        with patch('sportsedge.registry_gate.illinois_exclusion', return_value=None):
            for sport in ('CFB', 'NBA', 'CBB'):
                for field in FIELDS:
                    with self.subTest(sport=sport, field=field):
                        card = {'sport': sport, 'market': 'TOTAL', field: .25}
                        result, stats = gate_payload(card)
                        self.assertNotIn(field, result)
                        self.assertTrue(result['registry_enforced'])
                        self.assertEqual(result['blocker'], 'NO_VALIDATION')
                        self.assertEqual(stats['blocked'], 1)

    def test_sibling_fields_do_not_survive_a_model_probability_refusal(self):
        result, stats = gate_payload({'sport': 'NBA', 'market': 'TOTAL',
                                     'model_p': .6, **dict.fromkeys(FIELDS, .25)})
        self.assertTrue(result['registry_enforced'])
        self.assertEqual(stats['blocked'], 1)
        for field in FIELDS:
            self.assertNotIn(field, result)

    def test_nested_ev_only_row_is_refused(self):
        result, stats = gate_payload({'sport': 'NBA', 'results': [
            {'market': 'TOTAL', 'ev_per_dollar': .25, 'fair_decimal': 1.4}]})
        self.assertNotIn('ev_per_dollar', result['results'][0])
        self.assertNotIn('fair_decimal', result['results'][0])
        self.assertEqual(stats['blocked'], 1)

    def test_other_sports_keep_their_fields(self):
        for sport in ('NFL', 'MLB'):
            row = {'sport': sport, 'market': 'TOTAL', 'ev_per_dollar': .25}
            result, stats = gate_payload(row)
            self.assertEqual(result, row)
            self.assertEqual(stats['checked'], 0)


if __name__ == '__main__':
    unittest.main()
