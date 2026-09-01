import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge.auto_native_odds import run_auto_mlb_native_odds


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)


class AutoNativeKeyringRotationTests(unittest.TestCase):
    @staticmethod
    def _report():
        return SimpleNamespace(
            slate_date_ct="2026-09-01",
            generated_at_utc=NOW.isoformat(),
            run_status="PASS",
            card_status="NO_BETS",
            results=(),
            coverage_slots=(),
            source_failures=(),
            market_surface_version="test",
        )

    def _run(self, *, partial_first_key=False):
        calls = []

        def source(surface):
            def fetch(**kwargs):
                key = kwargs["api_key"]
                calls.append((surface, key))
                if key == "dead":
                    quotes = ({"surface": surface},) if partial_first_key and surface == "PLAYER" else ()
                    return SimpleNamespace(
                        quotes=quotes,
                        failures=({"reason": f"ODDS_API_FETCH_FAILED:{surface}"},),
                    )
                return SimpleNamespace(quotes=({"surface": surface},), failures=())
            return fetch

        patches = (
            patch("sportsedge.auto_native_odds.fetch_schedule", return_value=[]),
            patch("sportsedge.auto_native_odds.build_participant_index", return_value={}),
            patch("sportsedge.auto_native_odds.fetch_mlb_player_prop_quotes", side_effect=source("PLAYER")),
            patch("sportsedge.auto_native_odds.fetch_mlb_game_quotes", side_effect=source("GAME")),
            patch("sportsedge.auto_native_odds.fetch_mlb_team_total_quotes", side_effect=source("TEAM_TOTAL")),
            patch("sportsedge.auto_native_odds.fetch_mlb_additional_quotes", side_effect=source("ADDITIONAL")),
            patch("sportsedge.auto_native_odds.run_auto_joint_mlb", return_value=self._report()),
        )
        entered = []
        try:
            for item in patches:
                entered.append(item)
                item.start()
            report = run_auto_mlb_native_odds(
                odds_api_key="dead",
                odds_api_keys=("good",),
                feature_url=None,
                now=NOW,
            )
        finally:
            for item in reversed(entered):
                item.stop()
        return calls, report

    def test_zero_quotes_with_provider_failures_rotates_to_next_key(self):
        calls, report = self._run()
        self.assertEqual(
            calls,
            [
                ("PLAYER", "dead"), ("GAME", "dead"),
                ("TEAM_TOTAL", "dead"), ("ADDITIONAL", "dead"),
                ("PLAYER", "good"), ("GAME", "good"),
                ("TEAM_TOTAL", "good"), ("ADDITIONAL", "good"),
            ],
        )
        failover = [row for row in report.source_failures if row.get("stage") == "ODDS_API_KEY_FAILOVER"]
        self.assertEqual(len(failover), 1)
        self.assertEqual(failover[0]["key_slot"], 1)
        self.assertIn("NATIVE_ODDS_EMPTY_WITH_PROVIDER_FETCH_FAILURES:count=4", failover[0]["reason"])
        self.assertNotIn("dead", str(failover))
        self.assertNotIn("good", str(failover))

    def test_any_usable_quote_keeps_current_key_even_with_degraded_surfaces(self):
        calls, report = self._run(partial_first_key=True)
        self.assertEqual(
            calls,
            [
                ("PLAYER", "dead"), ("GAME", "dead"),
                ("TEAM_TOTAL", "dead"), ("ADDITIONAL", "dead"),
            ],
        )
        self.assertFalse(any(row.get("stage") == "ODDS_API_KEY_FAILOVER" for row in report.source_failures))


if __name__ == "__main__":
    unittest.main()
