from __future__ import annotations

import unittest

from sportsedge.core.promotion_record import (
    MarketPromotionRecord,
    PromotionRecordError,
    assert_no_certification_inheritance,
)


HEX = "a" * 64


def record(market_family="SPREAD"):
    return MarketPromotionRecord(
        sport="CFB",
        market_family=market_family,
        status="OFFICIAL",
        truth_gate_policy_id="CFB_TRUTH_GATE_V1",
        policy_bundle_sha=HEX,
        evidence_bundle_sha=HEX,
        model_bundle_sha=HEX,
        effective_at="2026-09-01T00:00:00Z",
    )


class PromotionRecordTests(unittest.TestCase):
    def test_same_market_record_is_valid(self):
        value = record()
        value.validate()
        assert_no_certification_inheritance(value, "SPREAD")
        self.assertEqual(len(value.content_hash()), 64)

    def test_cfb_spread_cannot_promote_prop(self):
        with self.assertRaisesRegex(PromotionRecordError, "CERTIFICATION_INHERITANCE_FORBIDDEN"):
            assert_no_certification_inheritance(record("SPREAD"), "PLAYER_PASS_YARDS")

    def test_mlb_game_family_cannot_promote_pitcher_joint(self):
        value = MarketPromotionRecord(
            sport="MLB",
            market_family="V7_GAME",
            status="OFFICIAL",
            truth_gate_policy_id="MLB_TRUTH_GATE_V1",
            policy_bundle_sha=HEX,
            evidence_bundle_sha=HEX,
            model_bundle_sha=HEX,
            effective_at="2026-09-01T00:00:00Z",
        )
        with self.assertRaisesRegex(PromotionRecordError, "CERTIFICATION_INHERITANCE_FORBIDDEN"):
            assert_no_certification_inheritance(value, "PITCHER_JOINT")


if __name__ == "__main__":
    unittest.main()
