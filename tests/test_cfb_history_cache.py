from __future__ import annotations

from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb import history_cache as hc
from sportsedge.sports.cfb.historical_release import CFBHistoricalReleaseError


class FakeResponse(io.BytesIO):
    pass


class FakeOpener:
    def __init__(self, dataset="adv_team"):
        self.dataset = dataset
        self.raw = b"team,epa\nAlpha,0.1\n"
        self.asset_calls = 0
        self.meta_calls = 0

    def __call__(self, request, timeout=60):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "/releases/tags/" in url:
            self.meta_calls += 1
            tag = hc.release_api_url(self.dataset).rsplit("/", 1)[-1]
            prefix = {
                "schedules": "cfb_schedule",
                "adv_team": "adv_team",
                "adv_situational": "adv_situational",
                "adv_drives": "adv_drives",
                "play_by_play": "play_by_play",
                "betting": "betting",
            }[self.dataset]
            name = f"{prefix}_2024.csv"
            asset_url = (
                "https://github.com/sportsdataverse/sportsdataverse-data/"
                f"releases/download/{tag}/{name}"
            )
            payload = {
                "id": 10,
                "tag_name": tag,
                "updated_at": "2026-08-03T03:00:54Z",
                "draft": False,
                "prerelease": False,
                "assets": [{
                    "id": 11,
                    "name": name,
                    "size": len(self.raw),
                    "state": "uploaded",
                    "digest": "sha256:" + sha256(self.raw).hexdigest(),
                    "browser_download_url": asset_url,
                }],
            }
            return FakeResponse(json.dumps(payload).encode())
        if "/releases/download/" in url:
            self.asset_calls += 1
            return FakeResponse(self.raw)
        raise AssertionError(url)


class HistoryCacheTests(unittest.TestCase):
    def test_cache_verifies_writes_manifest_and_reuses_verified_file(self):
        opener = FakeOpener()
        with tempfile.TemporaryDirectory() as tmp:
            first = hc.cache_one(
                dataset="adv_team", season=2024, cache_root=tmp, opener=opener
            )
            self.assertEqual(first["row_count"], 1)
            self.assertFalse(first["cache_reused"])
            self.assertEqual(Path(first["cache_file"]).read_bytes(), opener.raw)
            manifest = json.loads(Path(first["manifest_file"]).read_text())
            self.assertEqual(manifest["content_sha256"], sha256(opener.raw).hexdigest())
            self.assertEqual(manifest["market_role"], "PREDICTIVE_INPUT")
            self.assertEqual(len(manifest["manifest_sha256"]), 64)
            self.assertEqual(opener.asset_calls, 1)

            second = hc.cache_one(
                dataset="adv_team", season=2024, cache_root=tmp, opener=opener
            )
            self.assertTrue(second["cache_reused"])
            self.assertEqual(opener.asset_calls, 1)
            self.assertEqual(opener.meta_calls, 2)

    def test_corrupted_cache_is_replaced_from_verified_asset(self):
        opener = FakeOpener()
        with tempfile.TemporaryDirectory() as tmp:
            first = hc.cache_one(
                dataset="adv_team", season=2024, cache_root=tmp, opener=opener
            )
            Path(first["cache_file"]).write_bytes(b"corrupt")
            second = hc.cache_one(
                dataset="adv_team", season=2024, cache_root=tmp, opener=opener
            )
            self.assertFalse(second["cache_reused"])
            self.assertEqual(Path(second["cache_file"]).read_bytes(), opener.raw)
            self.assertEqual(opener.asset_calls, 2)

    def test_betting_requires_explicit_benchmark_permission_before_network(self):
        opener = FakeOpener(dataset="betting")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(CFBHistoricalReleaseError, "MARKET_DATA_PROHIBITED"):
                hc.cache_one(
                    dataset="betting", season=2024, cache_root=tmp, opener=opener
                )
            self.assertEqual(opener.meta_calls, 0)
            out = hc.cache_one(
                dataset="betting",
                season=2024,
                cache_root=tmp,
                opener=opener,
                allow_benchmark=True,
            )
            self.assertEqual(out["usage"], "BENCHMARK_ONLY")

    def test_season_ranges_and_predictive_expansion_are_deterministic(self):
        self.assertEqual(
            hc.parse_season_spec(["2022:2024", "2024,2025"]),
            (2022, 2023, 2024, 2025),
        )
        names = hc.resolve_datasets(["predictive"])
        self.assertIn("play_by_play", names)
        self.assertNotIn("betting", names)


if __name__ == "__main__":
    unittest.main()
