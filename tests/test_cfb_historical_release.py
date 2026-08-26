from __future__ import annotations
import gzip
from hashlib import sha256
import unittest

from sportsedge.sports.cfb.historical_release import (
    CFBHistoricalReleaseError,
    assert_predictive_dataset,
    load_release_season,
    release_api_url,
    select_release_asset,
    cache_asset_to_file,
    iter_cached_csv,
)

def release(dataset="adv_team", season=2024, raw=b"team,epa\nA,0.1\n"):
    prefix = {
        "adv_team": "adv_team",
        "adv_situational": "adv_situational",
        "adv_drives": "adv_drives",
        "schedules": "cfb_schedule",
        "betting": "betting",
        "play_by_play": "play_by_play",
    }[dataset]
    tag = {
        "adv_team": "espn_cfb_adv_team",
        "adv_situational": "espn_cfb_adv_situational",
        "adv_drives": "espn_cfb_adv_drives",
        "schedules": "espn_cfb_schedules",
        "betting": "espn_cfb_betting",
        "play_by_play": "espn_cfb_pbp",
    }[dataset]
    name = f"{prefix}_{season}.csv.gz"
    packed = gzip.compress(raw)
    return {
        "id": 10,
        "tag_name": tag,
        "updated_at": "2026-08-03T03:00:54Z",
        "draft": False,
        "prerelease": False,
        "assets": [{
            "id": 11, "name": name, "size": len(packed), "state": "uploaded",
            "digest": "sha256:" + sha256(packed).hexdigest(),
            "browser_download_url": f"https://github.com/sportsdataverse/sportsdataverse-data/releases/download/{tag}/{name}",
        }],
    }, packed

class HistoricalReleaseTests(unittest.TestCase):
    def test_exact_asset_digest_and_rows_are_bound_into_manifest(self):
        payload, packed = release()
        out = load_release_season(
            dataset="adv_team", season=2024,
            release_fetcher=lambda url: payload,
            bytes_fetcher=lambda url: packed,
            retrieved_at="2026-08-26T13:45:00+00:00",
        )
        self.assertEqual(out.asset.dataset, "adv_team")
        self.assertEqual(out.asset.usage, "PREDICTIVE_INPUT")
        self.assertEqual(out.row_count, 1)
        self.assertEqual(out.rows[0]["team"], "A")
        self.assertEqual(out.content_sha256, sha256(packed).hexdigest())
        self.assertEqual(len(out.manifest_sha256), 64)

    def test_digest_mismatch_fails_closed(self):
        payload, packed = release()
        payload["assets"][0]["digest"] = "sha256:" + "0"*64
        with self.assertRaisesRegex(CFBHistoricalReleaseError, "SHA256_MISMATCH"):
            load_release_season(
                dataset="adv_team", season=2024,
                release_fetcher=lambda url: payload,
                bytes_fetcher=lambda url: packed,
                retrieved_at="2026-08-26T13:45:00+00:00",
            )

    def test_size_mismatch_fails_closed(self):
        payload, packed = release()
        payload["assets"][0]["size"] += 1
        with self.assertRaisesRegex(CFBHistoricalReleaseError, "SIZE_MISMATCH"):
            load_release_season(
                dataset="adv_team", season=2024,
                release_fetcher=lambda url: payload,
                bytes_fetcher=lambda url: packed,
                retrieved_at="2026-08-26T13:45:00+00:00",
            )

    def test_missing_digest_fails_closed(self):
        payload, _ = release()
        payload["assets"][0].pop("digest")
        with self.assertRaisesRegex(CFBHistoricalReleaseError, "SHA256_REQUIRED"):
            select_release_asset(payload, dataset="adv_team", season=2024)

    def test_wrong_release_tag_fails_closed(self):
        payload, _ = release()
        payload["tag_name"] = "espn_cfb_betting"
        with self.assertRaisesRegex(CFBHistoricalReleaseError, "TAG_MISMATCH"):
            select_release_asset(payload, dataset="adv_team", season=2024)

    def test_ambiguous_asset_fails_closed(self):
        payload, _ = release()
        payload["assets"].append(dict(payload["assets"][0], id=12))
        with self.assertRaisesRegex(CFBHistoricalReleaseError, "ASSET_AMBIGUOUS"):
            select_release_asset(payload, dataset="adv_team", season=2024)

    def test_betting_is_benchmark_only_and_cannot_enter_predictive_path(self):
        payload, _ = release(dataset="betting")
        asset = select_release_asset(payload, dataset="betting", season=2024)
        self.assertEqual(asset.usage, "BENCHMARK_ONLY")
        with self.assertRaisesRegex(CFBHistoricalReleaseError, "MARKET_DATA_PROHIBITED"):
            assert_predictive_dataset("betting")

    def test_predictive_surface_is_explicit(self):
        for name in ("adv_team","adv_situational","adv_drives","schedules"):
            self.assertEqual(assert_predictive_dataset(name), name)

    def test_release_url_is_exact(self):
        self.assertEqual(
            release_api_url("schedules"),
            "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/releases/tags/espn_cfb_schedules",
        )

    def test_play_by_play_requires_streaming_and_stream_cache_verifies_hash(self):
        import io
        import tempfile
        from pathlib import Path
        payload, packed = release(dataset="play_by_play", raw=b"game_id,week,pos_team,scoring_opp\n1,1,10,TRUE\n")
        asset = select_release_asset(payload, dataset="play_by_play", season=2024)

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close(); return False

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / asset.asset_name
            cached = cache_asset_to_file(asset, str(path), opener=lambda url: Response(packed), chunk_size=3)
            self.assertEqual(cached, str(path))
            rows = list(iter_cached_csv(asset, cached))
            self.assertEqual(rows[0]["pos_team"], "10")
        with self.assertRaisesRegex(CFBHistoricalReleaseError, "STREAMING_REQUIRED"):
            load_release_season(
                dataset="play_by_play", season=2024,
                release_fetcher=lambda url: payload,
                bytes_fetcher=lambda url: packed,
                retrieved_at="2026-08-26T13:45:00+00:00",
            )

    def test_failed_stream_download_never_exposes_partial_cache(self):
        import io
        import tempfile
        from pathlib import Path
        payload, packed = release(dataset="play_by_play")
        payload["assets"][0]["digest"] = "sha256:" + "0"*64
        asset = select_release_asset(payload, dataset="play_by_play", season=2024)

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *args): self.close(); return False

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / asset.asset_name
            with self.assertRaisesRegex(CFBHistoricalReleaseError, "SHA256_MISMATCH"):
                cache_asset_to_file(asset, str(path), opener=lambda url: Response(packed))
            self.assertFalse(path.exists())
            self.assertFalse(Path(str(path)+".part").exists())


if __name__ == "__main__":
    unittest.main()
