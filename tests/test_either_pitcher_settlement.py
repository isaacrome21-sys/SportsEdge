import unittest
from types import SimpleNamespace

from sportsedge.either_pitcher_settlement import (
    EitherPitcherSettlementError,
    parse_pair_entity_id,
    settle_either_pitcher,
    settle_either_pitcher_engine_semantics,
)
from sportsedge.generic_card_pipeline import _bind_entity
from sportsedge.mlb_catalog_prediction_settlement import _resolve_prediction


FACTS = {
    "pitchers": [
        {"player_id": "111", "hits_allowed": 7, "walks_allowed": 2, "earned_runs": 3},
        {"player_id": "222", "hits_allowed": 4, "walks_allowed": 5, "earned_runs": 1},
    ]
}


class EitherPitcherSettlementTests(unittest.TestCase):
    def test_pair_identity_is_canonical_and_strict(self):
        self.assertEqual(parse_pair_entity_id("111|222"), ("111", "222"))
        for bad in ("111", "111|111", "abc|222", "111|222|333"):
            with self.subTest(bad=bad), self.assertRaises(EitherPitcherSettlementError):
                parse_pair_entity_id(bad)

    def test_card_boundary_requires_away_pipe_home_probable_pitchers(self):
        game = SimpleNamespace(away_probable_pitcher_id=111, home_probable_pitcher_id=222)
        _bind_entity(game, "EITHER_PITCHER_BB", "111|222", {})
        for bad in ("222|111", "111|333", "111"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _bind_entity(game, "EITHER_PITCHER_BB", bad, {})

    def test_engine_over_is_or_across_both_pitchers(self):
        self.assertEqual(
            settle_either_pitcher_engine_semantics(
                FACTS, market="EITHER_PITCHER_HITS_ALLOWED",
                entity_id="111|222", line=6.5, side="OVER",
            ),
            "WIN",
        )

    def test_engine_under_is_or_across_both_pitchers(self):
        self.assertEqual(
            settle_either_pitcher_engine_semantics(
                FACTS, market="EITHER_PITCHER_HITS_ALLOWED",
                entity_id="111|222", line=5.5, side="UNDER",
            ),
            "WIN",
        )

    def test_engine_or_semantics_are_not_a_normalized_two_sided_book_contract(self):
        # Cross-state: one pitcher above and one below the same line. The current
        # candidate engine marks BOTH independent OR events true, so these cannot
        # be treated as opposite sportsbook sides without a book-specific rule.
        over = settle_either_pitcher_engine_semantics(
            FACTS, market="EITHER_PITCHER_HITS_ALLOWED",
            entity_id="111|222", line=5.5, side="OVER",
        )
        under = settle_either_pitcher_engine_semantics(
            FACTS, market="EITHER_PITCHER_HITS_ALLOWED",
            entity_id="111|222", line=5.5, side="UNDER",
        )
        self.assertEqual((over, under), ("WIN", "WIN"))
        with self.assertRaisesRegex(EitherPitcherSettlementError, "BOOK_SPECIFIC_SEMANTICS_REQUIRED"):
            settle_either_pitcher(
                FACTS, market="EITHER_PITCHER_HITS_ALLOWED",
                entity_id="111|222", line=5.5, side="OVER",
            )

    def test_integer_line_push_under_engine_semantics_when_neither_over_wins(self):
        facts = {"pitchers": [
            {"player_id": "111", "hits_allowed": 6, "walks_allowed": 2, "earned_runs": 3},
            {"player_id": "222", "hits_allowed": 5, "walks_allowed": 5, "earned_runs": 1},
        ]}
        self.assertEqual(
            settle_either_pitcher_engine_semantics(
                facts, market="EITHER_PITCHER_HITS_ALLOWED",
                entity_id="111|222", line=6, side="OVER",
            ),
            "PUSH",
        )

    def test_catalog_resolver_fails_closed_until_book_semantics_are_normalized(self):
        result, reason = _resolve_prediction(
            {
                "market": "EITHER_PITCHER_BB", "entity_id": "111|222",
                "line": 4.5, "side": "OVER",
            },
            FACTS,
        )
        self.assertEqual(result, "UNRESOLVED")
        self.assertIn("EITHER_PITCHER_BOOK_SPECIFIC_SEMANTICS_REQUIRED", reason)

    def test_missing_pair_fact_still_fails_closed_in_engine_structural_helper(self):
        with self.assertRaises(EitherPitcherSettlementError):
            settle_either_pitcher_engine_semantics(
                {"pitchers": [FACTS["pitchers"][0]]},
                market="EITHER_PITCHER_BB", entity_id="111|222", line=2.5, side="OVER",
            )


if __name__ == "__main__":
    unittest.main()
