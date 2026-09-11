import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_market_value.py"
SPEC = importlib.util.spec_from_file_location("run_market_value", SCRIPT)
run_market_value = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(run_market_value)


class RunMarketValueTests(unittest.TestCase):
    def test_manual_payload_produces_separate_paper_market_decision(self):
        payload = {
            "reference_mode": "PINNACLE_ONLY_V1",
            "independent_model_selection": "OVER",
            "references": [
                {
                    "book": "Pinnacle",
                    "market_key": "mlb:123:pitcher_k:5.5",
                    "captured_at": "2026-09-11T12:00:00Z",
                    "source": "manual:screenshot",
                    "prices": {"OVER": -150, "UNDER": 130},
                }
            ],
            "executions": [
                {
                    "book": "DraftKings",
                    "market_key": "mlb:123:pitcher_k:5.5",
                    "selection": "OVER",
                    "american_odds": -130,
                    "captured_at": "2026-09-11T12:01:00Z",
                    "source": "manual:screenshot",
                },
                {
                    "book": "DraftKings",
                    "market_key": "mlb:123:pitcher_k:5.5",
                    "selection": "UNDER",
                    "american_odds": 125,
                    "captured_at": "2026-09-11T12:01:00Z",
                    "source": "manual:screenshot",
                },
            ],
        }
        result = run_market_value.run(payload)
        decision = result["decision"]
        self.assertEqual(decision["decision"], "PAPER_BET")
        self.assertEqual(decision["lane_status"], "PAPER")
        self.assertEqual(decision["selection"], "OVER")
        self.assertIn("market_fair_p", decision)
        self.assertNotIn("model_p", decision)
        self.assertIsNone(result["closing_snapshot"])

    def test_close_is_emitted_only_as_separate_snapshot(self):
        payload = {
            "reference_mode": "PINNACLE_ONLY_V1",
            "references": [
                {
                    "book": "Pinnacle",
                    "market_key": "mlb:123:pitcher_k:5.5",
                    "captured_at": "2026-09-11T12:00:00Z",
                    "source": "manual:open",
                    "prices": {"OVER": -150, "UNDER": 130},
                }
            ],
            "executions": [
                {
                    "book": "DraftKings",
                    "market_key": "mlb:123:pitcher_k:5.5",
                    "selection": "OVER",
                    "american_odds": -130,
                    "captured_at": "2026-09-11T12:01:00Z",
                    "source": "manual:open",
                }
            ],
            "closing_references": [
                {
                    "book": "Pinnacle",
                    "market_key": "mlb:123:pitcher_k:5.5",
                    "captured_at": "2026-09-11T23:00:00Z",
                    "source": "manual:close",
                    "prices": {"OVER": -165, "UNDER": 145},
                }
            ],
        }
        result = run_market_value.run(payload)
        self.assertEqual(
            result["decision"]["execution_american_odds"],
            -130,
        )
        self.assertEqual(
            result["closing_snapshot"]["original_execution_american_odds"],
            -130,
        )
        self.assertNotEqual(
            result["closing_snapshot"]["close_market_fair_p"],
            result["decision"]["market_fair_p"],
        )


if __name__ == "__main__":
    unittest.main()
