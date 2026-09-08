import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sportsedge.auto_native_odds import MEMORY_QUOTES_URL, run_auto_mlb_native_odds
from sportsedge.auto_runner import AutoRunReport
from sportsedge.mlb_source import GameSnapshot


NOW = datetime(2026, 8, 11, 15, 0, tzinfo=timezone.utc)


class AutoNativeAdditionalOddsTests(unittest.TestCase):
    def _game(self):
        return GameSnapshot(
            game_pk=777,
            game_date="2026-08-11T23:00:00Z",
            status="Preview",
            away_id=1,
            away_name="Chicago Cubs",
            home_id=2,
            home_name="New York Yankees",
            away_probable_pitcher_id=11,
            away_probable_pitcher_name="Away Pitcher",
            home_probable_pitcher_id=22,
            home_probable_pitcher_name="Home Pitcher",
            retrieved_at="2026-08-11T14:58:00Z",
            official_date="2026-08-11",
        )

    def _quote(self, market, entity_id, side, line=0.0, period="FG"):
        return {
            "game_id": "777",
            "period": period,
            "market": market,
            "entity_id": str(entity_id),
            "side": side,
            "line": line,
            "book_key": "draftkings",
            "sportsbook": "DraftKings",
            "retrieved_at": "2026-08-11T14:59:00+00:00",
            "is_alternate": False,
            "raw_market_name": market.lower(),
            "american_odds": -110,
            "ttl_seconds": 300,
        }

    def test_native_auto_includes_additional_surface_in_memory_payload_and_labels_failures(self):
        captured = {}
        player = SimpleNamespace(
            quotes=(self._quote("HITS", 100, "OVER", 0.5),),
            failures=(),
        )
        game = SimpleNamespace(
            quotes=(self._quote("MONEYLINE", 1, "AWAY"),),
            failures=(),
        )
        additional = SimpleNamespace(
            quotes=(self._quote("NRFI", 777, "YES", period="1ST"),),
            failures=({"reason": "synthetic additional source failure"},),
        )

        def fake_runner(**kwargs):
            with kwargs["opener"](MEMORY_QUOTES_URL) as response:
                captured["quotes"] = json.loads(response.read().decode("utf-8"))
            return AutoRunReport(
                slate_date_ct="2026-08-11",
                generated_at_utc=NOW.isoformat(),
                run_status="NO_QUOTES",
                card_status="NO_BETS",
                results=(),
                coverage_slots=(),
                source_failures=(),
                market_surface_version="test-surface-v1",
            )

        shared_snapshot = SimpleNamespace(events=(), provenance_fields=lambda: {}, event_by_id=lambda event_id: None)

        with patch("sportsedge.auto_native_odds.fetch_schedule", return_value=[self._game()]), patch(
            "sportsedge.auto_native_odds.fetch_boxscore", return_value={"teams": {"away": {"players": {}}, "home": {"players": {}}}}
        ), patch(
            "sportsedge.auto_native_odds.acquire_mlb_event_snapshot", return_value=shared_snapshot
        ) as snapshot_fetch, patch(
            "sportsedge.auto_native_odds.fetch_mlb_player_prop_quotes", return_value=player
        ) as player_fetch, patch(
            "sportsedge.auto_native_odds.fetch_mlb_game_quotes", return_value=game
        ) as game_fetch, patch(
            "sportsedge.auto_native_odds.fetch_mlb_team_total_quotes",
            return_value=SimpleNamespace(quotes=(), failures=()),
        ) as team_total_fetch, patch(
            "sportsedge.auto_native_odds.fetch_mlb_additional_quotes", return_value=additional
        ) as additional_fetch, patch(
            "sportsedge.auto_native_odds.run_auto_joint_mlb", side_effect=fake_runner
        ):
            report = run_auto_mlb_native_odds(
                odds_api_key="secret",
                feature_url=None,
                now=NOW,
                opener=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unexpected network")),
            )

        self.assertEqual(
            {q["market"] for q in captured["quotes"]},
            {"HITS", "MONEYLINE", "NRFI"},
        )
        snapshot_fetch.assert_called_once()
        player_fetch.assert_called_once()
        game_fetch.assert_called_once()
        team_total_fetch.assert_called_once()
        additional_fetch.assert_called_once()
        self.assertTrue(
            any(
                row.get("surface") == "ADDITIONAL"
                and "synthetic additional source failure" in row.get("reason", "")
                for row in report.source_failures
            )
        )


if __name__ == "__main__":
    unittest.main()
