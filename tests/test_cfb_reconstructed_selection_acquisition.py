from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.acquire_cfb_reconstructed_selection import (
    CFBAcquisitionError,
    _fetch_one,
    _validate_private_preflight,
    build_request_plan,
)


ROOT = Path(__file__).resolve().parents[1]


class TestCFBReconstructedSelectionAcquisition(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(
            (ROOT / "config/cfb_cfbd_reconstructed_selection_budget_v1.json").read_text()
        )

    def test_frozen_plan_has_exact_254_unique_requests(self):
        plan = build_request_plan(self.config)
        self.assertEqual(len(plan), 254)
        self.assertEqual(len({row["query_sha256"] for row in plan}), 254)
        counts = {}
        for row in plan:
            counts[row["endpoint"]] = counts.get(row["endpoint"], 0) + 1
        self.assertEqual(counts["/games"], 12)
        self.assertEqual(counts["/teams/fbs"], 11)
        self.assertEqual(counts["/games/weather"], 11)
        self.assertEqual(counts["/stats/season/advanced"], 220)

    def test_advanced_plan_includes_2014_prior_and_2025_endweek19(self):
        plan = build_request_plan(self.config)
        advanced = [row for row in plan if row["endpoint"] == "/stats/season/advanced"]
        self.assertTrue(any(row["params"].get("year") == 2014 and "endWeek" not in row["params"] for row in advanced))
        self.assertTrue(any(row["params"].get("year") == 2025 and row["params"].get("endWeek") == 19 for row in advanced))

    def test_preflight_must_be_verified_before_acquisition(self):
        with self.assertRaisesRegex(CFBAcquisitionError, "PREFLIGHT_NOT_VERIFIED"):
            _validate_private_preflight(
                {
                    "schema_version": "CFB_CFBD_PROVIDER_PREFLIGHT_V1",
                    "status": "BLOCKED_PROVIDER_PREFLIGHT",
                },
                254,
            )

    def test_preflight_requires_zero_authority_and_sufficient_quota(self):
        base = {
            "schema_version": "CFB_CFBD_PROVIDER_PREFLIGHT_V1",
            "status": "VERIFIED_BEFORE_FIRST_REPLAY_CALL",
            "weather_entitled": True,
            "historical_replay_calls_performed": 0,
            "planned_new_calls": 254,
            "retry_reserve_calls": 50,
            "remaining_quota": 304,
            "authority": {"attempt_consumed": False, "model_p": False},
        }
        self.assertEqual(_validate_private_preflight(base, 254)["remaining_quota"], 304)
        with self.assertRaisesRegex(CFBAcquisitionError, "QUOTA_INSUFFICIENT"):
            _validate_private_preflight({**base, "remaining_quota": 303}, 254)
        with self.assertRaisesRegex(CFBAcquisitionError, "AUTHORITY_LEAK"):
            _validate_private_preflight({**base, "authority": {"attempt_consumed": True}}, 254)

    def test_verified_cache_reuse_does_not_open_network(self):
        item = build_request_plan(self.config)[0]
        body = b'[{"id":1}]'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            q = item["query_sha256"]
            import hashlib
            meta = {
                "endpoint": item["endpoint"],
                "season": item["params"]["year"],
                "end_week": None,
                "params": item["params"],
                "provider_contract": item["provider_contract"],
                "query_sha256": q,
                "response_sha256": hashlib.sha256(body).hexdigest(),
                "retrieved_at_utc": "2026-09-18T12:00:00+00:00",
            }
            (root / f"{q}.json").write_bytes(body)
            (root / f"{q}.meta.json").write_text(json.dumps(meta))

            def forbidden(*args, **kwargs):
                raise AssertionError("network opener must not be called for verified cache hit")

            payload, returned_meta, cached = _fetch_one(
                item,
                api_key="not-used-on-cache-hit",
                cache_root=root,
                opener=forbidden,
            )
            self.assertTrue(cached)
            self.assertEqual(payload, [{"id": 1}])
            self.assertEqual(returned_meta["query_sha256"], q)


if __name__ == "__main__":
    unittest.main()
