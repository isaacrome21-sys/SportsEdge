from __future__ import annotations

import unittest

from sportsedge.core.manual_input_contract import (
    FeatureSchemaContract,
    ManualInputContractError,
    assert_manual_hybrid_feature_identity,
    validate_normalized_feature_payload,
)


class ManualInputContractTests(unittest.TestCase):
    def schema(self):
        return FeatureSchemaContract(
            schema_id="TEST_FEATURE_V1",
            required_fields=frozenset({"team_id", "adj_epa", "feature_asof_ts"}),
            optional_fields=frozenset({"weather"}),
        )

    def test_same_normalized_payload_has_manual_hybrid_parity(self):
        row = {"team_id": "A", "adj_epa": 0.12, "feature_asof_ts": "2026-08-29T10:00:00Z"}
        assert_manual_hybrid_feature_identity(row, dict(row), schema=self.schema())

    def test_market_field_in_manual_features_fails_closed(self):
        row = {
            "team_id": "A",
            "adj_epa": 0.12,
            "feature_asof_ts": "2026-08-29T10:00:00Z",
            "weather": {"wind": 8, "market_spread": -3.5},
        }
        with self.assertRaisesRegex(ManualInputContractError, "MARKET_DERIVED"):
            validate_normalized_feature_payload(row, schema=self.schema())

    def test_schema_extra_and_missing_fail_closed(self):
        with self.assertRaisesRegex(ManualInputContractError, "MISSING"):
            validate_normalized_feature_payload({"team_id": "A", "adj_epa": 0.12}, schema=self.schema())
        with self.assertRaisesRegex(ManualInputContractError, "EXTRA"):
            validate_normalized_feature_payload(
                {"team_id": "A", "adj_epa": 0.12, "feature_asof_ts": "x", "mystery": 1},
                schema=self.schema(),
            )

    def test_different_manual_and_hybrid_features_fail_identity(self):
        manual = {"team_id": "A", "adj_epa": 0.12, "feature_asof_ts": "2026-08-29T10:00:00Z"}
        hybrid = dict(manual, adj_epa=0.13)
        with self.assertRaisesRegex(ManualInputContractError, "IDENTITY_FAILED"):
            assert_manual_hybrid_feature_identity(manual, hybrid, schema=self.schema())


if __name__ == "__main__":
    unittest.main()
