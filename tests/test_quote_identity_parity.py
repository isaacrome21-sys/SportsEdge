import unittest
from datetime import datetime, timezone

from sportsedge.card_pipeline import run_hitter_card
from sportsedge.hits_engine import FEATURE_CONTRACT_VERSION as HITS_V
from sportsedge.live_slate import make_live_game
from sportsedge.mlb_source import GameSnapshot
from sportsedge.pitcher_card_pipeline import run_pitcher_bb_card
from sportsedge.total_bases_engine import FEATURE_CONTRACT_VERSION as TB_V
from sportsedge.unified_card import run_unified_card

UTC = timezone.utc
NOW = datetime(2026, 8, 10, 20, 0, tzinfo=UTC)


def rows(start):
    return [{"player_id": start + i, "slot": i + 1, "sequence": 0} for i in range(9)]


def game():
    snap = GameSnapshot(
        game_pk=777,
        game_date="2026-08-10T23:00:00Z",
        status="Preview",
        away_id=1,
        away_name="Away",
        home_id=2,
        home_name="Home",
        away_probable_pitcher_id=11,
        away_probable_pitcher_name="Away SP",
        home_probable_pitcher_id=22,
        home_probable_pitcher_name="Home SP",
        retrieved_at="2026-08-10T19:59:00+00:00",
    )
    return make_live_game(snap, rows(100), rows(200))


def features():
    return [
        {
            "game_pk": 777,
            "player_id": 100,
            "team_id": 1,
            "market": "HITS",
            "feature_version": HITS_V,
            "b_rate": 0.60,
            "p_rate": 0.60,
            "pa_pool": [4, 5, 4, 5],
        },
        {
            "game_pk": 777,
            "player_id": 100,
            "team_id": 1,
            "market": "TOTAL_BASES",
            "feature_version": TB_V,
            "rates": {"s": 0.20, "d": 0.08, "t": 0.01, "hr": 0.08},
            "p_h": 0.35,
            "p_hr": 0.06,
            "park": 1.2,
            "pa_pool": [4, 5, 4, 5],
        },
        {
            "game_pk": 777,
            "player_id": 11,
            "team_id": 1,
            "market": "PITCHER_BB",
            "feature_version": "pitcher_bb_features_v1",
            "own_bb": 20,
            "own_bfp": 220,
            "rolling_league_rate": 0.082,
            "pool": [22, 24, 25, 27],
            "league_pool": [20, 21, 23, 24, 25, 26, 27, 28],
        },
    ]


def quote(market, entity, line):
    raw_names = {
        "HITS": "Player Hits",
        "TOTAL_BASES": "Player Total Bases",
        "PITCHER_BB": "Pitcher Walks",
    }
    return {
        "game_id": "777",
        "period": "FG",
        "market": market,
        "entity_id": str(entity),
        "line": line,
        "side": "OVER",
        "book_key": "draftkings",
        "is_alternate": False,
        "raw_market_name": raw_names[market],
        "american_odds": 100,
        "retrieved_at": NOW,
        "ttl_seconds": 300,
    }


class CanonicalQuoteParityTests(unittest.TestCase):
    def assert_identity_block(self, standalone, unified):
        self.assertEqual(standalone[0].bet_status, "BLOCKED")
        self.assertEqual(unified[0].bet_status, "BLOCKED")
        self.assertIn("QUOTE_IDENTITY_INCOMPLETE", standalone[0].reason)
        self.assertIn("QUOTE_IDENTITY_INCOMPLETE", unified[0].reason)

    def test_hits_missing_identity_blocks_identically(self):
        q = quote("HITS", 100, 0.5)
        del q["book_key"]
        standalone = run_hitter_card(
            games=[game()], feature_rows=features(), quotes=[q],
            ingestion_now=NOW, finalization_now=NOW,
        )
        unified = run_unified_card(
            games=[game()], feature_rows=features(), quotes=[q],
            ingestion_now=NOW, finalization_now=NOW,
        )
        self.assert_identity_block(standalone, unified)

    def test_total_bases_missing_identity_blocks_identically(self):
        q = quote("TOTAL_BASES", 100, 0.5)
        del q["raw_market_name"]
        standalone = run_hitter_card(
            games=[game()], feature_rows=features(), quotes=[q],
            ingestion_now=NOW, finalization_now=NOW,
        )
        unified = run_unified_card(
            games=[game()], feature_rows=features(), quotes=[q],
            ingestion_now=NOW, finalization_now=NOW,
        )
        self.assert_identity_block(standalone, unified)

    def test_pitcher_bb_missing_identity_blocks_identically(self):
        q = quote("PITCHER_BB", 11, 1.5)
        del q["period"]
        standalone = run_pitcher_bb_card(
            games=[game()], feature_rows=features(), quotes=[q],
            ingestion_now=NOW, finalization_now=NOW,
        )
        unified = run_unified_card(
            games=[game()], feature_rows=features(), quotes=[q],
            ingestion_now=NOW, finalization_now=NOW,
        )
        self.assert_identity_block(standalone, unified)


if __name__ == "__main__":
    unittest.main()
