import unittest
from datetime import datetime, timezone

from sportsedge.live_slate import LiveGame, TeamLineup, make_live_game
from sportsedge.mlb_source import GameSnapshot
from sportsedge.unified_card import run_unified_card

UTC = timezone.utc
NOW = datetime(2026, 8, 12, 13, 0, tzinfo=UTC)


def rows(start, n=9):
    return [{"player_id": start + i, "slot": i + 1, "sequence": 0} for i in range(n)]


def game(*, away_pitcher=11, home_pitcher=22, away_rows=None, home_rows=None):
    snap = GameSnapshot(
        game_pk=777,
        game_date="2026-08-12T23:00:00Z",
        status="Preview",
        away_id=1,
        away_name="Away",
        home_id=2,
        home_name="Home",
        away_probable_pitcher_id=away_pitcher,
        away_probable_pitcher_name="Away SP" if away_pitcher else None,
        home_probable_pitcher_id=home_pitcher,
        home_probable_pitcher_name="Home SP" if home_pitcher else None,
        retrieved_at="2026-08-12T12:59:00+00:00",
    )
    return make_live_game(snap, away_rows if away_rows is not None else rows(100), home_rows if home_rows is not None else rows(200))


def projected_game():
    away = TeamLineup(1, "away", tuple(range(100, 109)), tuple(range(1, 10)), False)
    home = TeamLineup(2, "home", tuple(range(200, 209)), tuple(range(1, 10)), False)
    return LiveGame(
        game_pk=777,
        away_team_id=1,
        home_team_id=2,
        away_probable_pitcher_id=11,
        home_probable_pitcher_id=22,
        away_lineup=away,
        home_lineup=home,
        status="Preview",
    )


def quote(market):
    if market == "MONEYLINE":
        side, line, period = "HOME", None, "FG"
    elif market == "RUN_LINE":
        side, line, period = "HOME", -1.5, "FG"
    elif market == "TOTALS":
        side, line, period = "OVER", 8.5, "FG"
    elif market == "NRFI":
        side, line, period = "UNDER", 0.5, "1ST"
    else:
        side, line, period = "OVER", 0.5, "1ST"
    return {
        "game_id": "777",
        "period": period,
        "market": market,
        "entity_id": "",
        "line": line,
        "side": side,
        "book_key": "draftkings",
        "is_alternate": False,
        "raw_market_name": "fixture",
        "american_odds": -110,
        "retrieved_at": NOW,
        "ttl_seconds": 300,
    }


class GameContextGateTests(unittest.TestCase):
    def _run_card(self, live_game, markets, *, require_confirmed_lineup=False):
        return run_unified_card(
            games=[] if live_game is None else [live_game],
            feature_rows=[],
            quotes=[quote(m) for m in markets],
            ingestion_now=NOW,
            finalization_now=NOW,
            require_confirmed_lineup=require_confirmed_lineup,
        )

    def test_missing_probable_pitcher_blocks_every_game_market_before_model(self):
        markets = ["MONEYLINE", "RUN_LINE", "TOTALS", "NRFI", "YRFI"]
        out = self._run_card(game(home_pitcher=None), markets)
        self.assertEqual([x.market for x in out], markets)
        self.assertTrue(all(x.bet_status == "BLOCKED" for x in out))
        self.assertTrue(all(x.model_p is None for x in out))
        self.assertTrue(all(x.reason == "PROBABLE_PITCHER_UNRESOLVED" for x in out))

    def test_missing_live_game_context_blocks_before_model(self):
        out = self._run_card(None, ["MONEYLINE"])
        self.assertEqual(out[0].bet_status, "BLOCKED")
        self.assertIsNone(out[0].model_p)
        self.assertEqual(out[0].reason, "LIVE_GAME_CONTEXT_MISSING")

    def test_incomplete_lineup_blocks_even_when_projected_lineups_are_allowed(self):
        out = self._run_card(game(away_rows=rows(100, 8)), ["MONEYLINE"])
        self.assertEqual(out[0].bet_status, "BLOCKED")
        self.assertEqual(out[0].reason, "LINEUP_UNRESOLVED")

    def test_complete_projected_lineups_pass_context_gate_when_allowed(self):
        out = self._run_card(projected_game(), ["MONEYLINE"], require_confirmed_lineup=False)
        self.assertEqual(out[0].bet_status, "BLOCKED")
        self.assertEqual(out[0].reason, "GAME_RUNTIME_INPUTS_MISSING")

    def test_complete_projected_lineups_block_when_confirmation_is_required(self):
        out = self._run_card(projected_game(), ["MONEYLINE"], require_confirmed_lineup=True)
        self.assertEqual(out[0].bet_status, "BLOCKED")
        self.assertEqual(out[0].reason, "CONFIRMED_LINEUP_REQUIRED")

    def test_resolved_starters_and_lineups_reach_existing_runtime_gate(self):
        out = self._run_card(game(), ["MONEYLINE"])
        self.assertEqual(out[0].bet_status, "BLOCKED")
        self.assertEqual(out[0].reason, "GAME_RUNTIME_INPUTS_MISSING")


if __name__ == "__main__":
    unittest.main()
