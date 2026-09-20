from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_cfb_prop_model_candidate_tested",
    ROOT / "scripts/run_cfb_prop_model_candidate.py",
)
CANDIDATE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(CANDIDATE)


class CFBPropModelCandidateTests(unittest.TestCase):
    def test_candidate_rows_are_never_official(self):
        report = {
            "results": [{
                "provider_market": "player_pass_yds", "model_p": 0.61,
                "fair_market_p": 0.55, "ev_per_dollar": 0.08,
                "bet_status": "OFFICIAL_BET", "official_eligible": True,
            }],
            "summary": {"official_bets": 1}, "governance": {},
        }
        out = CANDIDATE._candidateize(report)
        row = out["results"][0]
        self.assertEqual(row["decision_tier"], "MODEL_CANDIDATE")
        self.assertEqual(row["bet_status"], "BLOCKED")
        self.assertFalse(row["official_eligible"])
        self.assertFalse(row["promotion_authority"])
        self.assertEqual(out["summary"]["official_bets"], 0)
        self.assertFalse(out["governance"]["official_bets_allowed"])
        self.assertFalse(out["governance"]["promotion_authority"])

    def test_nonfinite_model_probability_is_not_candidate(self):
        report = {
            "results": [{
                "provider_market": "player_pass_yds", "model_p": float("nan"),
                "fair_market_p": 0.55, "ev_per_dollar": 0.08,
            }], "summary": {},
        }
        out = CANDIDATE._candidateize(report)
        self.assertEqual(out["results"][0]["model_candidate_status"], "BLOCKED")
        self.assertEqual(out["summary"]["model_candidate_rows"], 0)

    def test_bettor_facing_cfb_surface_remains_no_engine(self):
        surface = json.loads(
            (ROOT / "config/football_prop_engine_surface.json").read_text(encoding="utf-8")
        )
        self.assertEqual(surface["sports"]["CFB"]["engine_state"], "NO_ENGINE")
        self.assertEqual(surface["sports"]["CFB"]["readiness_state"], "NO_ENGINE")
        self.assertIn("CFB", surface["explicit_no_engine"])


if __name__ == "__main__":
    unittest.main()
