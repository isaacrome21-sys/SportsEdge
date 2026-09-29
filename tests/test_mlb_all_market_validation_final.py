import json
from datetime import date, datetime, timezone
from pathlib import Path
import unittest

from sportsedge.engine_registry import EngineDispatchError, engine_registry, resolve_manual_market_type
from sportsedge.manual_quote import ManualQuoteError, validate_manual_quote
from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.shared_game_engine import build_shared_game_engine_session
from sportsedge.v7_distribution import simulate_game_distribution


class FakeAllMarketSource(MLBAllMarketHistorySource):
    def __init__(self):
        super().__init__(retrieved_at=datetime(2026, 9, 28, 18, 0, tzinfo=timezone.utc))

    def hitter_joint_history(self, *, player_id, target_date):
        return [{
            "plate_appearances": 4, "hits": 1, "singles": 1, "doubles": 0,
            "triples": 0, "home_runs": 0, "total_bases": 1, "rbi": 1,
            "runs": 1, "stolen_bases": 1, "walks": 1, "strikeouts": 1,
            "extra_base_hits": 0,
        }] * 10

    def pitcher_joint_history(self, *, player_id, target_date):
        return [{"strikeouts": 6, "outs": 18, "earned_runs": 2, "hits_allowed": 5, "walks_allowed": 2}] * 5

    def team_means(self, *, away_team_id, home_team_id, target_date):
        return 4.2, 4.6, 2.1


class MLBAllMarketValidationFinalTests(unittest.TestCase):
    def test_catalog_has_38_markets_and_every_market_has_runtime_engine(self):
        catalog = json.loads(Path("config/mlb_market_catalog.json").read_text())
        markets = set()
        for key, values in catalog.items():
            if key != "schema_version":
                markets.update(values)
        self.assertEqual(len(markets), 38)
        self.assertTrue(markets.issubset(engine_registry().keys()), sorted(markets - engine_registry().keys()))

    def test_manual_aliases_cover_team_totals_and_first_inning_total(self):
        self.assertEqual(resolve_manual_market_type("TEAM_TOTAL"), "TEAM_TOTALS")
        self.assertEqual(resolve_manual_market_type("GAME_TEAM_TOTAL"), "TEAM_TOTALS")
        self.assertEqual(resolve_manual_market_type("FIRST_FIVE_TEAM_TOTAL"), "F5_TEAM_TOTALS")
        with self.assertRaises(EngineDispatchError):
            resolve_manual_market_type("FIRST_INNING_TOTAL")

    def test_first_inning_total_maps_to_yrfi_only_at_half_run(self):
        from sportsedge.canonical_manual_mlb import CanonicalManualMLBError, _engine_market
        from sportsedge.manual_quote import validate_manual_quote
        base = {
            "game_id": "1", "market_type": "FIRST_INNING_TOTAL", "side": "OVER", "line": 0.5,
            "price": -110, "paired_side": "UNDER", "paired_price": -110, "book": "draftkings",
            "observed_at": "2026-09-29T15:00:00+00:00", "first_pitch_at": "2026-09-29T23:00:00+00:00",
            "source": "MANUAL",
        }
        self.assertEqual(_engine_market(validate_manual_quote(base)), "YRFI")
        with self.assertRaises(CanonicalManualMLBError):
            _engine_market(validate_manual_quote({**base, "line": 1.5}))

    def test_manual_quote_carries_canonical_team_side(self):
        base = {
            "game_id": "1", "market_type": "TEAM_TOTAL", "side": "OVER", "line": 4.5,
            "price": -110, "paired_side": "UNDER", "paired_price": -110, "book": "draftkings",
            "observed_at": "2026-09-28T18:00:00Z", "first_pitch_at": "2026-09-28T19:00:00Z",
            "source": "MANUAL",
        }
        self.assertEqual(validate_manual_quote({**base, "team_side": "home"}).team_side, "HOME")
        with self.assertRaisesRegex(ManualQuoteError, "team_side must be HOME or AWAY"):
            validate_manual_quote({**base, "team_side": "middle"})

    def test_full_game_team_total_feature_binds_selected_team(self):
        row = FakeAllMarketSource().feature_row(
            game_pk=99, market="TEAM_TOTALS", entity_id="20", target_date=date(2026, 9, 28),
            away_team_id=10, home_team_id=20, team_id=20,
        )
        self.assertEqual(row["team_id"], 20)
        self.assertEqual(row["away_mean_runs"], 4.2)
        self.assertEqual(row["home_mean_runs"], 4.6)
        self.assertEqual(len(row["source_subset_hash"]), 64)

    def test_joint_hitter_combo_families_get_history_pool(self):
        source = FakeAllMarketSource()
        for market in ("HITS_RUNS_STOLEN_BASES", "HITS_STOLEN_BASES", "HITS_WALKS_STOLEN_BASES"):
            with self.subTest(market=market):
                row = source.feature_row(
                    game_pk=99, market=market, entity_id="123", target_date=date(2026, 9, 28),
                    away_team_id=10, home_team_id=20, player_id=123, team_id=10,
                )
                self.assertEqual(len(row["features"]["history_pool"]), 10)
                self.assertEqual(row["joint_feature_version"], "mlb_hitter_joint_history_v1")

    def test_either_pitcher_families_bind_probable_pair_and_both_histories(self):
        source = FakeAllMarketSource()
        for market in ("EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB", "EITHER_PITCHER_ER"):
            with self.subTest(market=market):
                row = source.feature_row(
                    game_pk=99, market=market, entity_id="111|222", target_date=date(2026, 9, 28),
                    away_team_id=10, home_team_id=20, away_pitcher_id=111, home_pitcher_id=222,
                )
                self.assertEqual(len(row["features"]["pitcher_a_history"]), 5)
                self.assertEqual(len(row["features"]["pitcher_b_history"]), 5)

    def test_team_total_integer_line_preserves_push_mass(self):
        engine = build_shared_game_engine_session(
            simulator=lambda *args, **kwargs: simulate_game_distribution(*args, **kwargs),
            _minimum_simulations_for_test=1000,
        )
        result = engine({
            "game_id": "99", "entity_id": "20", "away_mean_runs": 4.2, "home_mean_runs": 4.6,
            "feature_source_hash": "a" * 64, "simulations": 5000,
            "market": "TEAM_TOTALS", "team_side": "HOME", "line": 4.0, "side": "OVER",
        })
        self.assertGreater(result["push_p"], 0.0)
        self.assertLess(result["model_p"] + result["push_p"], 1.0)


if __name__ == "__main__":
    unittest.main()
