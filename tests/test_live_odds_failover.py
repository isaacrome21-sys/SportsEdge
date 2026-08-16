import unittest

from sportsedge.live_odds_failover import should_rotate_odds_key


class LiveOddsFailoverTests(unittest.TestCase):
    def test_all_event_fetch_failures_rotate(self):
        failures = [
            {"stage": "ODDS_API", "reason": "ODDS_API_FETCH_FAILED:event:a"},
            {"stage": "ODDS_API", "reason": "ODDS_API_FETCH_FAILED:event:b"},
        ]
        self.assertTrue(should_rotate_odds_key(run_status="NO_QUOTES", results=(), source_failures=failures))

    def test_model_or_identity_failure_does_not_rotate(self):
        failures = [{"stage": "ODDS_API", "reason": "ODDS_EVENT_GAME_AMBIGUOUS"}]
        self.assertFalse(should_rotate_odds_key(run_status="NO_QUOTES", results=(), source_failures=failures))

    def test_any_output_never_rotates(self):
        failures = [{"stage": "ODDS_API", "reason": "ODDS_API_FETCH_FAILED:event:a"}]
        self.assertFalse(should_rotate_odds_key(run_status="OK", results=({"x": 1},), source_failures=failures))

    def test_roster_diagnostics_can_coexist_with_provider_rotation(self):
        failures = [
            {"stage": "ODDS_API", "reason": "ODDS_API_FETCH_FAILED:event:a"},
            {"stage": "MLB_ROSTER_IDENTITY", "reason": "temporary roster issue"},
        ]
        self.assertTrue(should_rotate_odds_key(run_status="NO_QUOTES", results=(), source_failures=failures))


if __name__ == "__main__":
    unittest.main()
