import unittest

from sportsedge.core.clv.nfl_forward_capture import (
    NFL_FORWARD_SELECTION_CONTRACT,
    build_forward_close_rows,
    build_forward_decision_rows,
)
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID


class NFLForwardCaptureTests(unittest.TestCase):
    def _event(self, *, commence="2026-09-11T00:20:00Z", spread=-3.0, total=45.5):
        return {
            "id": "evt-1",
            "sport_key": "americanfootball_nfl",
            "commence_time": commence,
            "home_team": "Alpha Aces",
            "away_team": "Beta Bears",
            "bookmakers": [{
                "key": "draftkings",
                "markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Alpha Aces", "price": -120},
                        {"name": "Beta Bears", "price": 100},
                    ]},
                    {"key": "spreads", "outcomes": [
                        {"name": "Alpha Aces", "price": -110, "point": spread},
                        {"name": "Beta Bears", "price": -110, "point": -spread},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "price": -105, "point": total},
                        {"name": "Under", "price": -115, "point": total},
                    ]},
                ],
            }],
        }

    def _game(self):
        return {
            "game_id": "2026_01_BET_ALP",
            "game_start_ts": "2026-09-11T00:20:00+00:00",
            "home_team": "ALP",
            "away_team": "BET",
            "provider_home_team": "Alpha Aces",
            "provider_away_team": "Beta Bears",
        }

    def _identity(self):
        return {
            "code_git_sha": "1" * 40,
            "model_id": PRODUCTION_NFL_M2_MODEL_ID,
            "feature_contract": NFL_M2_FEATURE_CONTRACT,
            "model_artifact_sha256": "a" * 64,
        }

    def _distribution(self):
        # Home wins 4/5; covers -3 in 3/5; totals >45.5 in 3/5.
        return [
            {"home_score": 31, "away_score": 20, "margin": 11, "total": 51},
            {"home_score": 27, "away_score": 24, "margin": 3, "total": 51},
            {"home_score": 24, "away_score": 20, "margin": 4, "total": 44},
            {"home_score": 20, "away_score": 17, "margin": 3, "total": 37},
            {"home_score": 17, "away_score": 20, "margin": -3, "total": 37},
        ]

    def test_one_best_side_per_market_is_logged_as_shadow_evidence(self):
        rows = build_forward_decision_rows(
            self._game(), self._event(), self._distribution(),
            captured_at="2026-09-10T23:10:00+00:00", identity=self._identity(),
        )
        self.assertEqual({r["market"] for r in rows}, {"moneyline", "spread", "total"})
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["selection_contract"] == NFL_FORWARD_SELECTION_CONTRACT for r in rows))
        self.assertTrue(all(r["gate_result"] in {"SHADOW_QUALIFIED", "REJECTED_NO_POSITIVE_EV"} for r in rows))
        self.assertTrue(all(r["provider_event_id"] == "evt-1" for r in rows))
        self.assertTrue(all(r["model_artifact_sha256"] == "a" * 64 for r in rows))

    def test_provider_event_time_must_match_canonical_game_start(self):
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_EVENT_START_MISMATCH"):
            build_forward_decision_rows(
                self._game(), self._event(commence="2026-09-11T00:30:00Z"), self._distribution(),
                captured_at="2026-09-10T23:10:00+00:00", identity=self._identity(),
            )

    def test_decision_capture_must_be_pregame(self):
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_DECISION_NOT_PREGAME"):
            build_forward_decision_rows(
                self._game(), self._event(), self._distribution(),
                captured_at="2026-09-11T00:20:00+00:00", identity=self._identity(),
            )

    def test_close_must_be_after_decision_and_before_kickoff(self):
        decisions = build_forward_decision_rows(
            self._game(), self._event(), self._distribution(),
            captured_at="2026-09-10T23:10:00+00:00", identity=self._identity(),
        )
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_CLOSE_NOT_AFTER_DECISION"):
            build_forward_close_rows(decisions, self._event(), captured_at="2026-09-10T23:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_CLOSE_NOT_PREGAME"):
            build_forward_close_rows(decisions, self._event(), captured_at="2026-09-11T00:20:00+00:00")

    def test_moved_line_requires_original_threshold_quote(self):
        decisions = build_forward_decision_rows(
            self._game(), self._event(), self._distribution(),
            captured_at="2026-09-10T23:10:00+00:00", identity=self._identity(),
        )
        moved = self._event(spread=-3.5, total=46.0)
        with self.assertRaisesRegex(ValueError, "NFL_FORWARD_ORIGINAL_THRESHOLD_QUOTE_MISSING"):
            build_forward_close_rows(decisions, moved, captured_at="2026-09-11T00:10:00+00:00")

    def test_alternate_close_at_original_threshold_is_accepted(self):
        decisions = build_forward_decision_rows(
            self._game(), self._event(), self._distribution(),
            captured_at="2026-09-10T23:10:00+00:00", identity=self._identity(),
        )
        moved = self._event(spread=-3.5, total=46.0)
        moved["bookmakers"][0]["markets"].extend([
            {"key": "alternate_spreads", "outcomes": [
                {"name": "Alpha Aces", "price": -118, "point": -3.0},
                {"name": "Beta Bears", "price": 102, "point": 3.0},
            ]},
            {"key": "alternate_totals", "outcomes": [
                {"name": "Over", "price": -112, "point": 45.5},
                {"name": "Under", "price": -104, "point": 45.5},
            ]},
        ])
        closes = build_forward_close_rows(decisions, moved, captured_at="2026-09-11T00:10:00+00:00")
        self.assertEqual(len(closes), 3)
        for close, decision in zip(closes, decisions):
            self.assertEqual(close["game_start_ts"], decision["game_start_ts"])
            self.assertEqual(close["book"], decision["book"])
            self.assertEqual(close["probability_line"], decision["line_at_decision"])


if __name__ == "__main__":
    unittest.main()
