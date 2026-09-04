from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def _flatten(groups):
    out = []
    for values in groups.values():
        out.extend(values)
    return out


class ResearchMarketCoverageTests(unittest.TestCase):
    def test_every_mlb_market_has_exactly_one_research_family(self):
        surface = _load("config/mlb_market_surface.json")
        coverage = _load("config/cross_sport_research_market_coverage_v1.json")
        declared = {row["market"] for row in surface["markets"]}
        mapped = _flatten(coverage["MLB"])
        self.assertEqual(len(mapped), len(set(mapped)), "MLB research coverage contains duplicate market assignments")
        self.assertEqual(declared, set(mapped))

    def test_every_football_market_has_exactly_one_research_family(self):
        surface = _load("config/football_market_surface.json")
        coverage = _load("config/cross_sport_research_market_coverage_v1.json")
        declared = {row["market"] for row in surface["markets"]}
        mapped = _flatten(coverage["FOOTBALL"])
        self.assertEqual(len(mapped), len(set(mapped)), "football research coverage contains duplicate market assignments")
        self.assertEqual(declared, set(mapped))

    def test_research_coverage_cannot_claim_production_promotion(self):
        coverage = _load("config/cross_sport_research_market_coverage_v1.json")
        self.assertEqual(coverage["status"], "RESEARCH_ONLY")
        self.assertIs(coverage["production_eligibility_changed"], False)


if __name__ == "__main__":
    unittest.main()
