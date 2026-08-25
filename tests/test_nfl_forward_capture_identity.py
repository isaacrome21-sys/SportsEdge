import unittest

from sportsedge.core.clv.nfl_forward_capture import build_forward_close_rows, build_forward_decision_rows
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLForwardCaptureIdentityTests(unittest.TestCase):
    def _event(self):
        return {
            "id": "evt-1",
            "sport_key": "americanfootball_nfl",
            "commence_time": "2026-09-11T00:20:00Z",
            "home_team": "Alpha Aces",
            "away_team": "Beta Bears",
            "bookmakers": [{"key": "draftkings", "markets": [
                {"key": "h2h", "outcomes": [{"name": "Alpha Aces", "price": -120}, {"name": "Beta Bears", "price": 100}]},
                {"key": "spreads", "outcomes": [{"name": "Alpha Aces", "price": -110, "point": -3.0}, {"name": "Beta Bears", "price": -110, "point": 3.0}]},
                {"key": "totals", "outcomes": [{"name": "Over", "price": -110, "point": 45.5}, {"name": "Under", "price": -110, "point": 45.5}]},
            ]}],
        }

    def _decisions(self):
        game = {"game_id": "g1", "game_start_ts": "2026-09-11T00:20:00+00:00", "home_team": "ALP", "away_team": "BET", "provider_home_team": "Alpha Aces", "provider_away_team": "Beta Bears"}
        dist = [{"home_score": 27, "away_score": 20, "margin": 7, "total": 47}, {"home_score": 24, "away_score": 21, "margin": 3, "total": 45}]
        identity = {"code_git_sha": "1" * 40, "model_id": PRODUCTION_NFL_M2_MODEL_ID, "feature_contract": NFL_M2_FEATURE_CONTRACT, "model_artifact_sha256": "a" * 64}
        return build_forward_decision_rows(game, self._event(), dist, captured_at="2026-09-10T23:00:00+00:00", identity=identity)

    def test_close_rejects_swapped_provider_teams_even_if_event_id_and_time_match(self):
        decisions = self._decisions()
        swapped = self._event()
        swapped["home_team"], swapped["away_team"] = swapped["away_team"], swapped["home_team"]
        for market in swapped["bookmakers"][0]["markets"]:
            if market["key"] in {"h2h", "spreads"}:
                market["outcomes"].reverse()
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_PROVIDER_TEAM_MISMATCH"):
            build_forward_close_rows(decisions, swapped, captured_at="2026-09-11T00:10:00+00:00")


if __name__ == "__main__":
    unittest.main()
