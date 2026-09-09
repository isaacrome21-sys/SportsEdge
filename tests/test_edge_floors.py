import unittest

from sportsedge.edge_floors import (
    EdgeFloorError,
    require_frozen_devig_policy,
    require_frozen_edge_floor,
)


def _devig_policy():
    return {
        "policy_id": "EDGE_FLOOR_DEVIG_V1",
        "status": "FROZEN_PRE_DERIVATION",
        "longshot_trigger_american_odds": 400,
        "longshot_trigger_rule": "EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400",
        "sensitivity_methods": ["MULTIPLICATIVE_V1", "POWER_V1", "SHIN_V1"],
        "sensitivity_limit_absolute_probability_points": 0.01,
        "stable_candidate_estimator": "MULTIPLICATIVE_V1",
        "longshot_candidate_estimator": "POWER_V1",
        "haircut_probability_points": 0.0,
        "aggregation_rule": "ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS",
        "sensitivity_failure": "BLOCK",
    }


def _cfg(record=None):
    floors = {} if record is None else {"MLB_MONEYLINE": record}
    return {
        "truth_gate": {
            "schema_version": 2,
            "production": {
                "fail_closed": True,
                "allow_cli_floor_override": False,
                "require_frozen_floor_for_eligible_market": True,
            },
            "devig_policy": _devig_policy(),
            "edge_floors": floors,
        }
    }


def _frozen(value="0.02"):
    return {
        "status": "FROZEN",
        "value_probability_points": value,
        "method_version": "oos_edge_floor_v1",
        "evidence": {
            "evidence_sha256": "e" * 64,
            "derivation_code_sha256": "d" * 64,
            "oos_cutoff_utc": "2026-08-01T00:00:00Z",
        },
        "frozen": {"frozen_by_commit": "a" * 40},
    }


class EdgeFloorTests(unittest.TestCase):
    def test_missing_market_fails_closed_with_specific_code(self):
        with self.assertRaisesRegex(
            EdgeFloorError,
            "^ELIGIBLE_MARKET_MISSING_OR_UNFROZEN_EDGE_FLOOR:MLB_MONEYLINE$",
        ):
            require_frozen_edge_floor(market="MLB_MONEYLINE", config=_cfg())

    def test_unproven_market_fails_closed_with_specific_code(self):
        with self.assertRaisesRegex(
            EdgeFloorError,
            "^ELIGIBLE_MARKET_MISSING_OR_UNFROZEN_EDGE_FLOOR:MLB_MONEYLINE$",
        ):
            require_frozen_edge_floor(
                market="MLB_MONEYLINE",
                config=_cfg({"status": "UNPROVEN", "value_probability_points": None}),
            )

    def test_nonpositive_or_invalid_floor_is_rejected(self):
        for value in (0, 0.0, "0", -0.01, "-0.02", None, "nan", "inf"):
            with self.subTest(value=value):
                with self.assertRaises(EdgeFloorError):
                    require_frozen_edge_floor(market="MLB_MONEYLINE", config=_cfg(_frozen(value)))

    def test_frozen_floor_requires_evidence_hashes_and_cutoff(self):
        record = _frozen()
        del record["evidence"]["evidence_sha256"]
        with self.assertRaises(EdgeFloorError):
            require_frozen_edge_floor(market="MLB_MONEYLINE", config=_cfg(record))

    def test_production_policy_must_be_fail_closed_and_override_disabled(self):
        cfg = _cfg(_frozen())
        cfg["truth_gate"]["production"]["fail_closed"] = False
        with self.assertRaises(EdgeFloorError):
            require_frozen_edge_floor(market="MLB_MONEYLINE", config=cfg)

        cfg = _cfg(_frozen())
        cfg["truth_gate"]["production"]["allow_cli_floor_override"] = True
        with self.assertRaises(EdgeFloorError):
            require_frozen_edge_floor(market="MLB_MONEYLINE", config=cfg)

    def test_frozen_requirement_cannot_be_disabled_or_omitted(self):
        for value in (None, False, 0, 1, "true"):
            with self.subTest(value=value):
                cfg = _cfg(_frozen())
                policy = cfg["truth_gate"]["production"]
                if value is None:
                    del policy["require_frozen_floor_for_eligible_market"]
                else:
                    policy["require_frozen_floor_for_eligible_market"] = value
                with self.assertRaisesRegex(EdgeFloorError, "^FROZEN_FLOOR_POLICY_REQUIRED$"):
                    require_frozen_edge_floor(market="MLB_MONEYLINE", config=cfg)

    def test_valid_frozen_floor_resolves_positive_value(self):
        floor = require_frozen_edge_floor(market="MLB_MONEYLINE", config=_cfg(_frozen("0.021")))
        self.assertEqual(str(floor.value_probability_points), "0.021")

    def test_devig_policy_freezes_requested_values(self):
        policy = require_frozen_devig_policy(config=_cfg())
        self.assertEqual(policy.longshot_trigger_american_odds, 400)
        self.assertEqual(str(policy.sensitivity_limit_absolute_probability_points), "0.01")
        self.assertEqual(policy.stable_candidate_estimator, "MULTIPLICATIVE_V1")
        self.assertEqual(policy.longshot_candidate_estimator, "POWER_V1")
        self.assertEqual(str(policy.haircut_probability_points), "0.0")
        self.assertEqual(policy.aggregation_rule, "ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS")

    def test_devig_policy_rejects_minimum_across_methods_rule(self):
        cfg = _cfg()
        cfg["truth_gate"]["devig_policy"]["aggregation_rule"] = "MINIMUM_ACROSS_METHODS"
        with self.assertRaisesRegex(EdgeFloorError, "^DEVIG_AGGREGATION_RULE_INVALID$"):
            require_frozen_devig_policy(config=cfg)

    def test_devig_policy_requires_schema_v2(self):
        cfg = _cfg()
        cfg["truth_gate"]["schema_version"] = 1
        with self.assertRaisesRegex(EdgeFloorError, "^EDGE_FLOOR_SCHEMA_VERSION_MISMATCH$"):
            require_frozen_devig_policy(config=cfg)


if __name__ == "__main__":
    unittest.main()
