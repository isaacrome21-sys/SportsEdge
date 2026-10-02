import unittest

from sportsedge.engine_registry import engine_registry, resolve_manual_market_type
from sportsedge.mlb_lines_intake import parse_lines


class MlbF5PhoneWireTests(unittest.TestCase):
    def test_phone_f5_aliases_resolve_and_share_session(self):
        text = "\n".join(
            [
                "Boston Red Sox @ New York Yankees",
                "F5 ML -120 +110",
                "F5 RL -0.5 -115 -105",
                "F5 total 4.5 -110 -110",
                "Boston Red Sox F5 TT 2.5 -115 -105",
            ]
        )
        rows = parse_lines(text)
        markets = [row.market for row in rows]
        self.assertEqual(
            markets,
            [
                "FIRST_FIVE_MONEYLINE",
                "FIRST_FIVE_RUN_LINE",
                "FIRST_FIVE_TOTAL",
                "FIRST_FIVE_TEAM_TOTAL",
            ],
        )
        resolved = [resolve_manual_market_type(market) for market in markets]
        self.assertEqual(
            resolved,
            ["F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"],
        )
        registry = engine_registry()
        shared = registry["F5_MONEYLINE"]
        self.assertTrue(callable(shared))
        self.assertTrue(all(registry[market] is shared for market in resolved))


if __name__ == "__main__":
    unittest.main()
