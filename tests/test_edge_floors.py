import unittest

from sportsedge.edge_floors import EdgeFloorError, require_frozen_edge_floor


def _cfg(record=None):
    floors = {} if record is None else {"MLB_MONEYLINE": record}
    return {
        "truth_gate": {
            "production": {
                "fail_closed": True,
                "allow_cli_floor_override": False,
                "require_frozen_floor_for_eligible_market": True,
            },
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
    def test_missing_market_fails_closed(self):
        with self.assertRaises(EdgeFloorError):
            require_frozen_edge_floor(market="MLB_MONEYLINE", config=_cfg())

    def test_unproven_market_fails_closed(self):
        with self.assertRaises(EdgeFloorError):
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

    def test_valid_frozen_floor_resolves_positive_value(self):
        floor = require_frozen_edge_floor(market="MLB_MONEYLINE", config=_cfg(_frozen("0.021")))
        self.assertEqual(str(floor.value_probability_points), "0.021")


if __name__ == "__main__":
    unittest.main()
