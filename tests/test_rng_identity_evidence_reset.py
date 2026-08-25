import json
import unittest
from pathlib import Path

from sportsedge.bb_engine import FEATURE_CONTRACT_VERSION as BB_V
from sportsedge.hits_engine import FEATURE_CONTRACT_VERSION as HITS_V
from sportsedge.live_slate import assemble_hitter_candidate, make_live_game
from sportsedge.mlb_source import GameSnapshot
from sportsedge.pitcher_live import assemble_pitcher_bb_candidate
from sportsedge.total_bases_engine import FEATURE_CONTRACT_VERSION as TB_V


RESET_MARKETS = ("HITS", "TOTAL_BASES", "PITCHER_BB")


def _rows(start):
    return [{"player_id": start + i, "slot": i + 1, "sequence": 0} for i in range(9)]


def _game():
    snap = GameSnapshot(
        game_pk=777,
        game_date="2026-08-25T23:00:00Z",
        status="Preview",
        away_id=1,
        away_name="Away",
        home_id=2,
        home_name="Home",
        away_probable_pitcher_id=11,
        away_probable_pitcher_name="Away SP",
        home_probable_pitcher_id=22,
        home_probable_pitcher_name="Home SP",
        retrieved_at="2026-08-25T19:00:00+00:00",
    )
    return make_live_game(snap, _rows(100), _rows(200))


def _hitter_feature(market):
    if market == "HITS":
        return {
            "game_pk": 777,
            "player_id": 100,
            "team_id": 1,
            "market": market,
            "feature_version": HITS_V,
            "b_rate": 0.31,
            "p_rate": 0.29,
            "pa_pool": [4, 5, 4, 5],
        }
    return {
        "game_pk": 777,
        "player_id": 100,
        "team_id": 1,
        "market": market,
        "feature_version": TB_V,
        "rates": {"s": 0.20, "d": 0.08, "t": 0.01, "hr": 0.08},
        "p_h": 0.35,
        "p_hr": 0.06,
        "park": 1.2,
        "pa_pool": [4, 5, 4, 5],
    }


def _pitcher_feature():
    return {
        "game_pk": 777,
        "player_id": 11,
        "team_id": 1,
        "market": "PITCHER_BB",
        "feature_version": BB_V,
        "own_bb": 20,
        "own_bfp": 220,
        "rolling_league_rate": 0.082,
        "pool": [22, 24, 25, 27],
        "league_pool": [20, 21, 23, 24, 25, 26, 27, 28],
    }


def _quote(market, entity, line, side):
    return {
        "game_id": "777",
        "market": market,
        "entity_id": str(entity),
        "line": line,
        "side": side,
    }


class QuoteSideRngIdentityTests(unittest.TestCase):
    def _hitter_hash(self, market, line, side):
        built = assemble_hitter_candidate(
            game=_game(),
            market=market,
            feature_row=_hitter_feature(market),
            quote=_quote(market, 100, line, side),
            require_confirmed_lineup=True,
        )
        return built["model_input"]["build_hash"]

    def _pitcher_hash(self, line, side):
        built = assemble_pitcher_bb_candidate(
            game=_game(),
            feature_row=_pitcher_feature(),
            quote=_quote("PITCHER_BB", 11, line, side),
        )
        return built["model_input"]["build_hash"]

    def test_hits_line_and_side_do_not_change_rng_identity(self):
        baseline = self._hitter_hash("HITS", 0.5, "OVER")
        self.assertEqual(baseline, self._hitter_hash("HITS", 0.5, "UNDER"))
        self.assertEqual(baseline, self._hitter_hash("HITS", 1.5, "OVER"))

    def test_total_bases_line_and_side_do_not_change_rng_identity(self):
        baseline = self._hitter_hash("TOTAL_BASES", 0.5, "OVER")
        self.assertEqual(baseline, self._hitter_hash("TOTAL_BASES", 0.5, "UNDER"))
        self.assertEqual(baseline, self._hitter_hash("TOTAL_BASES", 1.5, "OVER"))

    def test_pitcher_bb_line_and_side_do_not_change_rng_identity(self):
        baseline = self._pitcher_hash(1.5, "OVER")
        self.assertEqual(baseline, self._pitcher_hash(1.5, "UNDER"))
        self.assertEqual(baseline, self._pitcher_hash(2.5, "OVER"))

    def test_validation_evidence_is_explicitly_reset_to_zero(self):
        raw = json.loads(Path("config/mlb_validation_evidence.json").read_text())
        for market in RESET_MARKETS:
            row = raw["markets"][market]
            self.assertEqual(row["evidence_count"], 0)
            self.assertEqual(row["evidence_status"], "RESET")
            self.assertEqual(row["evidence_reset_reason"], "RNG_IDENTITY_QUOTE_SIDE_REMOVED")
            for gate in raw["required_gates"]:
                self.assertNotEqual(row.get(gate), "PASS")


if __name__ == "__main__":
    unittest.main()
