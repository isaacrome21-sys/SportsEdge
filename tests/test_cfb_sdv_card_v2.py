import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location(
    "cfb_sdv_card_v2",
    Path(__file__).resolve().parents[1] / "scripts" / "run_cfb_sdv_card_v2.py",
)
card = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(card)


class BlockedCardTest(unittest.TestCase):
    def test_floor_and_same_game_guard(self):
        rows = card.price_game("g", 25.0, 24.0, [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": 120},
            {"market": "MONEYLINE", "side": "AWAY", "american_odds": -140},
            {"market": "SPREAD", "side": "HOME", "line": 1.5, "american_odds": -110},
            {"market": "SPREAD", "side": "AWAY", "line": -1.5, "american_odds": -110},
        ], validated={"MONEYLINE", "SPREAD", "TOTAL"})
        bets = [r for r in rows if r["bet_status"] == "BET"]
        self.assertEqual(len(bets), 1)
        self.assertTrue(any(r["reason"] == "SAME_GAME_GUARD" for r in rows))

    def test_expected_roi_uses_actual_quote_not_devig_probability(self):
        rows = card.price_game("g", 28.0, 24.0, [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": -110},
            {"market": "MONEYLINE", "side": "AWAY", "american_odds": -110},
        ], validated={"MONEYLINE"})
        for row in rows:
            self.assertAlmostEqual(row["expected_roi"], round(row["model_p"] * (1 + 100 / 110) - 1, 4), delta=0.0002)

    def test_paired_devig_sums_to_one(self):
        rows = card.price_game("g", 28.0, 24.0, [
            {"market": "SPREAD", "side": "HOME", "line": -3.5, "american_odds": -110},
            {"market": "SPREAD", "side": "AWAY", "line": 3.5, "american_odds": -110},
        ])
        self.assertAlmostEqual(rows[0]["market_p"] + rows[1]["market_p"], 1.0, places=3)
        self.assertEqual(rows[0]["devig"], "PAIRED_PROPORTIONAL")
        self.assertAlmostEqual(rows[0]["model_p"] + rows[1]["model_p"], 1.0, places=3)

    def test_duplicate_same_side_quotes_cannot_create_fake_devig(self):
        rows = card.price_game("g", 32.0, 21.0, [
            {"market": "TOTAL", "side": "OVER", "line": 50.5, "american_odds": -110},
            {"market": "TOTAL", "side": "OVER", "line": 50.5, "american_odds": -115},
        ], validated={"TOTAL"})
        self.assertTrue(all(r["devig"] == "UNPAIRED_RAW_IMPLIED" for r in rows))
        self.assertTrue(all(r["bet_status"] == "TRACK" for r in rows))
        self.assertTrue(all(r["reason"] == "UNPAIRED_MARKET_NO_DEVIG" for r in rows))

    def test_unpaired_moneyline_cannot_emit_bet_or_lean(self):
        rows = card.price_game("g", 42.0, 14.0, [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": 150},
        ], validated={"MONEYLINE"})
        self.assertEqual(rows[0]["bet_status"], "TRACK")
        self.assertEqual(rows[0]["reason"], "UNPAIRED_MARKET_NO_DEVIG")

    def test_unpaired_spread_cannot_emit_bet_or_lean(self):
        rows = card.price_game("g", 34.0, 20.0, [
            {"market": "SPREAD", "side": "HOME", "line": -6.5, "american_odds": -110},
        ], validated={"SPREAD"})
        self.assertEqual(rows[0]["bet_status"], "TRACK")
        self.assertEqual(rows[0]["reason"], "UNPAIRED_MARKET_NO_DEVIG")

    def test_opposing_total_quotes_still_pair(self):
        rows = card.price_game("g", 28.0, 24.0, [
            {"market": "TOTAL", "side": "OVER", "line": 51.5, "american_odds": -110},
            {"market": "TOTAL", "side": "UNDER", "line": 51.5, "american_odds": -110},
        ])
        self.assertTrue(all(r["devig"] == "PAIRED_PROPORTIONAL" for r in rows))
        self.assertAlmostEqual(sum(r["market_p"] for r in rows), 1.0, places=3)

    def test_total_symmetry(self):
        rows = card.price_game("g", 30.0, 22.5, [
            {"market": "TOTAL", "side": "OVER", "line": 52.5, "american_odds": -110},
            {"market": "TOTAL", "side": "UNDER", "line": 52.5, "american_odds": -110},
        ])
        self.assertAlmostEqual(rows[0]["model_p"], 0.5, places=3)

    def test_compact_expand_and_resolve(self):
        from types import SimpleNamespace as G
        row = card.expand_compact({"away": "Mississippi", "home": "Alabama",
                                   "ml": [180, -218], "spread": [5.5, -112, -108], "total": [61.5, -105, -115]})
        self.assertEqual(len(row["quotes"]), 6)
        self.assertEqual(row["quotes"][3]["line"], -5.5)
        games = [G(game_id="1", away_team="Ole Miss", home_team="Alabama"),
                 G(game_id="2", away_team="Massachusetts", home_team="Ohio")]
        self.assertEqual(card.resolve_game(row, games).game_id, "1")
        self.assertEqual(card.resolve_game({"away": "UMass", "home": "Ohio"}, games).game_id, "2")

    def test_moment_match_and_sanity(self):
        snaps = {f"T{i}": {"prior": {k: float(i) for k in card.TEAM_KEYS},
                           "current": {k: float(i) * 2 for k in card.TEAM_KEYS}} for i in range(30)}
        moments = {k: (0.5, 0.1) for k in card.TEAM_KEYS}
        card.moment_match(snaps, moments)
        vals = [snaps[t]["current"]["explosive_rate"] for t in snaps]
        mu = sum(vals) / len(vals)
        self.assertAlmostEqual(mu, 0.5, places=6)
        self.assertLess(snaps["T0"]["current"]["explosive_rate"], snaps["T29"]["current"]["explosive_rate"])
        self.assertFalse(card.projection_sane(160.0, 150.0, []))
        self.assertTrue(card.projection_sane(30.0, 24.0, [{"market": "TOTAL", "line": 52.5}]))

    def test_edge_cap(self):
        rows = card.price_game("g", 45.0, 10.0, [
            {"market": "MONEYLINE", "side": "HOME", "american_odds": 200},
            {"market": "MONEYLINE", "side": "AWAY", "american_odds": -250}])
        self.assertEqual(rows[0]["reason"], "EDGE_TOO_LARGE_SUSPECT")
        self.assertEqual(rows[0]["bet_status"], "PASS")

    def test_paired_spread_anchor_uses_only_spread_market(self):
        quotes = [
            {"market": "SPREAD", "side": "AWAY", "line": -6.0, "american_odds": -110},
            {"market": "SPREAD", "side": "HOME", "line": 6.0, "american_odds": -110},
            {"market": "TOTAL", "side": "OVER", "line": 52.5, "american_odds": -110},
            {"market": "TOTAL", "side": "UNDER", "line": 52.5, "american_odds": -110},
        ]
        ctx = card.anchored_spread_context(30.0, 20.0, quotes)
        self.assertIsNotNone(ctx)
        self.assertAlmostEqual(ctx["market_home_margin"], -6.0)
        self.assertAlmostEqual(ctx["raw_model_home_margin"], 10.0)
        self.assertTrue(ctx["forward_track_eligible"])
        rows = card.price_game("g", 30.0, 20.0, quotes, spread_context=ctx)
        spread = [r for r in rows if r["market"] == "SPREAD"]
        totals = [r for r in rows if r["market"] == "TOTAL"]
        self.assertTrue(all(r["anchor_version"] == "CFB_MARKET_ANCHORED_SPREAD_V1" for r in spread))
        self.assertAlmostEqual(totals[0]["model_p"], card.model_prob("TOTAL", "OVER", 52.5, 30.0, 20.0), places=4)

    def test_incomplete_spread_pair_does_not_create_anchor(self):
        quotes = [{"market": "SPREAD", "side": "HOME", "line": -3.5, "american_odds": -110}]
        self.assertIsNone(card.anchored_spread_context(27.0, 24.0, quotes))

    def test_anchor_below_half_point_cannot_be_forward_lean(self):
        fit = {
            "intercept": 0.0,
            "weight": 0.01,
            "n": 6498,
        }
        quotes = [
            {"market": "SPREAD", "side": "HOME", "line": -3.0, "american_odds": 120},
            {"market": "SPREAD", "side": "AWAY", "line": 3.0, "american_odds": -140},
        ]
        ctx = card.anchored_spread_context(27.0, 23.0, quotes, fit=fit)
        self.assertFalse(ctx["forward_track_eligible"])
        rows = card.price_game("g", 27.0, 23.0, quotes, spread_context=ctx)
        self.assertFalse(any(r["bet_status"] == "LEAN" for r in rows if r["market"] == "SPREAD"))

    def test_unvalidated_edges_are_leans(self):
        quotes = [{"market": "MONEYLINE", "side": "HOME", "american_odds": 120},
                  {"market": "MONEYLINE", "side": "AWAY", "american_odds": -140},
                  {"market": "SPREAD", "side": "HOME", "line": 1.5, "american_odds": -110},
                  {"market": "SPREAD", "side": "AWAY", "line": -1.5, "american_odds": -110}]
        rows = card.price_game("g", 25.0, 24.0, quotes)
        self.assertFalse(any(r["bet_status"] == "BET" for r in rows))
        leans = [r for r in rows if r["bet_status"] == "LEAN"]
        self.assertEqual(len(leans), 1)
        self.assertEqual(leans[0]["reason"], "MODEL_EDGE_NOT_VALIDATED_VS_CLOSE")
        self.assertEqual(card.VALIDATED_MARKETS, frozenset())


