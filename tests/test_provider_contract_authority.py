import json
from pathlib import Path
import unittest


class ProviderContractAuthorityTests(unittest.TestCase):
    def test_contract_and_context_cli_are_non_authoritative(self):
        contract = json.loads(Path("config/market_provider_contract_v1.json").read_text())
        self.assertEqual(contract["authority"], "ROUTING_AND_PROVENANCE_ONLY")
        self.assertFalse(contract["promotion_authority"])
        self.assertFalse(contract["model_p_authority"])
        cli = Path("scripts/run_free_mlb_game_markets.py").read_text()
        for marker in ('"model_p": None', '"promotion_authority": False', '"staking_authority": False', '"official_authority": False'):
            self.assertIn(marker, cli)


if __name__ == "__main__":
    unittest.main()
