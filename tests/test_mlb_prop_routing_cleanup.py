import unittest

import sportsedge.auto_joint_runner as auto_joint_runner
import sportsedge.auto_runner as auto_runner
import sportsedge.canonical_manual_mlb as canonical_manual_mlb
import sportsedge.manual_hybrid_joint_runner as manual_hybrid_joint_runner
import sportsedge.manual_mlb_snapshot as manual_mlb_snapshot
import sportsedge.unified_card as unified_card
from sportsedge.engine_registry import EngineDispatchError, engine_registry
from sportsedge.generic_card_pipeline import run_generic_card


def _joint_hitter_row(hits=1):
    return {
        "plate_appearances": 4,
        "hits": hits,
        "singles": hits,
        "doubles": 0,
        "triples": 0,
        "home_runs": 0,
        "total_bases": hits,
        "rbi": 0,
        "runs": 0,
        "stolen_bases": 0,
        "walks": 0,
        "strikeouts": 0,
        "extra_base_hits": 0,
    }


class MLBPropRoutingCleanupTests(unittest.TestCase):
    def test_joint_hits_supports_alternate_line_legacy_contract_does_not(self):
        joint = engine_registry()["HITS"]({
            "game_id": "g", "market": "HITS", "entity_id": "b",
            "line": 3.5, "side": "OVER", "feature_source_hash": "a" * 64,
            "features": {"history_pool": [_joint_hitter_row(4) for _ in range(10)]},
        })
        self.assertEqual(joint["model_p"], 1.0)

        legacy = {
            "build_hash": "b" * 64, "game_id": "g", "market": "HITS",
            "entity_id": "b", "line": 3.5, "side": "OVER",
            "lineup_status": "CONFIRMED", "require_confirmed_lineup": False,
            "features": {"b_rate": 0.30, "p_rate": 0.27, "pa_pool": [3, 4, 4, 5]},
        }
        with self.assertRaisesRegex(EngineDispatchError, "LEGACY_LINE_UNSUPPORTED") as ctx:
            engine_registry()["HITS"](legacy)
        self.assertIn("canonical joint payload supports arbitrary", str(ctx.exception))

    def test_mixed_hitter_payload_fails_closed_before_engine_selection(self):
        mixed = {
            "build_hash": "b" * 64, "game_id": "g", "market": "HITS",
            "entity_id": "b", "line": 0.5, "side": "OVER",
            "lineup_status": "CONFIRMED", "require_confirmed_lineup": False,
            "features": {
                "history_pool": [_joint_hitter_row() for _ in range(10)],
                "b_rate": 0.30, "p_rate": 0.27, "pa_pool": [3, 4, 4, 5],
            },
        }
        with self.assertRaisesRegex(EngineDispatchError, "AMBIGUOUS_PROP_PAYLOAD"):
            engine_registry()["HITS"](mixed)

    def test_mixed_pitcher_bb_payload_fails_closed_before_engine_selection(self):
        mixed = {
            "build_hash": "c" * 64, "game_id": "g", "market": "PITCHER_BB",
            "entity_id": "p", "line": 1.5, "side": "OVER",
            "features": {
                "history_pool": [
                    {"strikeouts": 6, "outs": 18, "earned_runs": 2, "hits_allowed": 5, "walks_allowed": 2}
                    for _ in range(5)
                ],
                "own_bb": 20, "own_bfp": 220, "rolling_league_rate": 0.082,
                "pool": [22, 24, 25], "league_pool": [20, 21, 22, 23, 24],
            },
        }
        with self.assertRaisesRegex(EngineDispatchError, "AMBIGUOUS_PROP_PAYLOAD"):
            engine_registry()["PITCHER_BB"](mixed)

    def test_public_runners_have_explicit_canonical_pipeline_ownership(self):
        # Direct generic-card owners.
        self.assertIs(unified_card.run_generic_card, run_generic_card)
        self.assertIs(canonical_manual_mlb.run_generic_card, run_generic_card)
        self.assertIs(manual_mlb_snapshot.run_generic_card, run_generic_card)

        # Unified-card owners. These runners must not silently drift back to the
        # older hitter-only card pipeline during a registry migration.
        self.assertIs(auto_runner.run_unified_card, unified_card.run_unified_card)
        self.assertIs(auto_joint_runner.run_unified_card, unified_card.run_unified_card)
        self.assertIs(manual_hybrid_joint_runner.run_unified_card, unified_card.run_unified_card)


if __name__ == "__main__":
    unittest.main()