class LiveWeekCacheTest(unittest.TestCase):
    def _game(self, *, weather=None):
        from sportsedge.sports.cfb.source import CFBGame
        return CFBGame(
            game_id="g1",
            season=2026,
            week=6,
            start_ts="2026-10-10T16:00:00Z",
            home_team="Home",
            away_team="Away",
            neutral_site=False,
            weather=weather,
        )

    def test_future_capture_is_rejected(self):
        game = self._game()
        payload = {
            "schema": "CFB_LIVE_WEEK_CACHE_V1",
            "season": 2026,
            "week": 6,
            "captured_at": "2026-10-06T15:01:00+00:00",
            "games": [game.__dict__],
            "snapshots": {"Home": {"prior": {}, "current": {}}},
        }
        got = card._load_live_week_cache(
            2026,
            6,
            datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc),
            load_cache=lambda: {"live_2026_w6": payload},
        )
        self.assertIsNone(got)

    def test_saved_bundle_is_market_blind(self):
        captured = {}
        def save(name, payload):
            captured["name"] = name
            captured["payload"] = payload
            return True

        ok = card._save_live_week_cache(
            2026,
            6,
            datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc),
            [self._game()],
            {"Home": {"prior": {"off_ppa_rush": 0.1}, "current": {"off_ppa_rush": 0.2}}},
            save_item=save,
        )
        self.assertTrue(ok)
        self.assertEqual(captured["name"], "live_2026_w6")
        encoded = __import__("json").dumps(captured["payload"], sort_keys=True).lower()
        self.assertNotIn("quote", encoded)
        self.assertNotIn("odds", encoded)
        self.assertNotIn("spread", encoded)
        self.assertNotIn("total", encoded)

    def test_build_rows_cache_hit_works_without_api_key(self):
        game = self._game(weather={"wind_speed": 9.0, "temperature": 60.0})
        snaps = {
            team: {"prior": {k: 0.0 for k in card.TEAM_KEYS},
                   "current": {k: 0.0 for k in card.TEAM_KEYS}}
            for team in ("Home", "Away")
        }
        board = [{"game_id": "g1", "quotes": []}]
        with patch.dict("os.environ", {}, clear=True), \
             patch.object(card, "_load_live_week_cache", return_value=([game], snaps)), \
             patch.object(card, "training_moments", return_value={k: (0.0, 1.0) for k in card.TEAM_KEYS}), \
             patch.object(card, "moment_match", return_value=[]), \
             patch("sportsedge.sports.cfb.source.fetch_cfbd_games", side_effect=AssertionError("no fetch")), \
             patch("sportsedge.sports.cfb.source.fetch_cfbd_weather", side_effect=AssertionError("no weather fetch")), \
             patch("sportsedge.sports.cfb.candidate_live_source.fetch_cfbd_candidate_metric_snapshots", side_effect=AssertionError("no metric fetch")), \
             patch("sportsedge.sports.cfb.candidate_live_source.attach_candidate_snapshots_to_game_row", side_effect=lambda base, **_: base):
            rows = card.build_rows(board, 2026, 6, "2026-10-06T15:00:00Z", fit_path="unused")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_id"], "g1")

    def test_build_rows_cache_hit_skips_cfbd_fetches(self):
        game = self._game(weather={"wind_speed": 17.0, "temperature": 55.0, "game_indoor": False})
        snaps = {
            "Home": {"prior": {k: 0.0 for k in card.TEAM_KEYS}, "current": {k: 0.0 for k in card.TEAM_KEYS}},
            "Away": {"prior": {k: 0.0 for k in card.TEAM_KEYS}, "current": {k: 0.0 for k in card.TEAM_KEYS}},
        }
        board = [{"game_id": "g1", "quotes": []}]

        with patch.dict("os.environ", {"CFBD_API_KEY": "test"}, clear=False), \
             patch.object(card, "_load_live_week_cache", return_value=([game], snaps)), \
             patch.object(card, "training_moments", return_value={k: (0.0, 1.0) for k in card.TEAM_KEYS}), \
             patch.object(card, "moment_match", return_value=[]), \
             patch("sportsedge.sports.cfb.source.fetch_cfbd_games", side_effect=AssertionError("games fetch must be skipped")), \
             patch("sportsedge.sports.cfb.source.fetch_cfbd_weather", side_effect=AssertionError("weather fetch must be skipped")), \
             patch("sportsedge.sports.cfb.candidate_live_source.fetch_cfbd_candidate_metric_snapshots", side_effect=AssertionError("metrics fetch must be skipped")), \
             patch("sportsedge.sports.cfb.source.attach_weather", side_effect=AssertionError("cached weather must be reused exactly")), \
             patch("sportsedge.sports.cfb.candidate_live_source.attach_candidate_snapshots_to_game_row", side_effect=lambda base, **_: base):
            rows = card.build_rows(board, 2026, 6, "2026-10-06T15:00:00Z", fit_path="unused")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_id"], "g1")
        self.assertEqual(rows[0]["weather"]["wind_speed"], 17.0)
        self.assertEqual(rows[0]["weather"]["temperature"], 55.0)



class MarketOnlyFallbackTest(unittest.TestCase):
    def test_market_implied_scores(self):
        row = card.expand_compact({"away": "Michigan", "home": "Minnesota",
                                   "spread": [-6, -110, -110], "total": [43.5, -105, -115]})
        home, away = card.market_implied_scores(row["quotes"])
        self.assertAlmostEqual(away - home, 6.0)
        self.assertAlmostEqual(home + away, 43.5)

    def test_market_only_rows_never_bet_or_lean(self):
        rows = card.market_only_rows([
            {"away": "Michigan", "home": "Minnesota", "ml": [-225, 185],
             "spread": [-6, -110, -110], "total": [43.5, -105, -115]},
            {"away": "A", "home": "B", "ml": [-150, 130]},
        ], "CFBD_RATE_LIMITED")
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(r["bet_status"] == "TRACK" and r["edge"] == 0.0 for r in rows))
        self.assertTrue(all(r["model_p"] == r["market_p"] for r in rows))
        self.assertEqual(rows[0]["matchup"], "Michigan @ Minnesota")


if __name__ == "__main__":
    unittest.main()
