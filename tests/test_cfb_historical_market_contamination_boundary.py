import json
import tempfile
import unittest
from pathlib import Path

from scripts.materialize_cfb_historical_market_archive import _load_contract

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / 'config/research/cfb_historical_market_source_v1.json'

class CFBHistoricalMarketContaminationBoundaryTests(unittest.TestCase):
    def test_checked_contract_forbids_predictive_market_features(self):
        payload = _load_contract(CONTRACT)
        self.assertIs(payload['authority']['feature_authority'], False)
        self.assertNotIn('candidate_feature_research_when_separately_pit_safe', payload['allowed_uses'])
        for required in (
            'predictive_model_features','model_training_inputs','model_calibration_inputs',
            'model_p_generation','paired_no_vig_market_benchmark','decision_close_clv_evidence',
            'truth_gate_evidence','promotion_evidence','staking_authority','official_bet_authority'):
            self.assertIn(required, payload['forbidden_uses'])
        self.assertIs(payload['evidence_limitations']['paired_two_sided_quote_certified'], False)

    def test_predictive_feature_use_fails_closed_even_if_called_pit_safe(self):
        payload = json.loads(CONTRACT.read_text())
        payload['allowed_uses'].append('candidate_feature_research_when_separately_pit_safe')
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'contract.json'
            p.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, 'USE_PROJECTION_INVALID'):
                _load_contract(p)

    def test_missing_forbidden_use_fails_closed(self):
        payload = json.loads(CONTRACT.read_text())
        payload['forbidden_uses'].remove('model_training_inputs')
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'contract.json'
            p.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, 'USE_PROJECTION_INVALID'):
                _load_contract(p)

    def test_feature_authority_true_fails_closed(self):
        payload = json.loads(CONTRACT.read_text())
        payload['authority']['feature_authority'] = True
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'contract.json'
            p.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, 'FORBIDDEN_AUTHORITY_OR_LIMIT'):
                _load_contract(p)

if __name__ == '__main__':
    unittest.main()
