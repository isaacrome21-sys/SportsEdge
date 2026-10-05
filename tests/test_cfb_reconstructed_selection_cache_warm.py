from __future__ import annotations

import inspect
import unittest

from scripts.warm_cfb_reconstructed_selection_cache import (
    CFBPartialCacheWarmError,
    _validate_preflight,
    main,
)


def _authority():
    return {
        "attempt_consumed": False,
        "evaluation_performed": False,
        "model_p": False,
        "truth_gate": False,
        "promotion": False,
        "eligibility": False,
        "staking": False,
        "official": False,
        "backfill": False,
    }


class TestCFBReconstructedSelectionCacheWarm(unittest.TestCase):
    def _preflight(self):
        return {
            "schema_version": "CFB_CFBD_PROVIDER_PREFLIGHT_V1",
            "status": "VERIFIED_PARTIAL_CACHE_WARM_ONLY",
            "historical_replay_calls_performed": 0,
            "planned_total_calls": 200,
            "verified_cache_hits": 0,
            "planned_new_calls": 200,
            "cache_warm_new_calls": 29,
            "retry_reserve_calls": 50,
            "remaining_quota": 79,
            "authority": _authority(),
        }

    def test_partial_warm_preflight_preserves_reserve(self):
        out = _validate_preflight(
            self._preflight(),
            total_calls=200,
            actual_cache_hits=0,
        )
        self.assertEqual(out["cache_warm_new_calls"], 29)
        self.assertGreaterEqual(
            out["remaining_quota"],
            out["cache_warm_new_calls"] + out["retry_reserve_calls"],
        )

    def test_partial_warm_rejects_cache_drift(self):
        with self.assertRaisesRegex(CFBPartialCacheWarmError, "PLAN_COUNT_MISMATCH"):
            _validate_preflight(
                self._preflight(),
                total_calls=200,
                actual_cache_hits=1,
            )

    def test_partial_warm_rejects_full_acquisition_status(self):
        bad = {**self._preflight(), "status": "VERIFIED_BEFORE_FIRST_REPLAY_CALL"}
        with self.assertRaisesRegex(CFBPartialCacheWarmError, "STATUS_INVALID"):
            _validate_preflight(
                bad,
                total_calls=200,
                actual_cache_hits=0,
            )

    def test_partial_warm_rejects_reserve_violation(self):
        bad = {**self._preflight(), "cache_warm_new_calls": 30}
        with self.assertRaisesRegex(CFBPartialCacheWarmError, "RESERVE_VIOLATION"):
            _validate_preflight(
                bad,
                total_calls=200,
                actual_cache_hits=0,
            )

    def test_network_warm_uses_single_attempt_per_request(self):
        source = inspect.getsource(main)
        self.assertIn("max_attempts=1", source)
        self.assertIn('"attempt_consumed": False', source)
        self.assertIn('"evaluation_performed": False', source)
        self.assertIn('"historical_pit_created": False', source)


if __name__ == "__main__":
    unittest.main()
