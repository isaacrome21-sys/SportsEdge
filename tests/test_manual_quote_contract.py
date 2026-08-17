import unittest

from sportsedge.engine_registry import (
    EngineDispatchError,
    MANUAL_MARKET_TYPE_TO_ENGINE_MARKET,
    resolve_manual_market_type,
)
from sportsedge.generic_market_engine import generic_market_engine_adapter
from sportsedge.manual_quote import validate_manual_quote


BASE = {
    "game_id": "824514",
    "side": "OVER",
    "line": 0.5,
    "price": -110,
    "paired_side": "UNDER",
    "paired_price": -110,
    "book": "draftkings",
    "observed_at": "2026-08-17T12:00:00-05:00",
    "first_pitch_at": "2026-08-17T12:40:00-05:00",
    "source": "MANUAL",
}


class ManualQuoteContractTests(unittest.TestCase):
    def test_ingestion_shape_is_market_agnostic_for_every_registered_market_type(self):
        for market_type in MANUAL_MARKET_TYPE_TO_ENGINE_MARKET:
            with self.subTest(market_type=market_type):
                row = dict(BASE, market_type=market_type)
                parsed = validate_manual_quote(row)
                self.assertEqual(parsed.market_type, market_type)

    def test_unknown_market_is_accepted_by_ingestion_but_rejected_by_engine_registry(self):
        parsed = validate_manual_quote(dict(BASE, market_type="SOME_FUTURE_MARKET"))
        self.assertEqual(parsed.market_type, "SOME_FUTURE_MARKET")
        with self.assertRaisesRegex(EngineDispatchError, "NO_ENGINE_FOR_MARKET"):
            resolve_manual_market_type(parsed.market_type)

    def test_every_declared_manual_market_type_resolves_to_an_engine(self):
        for market_type, expected in MANUAL_MARKET_TYPE_TO_ENGINE_MARKET.items():
            with self.subTest(market_type=market_type):
                self.assertEqual(resolve_manual_market_type(market_type), expected)

    def test_first_inning_yes_no_engine_probabilities_are_complements(self):
        common = {
            "game_id": "824514",
            "market": "YRFI",
            "entity_id": "824514",
            "line": 0.5,
            "away_mean_runs": 4.5,
            "home_mean_runs": 4.2,
            "total_line": 0.0,
            "first_inning_share": 1.0 / 9.0,
            "simulations": 4000,
            "seed": 17,
        }
        yes = generic_market_engine_adapter(dict(common, side="YES"))["model_p"]
        no = generic_market_engine_adapter(dict(common, side="NO"))["model_p"]
        self.assertAlmostEqual(yes + no, 1.0, places=12)


if __name__ == "__main__":
    unittest.main()
