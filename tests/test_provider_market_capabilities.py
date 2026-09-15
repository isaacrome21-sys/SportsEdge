import json
from pathlib import Path
import unittest


class ProviderMarketCapabilitiesTests(unittest.TestCase):
    def test_espn_and_metered_capabilities_are_explicit(self):
        rows = {x["provider"]: x for x in json.loads(Path("config/market_provider_contract_v1.json").read_text())["rules"]}
        self.assertEqual(set(rows["ESPN_SCOREBOARD"]["markets"]), {"MONEYLINE", "RUN_LINE", "TOTALS"})
        paid = set(rows["THE_ODDS_API"]["markets"])
        self.assertTrue({"TEAM_TOTALS", "NRFI", "YRFI", "PLAYER_PROPS", "ADDITIONAL_DERIVATIVES"}.issubset(paid))


if __name__ == "__main__":
    unittest.main()
