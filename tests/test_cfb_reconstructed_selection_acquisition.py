from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.acquire_cfb_reconstructed_selection import (
    CFBAcquisitionError,
    WEATHER_CONTRACT,
    _fetch_one,
    _hourly_index,
    _normalize_open_meteo_payload,
    _validate_private_preflight,
    _weather_hour_key,
    _weather_request,
    _venue_indexes,
    build_request_plan,
)


ROOT = Path(__file__).resolve().parents[1]


class TestCFBReconstructedSelectionAcquisition(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(
            (ROOT / "config/cfb_cfbd_reconstructed_selection_budget_v1.json").read_text()
        )

    def test_frozen_plan_has_exact_200_unique_cfbd_requests(self):
        plan = build_request_plan(self.config)
        self.assertEqual(len(plan), 200)
        self.assertEqual(len({row["query_sha256"] for row in plan}), 200)
        counts = {}
        for row in plan:
            counts[row["endpoint"]] = counts.get(row["endpoint"], 0) + 1
        self.assertEqual(counts["/games"], 12)
        self.assertEqual(counts["/teams/fbs"], 11)
        self.assertEqual(counts["/venues"], 1)
        self.assertEqual(counts["/stats/season/advanced"], 176)
        self.assertNotIn("/games/weather", counts)

    def test_advanced_plan_includes_2014_prior_and_stops_at_contract_week_16(self):
        plan = build_request_plan(self.config)
        advanced = [row for row in plan if row["endpoint"] == "/stats/season/advanced"]
        self.assertTrue(any(row["params"].get("year") == 2014 and "endWeek" not in row["params"] for row in advanced))
        self.assertTrue(any(row["params"].get("year") == 2025 and row["params"].get("endWeek") == 15 for row in advanced))
        self.assertFalse(any(int(row["params"].get("endWeek", 0)) > 15 for row in advanced))

    def test_preflight_must_be_verified_before_acquisition(self):
        with self.assertRaisesRegex(CFBAcquisitionError, "PREFLIGHT_NOT_VERIFIED"):
            _validate_private_preflight(
                {
                    "schema_version": "CFB_CFBD_PROVIDER_PREFLIGHT_V1",
                    "status": "BLOCKED_PROVIDER_PREFLIGHT",
                },
                200,
            )

    def test_preflight_requires_transport_zero_authority_and_sufficient_quota(self):
        base = {
            "schema_version": "CFB_CFBD_PROVIDER_PREFLIGHT_V1",
            "status": "VERIFIED_BEFORE_FIRST_REPLAY_CALL",
            "weather_transport_ready": True,
            "cfbd_weather_required_for_selection": False,
            "weather_source_contract": WEATHER_CONTRACT,
            "historical_replay_calls_performed": 0,
            "planned_new_calls": 200,
            "retry_reserve_calls": 50,
            "remaining_quota": 250,
            "authority": {"attempt_consumed": False, "model_p": False},
        }
        self.assertEqual(_validate_private_preflight(base, 200)["remaining_quota"], 250)
        with self.assertRaisesRegex(CFBAcquisitionError, "QUOTA_INSUFFICIENT"):
            _validate_private_preflight({**base, "remaining_quota": 249}, 200)
        with self.assertRaisesRegex(CFBAcquisitionError, "WEATHER_TRANSPORT_NOT_READY"):
            _validate_private_preflight({**base, "weather_transport_ready": False}, 200)
        with self.assertRaisesRegex(CFBAcquisitionError, "AUTHORITY_LEAK"):
            _validate_private_preflight({**base, "authority": {"attempt_consumed": True}}, 200)

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

    def test_acquisition_venue_index_accepts_provider_shapes_and_skips_unusable_rows(self):
        rows = [
            {"id": 1, "name": "Canonical", "dome": False, "latitude": 41.0, "longitude": -87.0},
            {"id": 2, "name": "Lng", "dome": False, "lat": 42.0, "lng": -88.0},
            {"id": 3, "name": "Lon", "dome": False, "lat": 43.0, "lon": -89.0},
            {"id": 4, "name": "Nested", "dome": True, "location": {"y": 44.0, "x": -90.0}},
            {"id": 5, "name": "Unusable", "dome": False},
        ]
        by_id, by_name = _venue_indexes(rows)
        self.assertEqual(set(by_id), {"1", "2", "3", "4"})
        self.assertEqual(by_id["2"]["longitude"], -88.0)
        self.assertEqual(by_id["3"]["longitude"], -89.0)
        self.assertEqual(by_id["4"]["latitude"], 44.0)
        self.assertNotIn("unusable", by_name)

    def test_open_meteo_request_is_hash_bound_to_frozen_contract(self):
        venues = [
            {"venue_id": "1", "latitude": 41.881832, "longitude": -87.623177},
            {"venue_id": "2", "latitude": 33.448376, "longitude": -112.074036},
        ]
        item = _weather_request(
            config=self.config,
            season=2020,
            venues=venues,
            start_date="2020-09-01",
            end_date="2020-09-30",
        )
        self.assertEqual(item["provider_contract"], WEATHER_CONTRACT)
        self.assertEqual(item["params"]["models"], "era5")
        self.assertEqual(item["params"]["timezone"], "GMT")
        self.assertEqual(item["params"]["hourly"], "temperature_2m,wind_speed_10m")
        self.assertEqual(item["venue_ids"], ["1", "2"])
        self.assertEqual(len(item["query_sha256"]), 64)

    def test_open_meteo_uses_exact_utc_hour_floor_without_interpolation(self):
        self.assertEqual(
            _weather_hour_key("2020-09-12T19:37:00-05:00"),
            "2020-09-13T00:00",
        )
        payload = {
            "hourly": {
                "time": ["2020-09-13T00:00", "2020-09-13T01:00"],
                "temperature_2m": [77.1, 76.4],
                "wind_speed_10m": [8.2, 7.5],
            }
        }
        self.assertEqual(_hourly_index(payload)["2020-09-13T00:00"], (77.1, 8.2))
        self.assertEqual(_normalize_open_meteo_payload(payload, 1), [payload])


if __name__ == "__main__":
    unittest.main()
