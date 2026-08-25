import unittest
from types import SimpleNamespace

from sportsedge.either_pitcher_settlement import (
    EitherPitcherSettlementError,
    parse_pair_entity_id,
    settle_either_pitcher,
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

    def test_over_is_or_across_both_pitchers(self):
        self.assertEqual(
            settle_either_pitcher(
                FACTS, market="EITHER_PITCHER_HITS_ALLOWED",
                entity_id="111|222", line=6.5, side="OVER",
            ),
            "WIN",
        )

    def test_under_is_or_across_both_pitchers(self):
        # One pitcher can make UNDER true even when the other is above the line;
        # this intentionally mirrors the active joint-engine proposition semantics.
        self.assertEqual(
            settle_either_pitcher(
                FACTS, market="EITHER_PITCHER_HITS_ALLOWED",
                entity_id="111|222", line=5.5, side="UNDER",
            ),
            "WIN",
        )

    def test_integer_line_push_when_neither_wins_and_one_equals(self):
        facts = {"pitchers": [
            {"player_id": "111", "hits_allowed": 6, "walks_allowed": 2, "earned_runs": 3},
            {"player_id": "222", "hits_allowed": 5, "walks_allowed": 5, "earned_runs": 1},
        ]}
        self.assertEqual(
            settle_either_pitcher(
                facts, market="EITHER_PITCHER_HITS_ALLOWED",
                entity_id="111|222", line=6, side="OVER",
            ),
            "PUSH",
        )

    def test_catalog_resolver_uses_interpreter(self):
        result, reason = _resolve_prediction(
            {
                "market": "EITHER_PITCHER_BB", "entity_id": "111|222",
                "line": 4.5, "side": "OVER",
            },
            FACTS,
        )
        self.assertEqual(result, "WIN")
        self.assertEqual(reason, "OFFICIAL_TWO_PITCHER_FACTS_AND_NORMALIZED_BOOK_RULES")

    def test_missing_pair_fact_fails_closed(self):
        with self.assertRaises(EitherPitcherSettlementError):
            settle_either_pitcher(
                {"pitchers": [FACTS["pitchers"][0]]},
                market="EITHER_PITCHER_BB", entity_id="111|222", line=2.5, side="OVER",
            )


if __name__ == "__main__":
    unittest.main()
