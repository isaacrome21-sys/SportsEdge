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
        self.assertEqual(row["presentation_label"], "LEAN")
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
        self.assertEqual(out["results"][0]["presentation_label"], "NO_PLAY")
        self.assertEqual(out["summary"]["model_candidate_rows"], 0)


    def test_one_sided_anytime_td_can_be_research_candidate_without_fair_market_p(self):
        report = {
            "results": [{
                "provider_market": "player_anytime_td", "model_p": 0.42,
                "fair_market_p": None,
                "market_no_vig_p_status": "UNAVAILABLE_ONE_SIDED",
                "ev_per_dollar": 0.05,
                "quote_fresh": True,
                "bet_status": "BLOCKED", "official_eligible": False,
            }],
            "summary": {"official_bets": 0}, "governance": {},
        }
        out = CANDIDATE._candidateize(report)
        row = out["results"][0]
        self.assertEqual(row["model_candidate_status"], "READY")
        self.assertEqual(row["decision_tier"], "MODEL_CANDIDATE")
        self.assertEqual(row["bet_status"], "BLOCKED")
        self.assertFalse(row["official_eligible"])
        self.assertEqual(out["summary"]["model_candidate_rows"], 1)


    def test_proxy_odds_blocks_unresolved_player_without_poisoning_known_player(self):
        live = {
            "games": [{
                "provider_event_id": "evt-1",
                "home_usage": {"players": [
                    {"player_name": "Known Quarterback"},
                ]},
                "away_usage": {"players": [
                    {"player_name": "Known Runner"},
                ]},
            }],
        }
        odds = {
            "observed_at": "2026-10-02T14:00:00+00:00",
            "events": [{
                "id": "evt-1",
                "bookmakers": [{
                    "key": "draftkings",
                    "markets": [{
                        "key": "player_pass_yds",
                        "outcomes": [
                            {"name": "Over", "description": "Known Quarterback", "price": -110, "point": 250.5},
                            {"name": "Under", "description": "Known Quarterback", "price": -110, "point": 250.5},
                            {"name": "Over", "description": "Jo Silver", "price": -110, "point": 199.5},
                            {"name": "Under", "description": "Jo Silver", "price": -110, "point": 199.5},
                        ],
                    }],
                }],
            }],
        }
        filtered, blocks = CANDIDATE._filter_proxy_odds_by_live_identity(
            odds, live=live
        )
        outcomes = filtered["events"][0]["bookmakers"][0]["markets"][0]["outcomes"]
        self.assertEqual(
            [row["description"] for row in outcomes],
            ["Known Quarterback", "Known Quarterback"],
        )
        self.assertEqual(len(blocks), 2)
        self.assertTrue(all(row["player_name"] == "Jo Silver" for row in blocks))
        self.assertTrue(all(row["model_p"] is None for row in blocks))
        self.assertTrue(all(row["official_eligible"] is False for row in blocks))
        self.assertEqual(
            len(odds["events"][0]["bookmakers"][0]["markets"][0]["outcomes"]),
            4,
        )

    def test_proxy_network_scope_excludes_kicker_and_defender_markets(self):
        self.assertIn("player_pass_yds", CANDIDATE.CFB_PROXY_PROVIDER_MARKETS)
        self.assertIn("player_anytime_td", CANDIDATE.CFB_PROXY_PROVIDER_MARKETS)
        self.assertNotIn("player_field_goals", CANDIDATE.CFB_PROXY_PROVIDER_MARKETS)
        self.assertNotIn("player_sacks", CANDIDATE.CFB_PROXY_PROVIDER_MARKETS)

    def test_network_odds_requires_key_after_live_game_identity_exists(self):
        live = {"games": [{"provider_event_id": "evt-1"}]}
        original = CANDIDATE.os.environ.copy()
        try:
            for name in (
                "SPORTSEDGE_ODDS_API_KEY", "SPORTSEDGE_ODDS_API_KEY_2",
                "SPORTSEDGE_ODDS_API_KEY_3", "SPORTSEDGE_ODDS_API_KEY_4",
                "ODDS_API_KEY",
            ):
                CANDIDATE.os.environ.pop(name, None)
            with self.assertRaisesRegex(
                CANDIDATE.CFBPropCandidateError,
                "CFB_PROP_CANDIDATE_ODDS_API_KEY_REQUIRED",
            ):
                CANDIDATE._network_odds(
                    live=live,
                    current=CANDIDATE.datetime(2026, 10, 2, tzinfo=CANDIDATE.timezone.utc),
                )
        finally:
            CANDIDATE.os.environ.clear()
            CANDIDATE.os.environ.update(original)

    def test_bettor_facing_cfb_surface_remains_no_engine(self):
        surface = json.loads(
            (ROOT / "config/football_prop_engine_surface.json").read_text(encoding="utf-8")
        )
        self.assertEqual(surface["sports"]["CFB"]["engine_state"], "NO_ENGINE")
        self.assertEqual(surface["sports"]["CFB"]["readiness_state"], "NO_ENGINE")
        self.assertIn("CFB", surface["explicit_no_engine"])


if __name__ == "__main__":
    unittest.main()
