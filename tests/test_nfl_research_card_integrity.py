import unittest

from sportsedge.sports.nfl.prop_edge_surface import american_implied_probability
from sportsedge.sports.nfl.research_card import (
    AUTHORITY_LABEL,
    NFLResearchCardError,
    build_nfl_research_card,
)


class NFLResearchCardIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.base = {
            "forecast_provenance": {
                "input_fingerprint": "current-roles-and-injuries",
                "generated_at": "2026-09-28T13:00:00Z",
                "home_points": 22.1,
                "away_points": 19.7,
            },
            "current_input_fingerprint": "current-roles-and-injuries",
            "current_input_as_of": "2026-09-28T12:59:00Z",
            "as_of": "2026-09-28T13:05:00Z",
        }

    @staticmethod
    def prop_row(**overrides):
        row = {
            "sport": "NFL",
            "game_id": "PHI-CHI",
            "provider_market": "player_rush_yds",
            "player_id": "swift",
            "player_name": "D'Andre Swift",
            "team": "CHI",
            "side": "over",
            "line": 62.5,
            "model_p": 0.57,
            "push_p": 0.0,
            "american_odds": -110,
            "ev_per_dollar": 0.05,
            "quote_timestamp": "2026-09-28T13:01:00Z",
            "quote_fresh": True,
            # This is intentionally the old surface score. The publish contract
            # must not reuse it because it can contain EV/edge.
            "score": 99.0,
            "grade": "A+",
            "crown": True,
            "pick": True,
        }
        row.update(overrides)
        return row

    def test_current_positive_ev_prop_is_research_only_without_crown(self):
        payload = {"sport": "NFL", "results": [self.prop_row()]}
        card = build_nfl_research_card(
            prop_run_payload=payload,
            roster_team_by_player_id={"swift": "CHI"},
            splits_context={"tickets": 54, "handle": 51},
            **self.base,
        )
        self.assertEqual(card["authority_label"], AUTHORITY_LABEL)
        self.assertFalse(card["official"])
        self.assertFalse(card["governance"]["crown_allowed"])
        self.assertEqual(card["splits"]["source"], "ScoresAndOdds")

        row = card["props"]["research_edges"][0]
        self.assertEqual(row["display_team"], "CHI")
        self.assertTrue(row["team_binding_verified"])
        self.assertIsNone(row["score"])
        self.assertIsNone(row["grade"])
        self.assertNotIn("crown", row)
        self.assertNotIn("pick", row)
        self.assertEqual(row["display_label"], "RESEARCH EDGE")

    def test_zero_ev_at_break_even_is_cut(self):
        p = american_implied_probability(-112)
        payload = {
            "sport": "NFL",
            "results": [
                self.prop_row(
                    player_id="zero",
                    player_name="Zero Edge",
                    team="CHI",
                    model_p=p,
                    american_odds=-112,
                    ev_per_dollar=0.0,
                )
            ],
        }
        card = build_nfl_research_card(
            prop_run_payload=payload,
            roster_team_by_player_id={"zero": "CHI"},
            **self.base,
        )
        self.assertEqual(card["props"]["research_edges"], [])
        reasons = set(card["props"]["excluded"][0]["reasons"])
        self.assertIn("NON_POSITIVE_EV", reasons)
        self.assertIn("NO_BREAK_EVEN_EDGE", reasons)

    def test_negative_ev_chicago_team_total_shape_is_cut(self):
        game_row = {
            "sport": "NFL",
            "game_id": "PHI-CHI",
            "market": "team_total",
            "team": "CHI",
            "side": "over",
            "line": 19.5,
            "model_probability": 0.533,
            "book_american": -115,
            "ev_per_dollar": -0.004,
            "quote_timestamp": "2026-09-28T13:01:00Z",
        }
        card = build_nfl_research_card(game_market_rows=[game_row], **self.base)
        self.assertEqual(card["game_markets"]["research_edges"], [])
        reasons = set(card["game_markets"]["excluded"][0]["reasons"])
        self.assertIn("NON_POSITIVE_EV", reasons)
        self.assertIn("NO_BREAK_EVEN_EDGE", reasons)

    def test_changed_injury_or_role_fingerprint_blocks_entire_card(self):
        with self.assertRaisesRegex(NFLResearchCardError, "RECOMPUTE_OR_BLOCK"):
            build_nfl_research_card(
                forecast_provenance={
                    "input_fingerprint": "before-brown-goedert-status",
                    "generated_at": "2026-09-28T11:32:00Z",
                },
                current_input_fingerprint="after-brown-goedert-status",
                current_input_as_of="2026-09-28T12:50:00Z",
                as_of="2026-09-28T13:05:00Z",
            )

    def test_forecast_that_predates_current_input_snapshot_blocks(self):
        with self.assertRaisesRegex(NFLResearchCardError, "FORECAST_PREDATES_INPUTS"):
            build_nfl_research_card(
                forecast_provenance={
                    "input_fingerprint": "same-fingerprint",
                    "generated_at": "2026-09-28T12:00:00Z",
                },
                current_input_fingerprint="same-fingerprint",
                current_input_as_of="2026-09-28T12:30:00Z",
                as_of="2026-09-28T13:05:00Z",
            )

    def test_stale_price_is_cut_even_when_row_claims_fresh(self):
        payload = {
            "sport": "NFL",
            "results": [
                self.prop_row(quote_timestamp="2026-09-28T12:20:00Z", quote_fresh=True)
            ],
        }
        card = build_nfl_research_card(
            prop_run_payload=payload,
            roster_team_by_player_id={"swift": "CHI"},
            max_quote_age_seconds=900,
            **self.base,
        )
        self.assertEqual(card["props"]["research_edges"], [])
        self.assertIn("STALE_QUOTE", card["props"]["excluded"][0]["reasons"])

    def test_player_team_logo_mismatch_fails_closed(self):
        payload = {
            "sport": "NFL",
            "results": [self.prop_row(team="PHI")],
        }
        with self.assertRaisesRegex(NFLResearchCardError, "PLAYER_TEAM_BINDING_MISMATCH"):
            build_nfl_research_card(
                prop_run_payload=payload,
                roster_team_by_player_id={"swift": "CHI"},
                **self.base,
            )

    def test_unverified_player_team_does_not_get_display_logo_team(self):
        payload = {"sport": "NFL", "results": [self.prop_row()]}
        card = build_nfl_research_card(prop_run_payload=payload, **self.base)
        row = card["props"]["research_edges"][0]
        self.assertIsNone(row["display_team"])
        self.assertFalse(row["team_binding_verified"])

    def test_qualification_score_is_allowed_but_ev_score_is_not(self):
        payload = {
            "sport": "NFL",
            "results": [self.prop_row(qualification_score=86.0, score=100.0)],
        }
        card = build_nfl_research_card(
            prop_run_payload=payload,
            roster_team_by_player_id={"swift": "CHI"},
            **self.base,
        )
        row = card["props"]["research_edges"][0]
        self.assertEqual(row["score"], 86.0)
        self.assertFalse(card["governance"]["score_uses_ev"])
        self.assertFalse(card["governance"]["score_uses_edge"])

    def test_splits_cannot_be_mislabeled(self):
        with self.assertRaisesRegex(NFLResearchCardError, "SPLITS_SOURCE_MISMATCH"):
            build_nfl_research_card(
                splits_context={"source": "UnknownOtherSource", "tickets": 51},
                **self.base,
            )


if __name__ == "__main__":
    unittest.main()
