from datetime import datetime, timezone
import unittest
from unittest.mock import patch

from sportsedge.auto_native_odds import run_auto_mlb_native_odds
from sportsedge.auto_runner import AutoRunReport
from sportsedge.espn_game_odds_source import EspnGameOddsSnapshot
from sportsedge.mlb_source import GameSnapshot
from sportsedge.odds_keyring import OddsKeyringError

NOW = datetime(2026, 8, 12, 13, 0, tzinfo=timezone.utc)
GAME = GameSnapshot(
    777, "2026-08-12T17:40:00+00:00", "Preview",
    1, "Baltimore Orioles", 2, "Minnesota Twins",
    11, "Away Pitcher", 22, "Home Pitcher", NOW.isoformat(),
    official_date="2026-08-12",
)
QUOTE = {
    "game_id": "777", "period": "FG", "market": "MONEYLINE", "entity_id": "",
    "side": "HOME", "line": None, "book_key": "draftkings", "sportsbook": "DraftKings",
    "retrieved_at": NOW, "ttl_seconds": 60, "is_alternate": False,
    "raw_market_name": "espn_dk_moneyline", "american_odds": -105,
    "source_url": "ESPN_WEB_HEADER_DRAFTKINGS",
}


class AutoNativeOddsFallbackTests(unittest.TestCase):
    @patch("sportsedge.auto_native_odds.run_auto_mlb")
    @patch("sportsedge.auto_native_odds.build_live_game_feature_rows")
    @patch("sportsedge.auto_native_odds.build_native_projected_lineups")
    @patch("sportsedge.auto_native_odds.fetch_espn_draftkings_game_quotes")
    @patch("sportsedge.auto_native_odds.fetch_with_key_failover")
    @patch("sportsedge.auto_native_odds.fetch_boxscore")
    @patch("sportsedge.auto_native_odds.fetch_schedule")
    def test_keyring_exhaustion_uses_game_only_espn_fallback(
        self, schedule, boxscore, keyring, espn, projected, game_features, runner,
    ):
        schedule.return_value = [GAME]
        boxscore.return_value = {"teams": {"away": {"players": {}}, "home": {"players": {}}}}
        keyring.side_effect = OddsKeyringError("ODDS_API_ALL_KEYS_FAILED: slot=1:401; slot=2:401; slot=3:401; slot=4:401")
        espn.return_value = EspnGameOddsSnapshot((QUOTE,), ())
        projected.return_value = ([], [])
        game_features.return_value = ([], [])
        runner.return_value = AutoRunReport("2026-08-12", NOW.isoformat(), "NO_OFFICIAL_BETS", (), ())

        report = run_auto_mlb_native_odds(
            odds_api_key="k1", odds_api_keys=("k2", "k3", "k4"), now=NOW,
            game_score_artifact={}, nrfi_artifact={}, feature_url="https://features",
        )

        espn.assert_called_once()
        call = espn.call_args.kwargs
        self.assertEqual(call["slate_date"].isoformat(), "2026-08-12")
        self.assertEqual(call["schedule"], [GAME])
        self.assertEqual(call["retrieved_at"], NOW)
        self.assertTrue(any(x.get("stage") == "ODDS_API_KEYRING_EXHAUSTED" for x in report.source_failures))
        fallback_rows = [x for x in report.source_failures if x.get("stage") == "ESPN_DK_GAME_FALLBACK"]
        self.assertTrue(fallback_rows)
        self.assertEqual(fallback_rows[0]["markets"], ["MONEYLINE", "RUN_LINE", "TOTALS"])
        self.assertEqual(fallback_rows[0]["ttl_seconds"], 60)

        # Inspect what the downstream runner actually receives through the
        # in-memory canonical quote endpoint.
        wrapped = runner.call_args.kwargs["opener"]
        with wrapped("https://sportsedge.local/native-odds") as response:
            raw = response.read().decode("utf-8")
        self.assertIn('"market": "MONEYLINE"', raw)
        self.assertNotIn("NRFI", raw)
        self.assertNotIn("YRFI", raw)
        self.assertNotIn("HITS", raw)
        self.assertNotIn("TOTAL_BASES", raw)
        self.assertNotIn("PITCHER_BB", raw)

    @patch("sportsedge.auto_native_odds.build_native_projected_lineups")
    @patch("sportsedge.auto_native_odds.fetch_with_key_failover")
    @patch("sportsedge.auto_native_odds.fetch_boxscore")
    @patch("sportsedge.auto_native_odds.fetch_schedule")
    def test_without_game_artifacts_keyring_exhaustion_still_fails_closed(
        self, schedule, boxscore, keyring, projected,
    ):
        schedule.return_value = [GAME]
        boxscore.return_value = {"teams": {"away": {"players": {}}, "home": {"players": {}}}}
        keyring.side_effect = OddsKeyringError("ODDS_API_ALL_KEYS_FAILED")
        projected.return_value = ([], [])
        with self.assertRaisesRegex(OddsKeyringError, "ODDS_API_ALL_KEYS_FAILED"):
            run_auto_mlb_native_odds(odds_api_key="k1", now=NOW, feature_url="https://features")


if __name__ == "__main__":
    unittest.main()
