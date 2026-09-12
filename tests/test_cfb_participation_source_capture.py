from __future__ import annotations

from datetime import datetime, timezone
import gzip
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb.participation_source_capture import (
    CFBParticipationSourceError,
    PARTICIPATION_CAPTURE_CONTRACT,
    PARTICIPATION_DATASETS,
    cache_participation_source,
    select_participation_asset,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class _Opener:
    def __init__(self, payloads):
        self.payloads = dict(payloads)

    def __call__(self, request, timeout=60):
        url = request.full_url
        if url not in self.payloads:
            raise RuntimeError(f"unexpected url:{url}")
        return _Response(self.payloads[url])


class CFBParticipationSourceCaptureTests(unittest.TestCase):
    def release(self, *, dataset="play_participants", raw=b"game_id,athlete_id\n1,2\n", gz=False):
        tag, prefix = PARTICIPATION_DATASETS[dataset]
        suffix = ".csv.gz" if gz else ".csv"
        body = gzip.compress(raw) if gz else raw
        name = f"{prefix}_2026{suffix}"
        url = f"https://github.com/sportsdataverse/sportsdataverse-data/releases/download/{tag}/{name}"
        return {
            "id": 101,
            "tag_name": tag,
            "draft": False,
            "prerelease": False,
            "updated_at": "2026-09-12T14:00:00Z",
            "assets": [{
                "id": 202,
                "name": name,
                "state": "uploaded",
                "size": len(body),
                "digest": "sha256:" + sha256(body).hexdigest(),
                "browser_download_url": url,
            }],
        }, body, url

    def test_dataset_allowlist_is_player_participation_only(self):
        self.assertEqual(set(PARTICIPATION_DATASETS), {
            "play_by_play", "play_participants", "player_box", "game_rosters"
        })
        with self.assertRaisesRegex(CFBParticipationSourceError, "DATASET_UNSUPPORTED"):
            select_participation_asset({}, dataset="betting", season=2026)

    def test_csv_gz_is_preferred_deterministically(self):
        plain_release, plain, plain_url = self.release(gz=False)
        gz_release, gz, gz_url = self.release(gz=True)
        payload = dict(plain_release)
        payload["assets"] = gz_release["assets"] + plain_release["assets"]
        asset = select_participation_asset(payload, dataset="play_participants", season=2026)
        self.assertTrue(asset.asset_name.endswith(".csv.gz"))
        self.assertEqual(asset.browser_download_url, gz_url)

    def test_cache_is_hash_bound_forward_only_and_non_authoritative(self):
        release, body, asset_url = self.release(gz=False)
        release_url = (
            "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/"
            "releases/tags/espn_cfb_play_participants"
        )
        opener = _Opener({
            release_url: json.dumps(release).encode("utf-8"),
            asset_url: body,
        })
        with tempfile.TemporaryDirectory() as td:
            row = cache_participation_source(
                dataset="play_participants",
                season=2026,
                cache_root=td,
                opener=opener,
                retrieved_at=datetime(2026, 9, 12, 14, 5, tzinfo=timezone.utc),
            )
            manifest = json.loads(Path(row["manifest_file"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["contract"], PARTICIPATION_CAPTURE_CONTRACT)
            self.assertFalse(manifest["market_data"])
            self.assertTrue(manifest["point_in_time_from_retrieval_forward"])
            self.assertFalse(manifest["retroactive_point_in_time_claim"])
            self.assertFalse(manifest["model_p_created"])
            self.assertFalse(manifest["promotion_authority"])
            self.assertEqual(manifest["content_sha256"], sha256(body).hexdigest())
            self.assertEqual(row["row_count"], 1)

    def test_wrong_asset_digest_cannot_be_selected(self):
        release, body, _ = self.release(gz=False)
        release["assets"][0]["digest"] = "not-a-sha"
        with self.assertRaisesRegex(CFBParticipationSourceError, "ASSET_SHA256_REQUIRED"):
            select_participation_asset(release, dataset="play_participants", season=2026)

    def test_release_tag_and_download_host_are_bound(self):
        release, _, _ = self.release(gz=False)
        release["tag_name"] = "wrong"
        with self.assertRaisesRegex(CFBParticipationSourceError, "RELEASE_TAG_MISMATCH"):
            select_participation_asset(release, dataset="play_participants", season=2026)

        release, _, _ = self.release(gz=False)
        release["assets"][0]["browser_download_url"] = "https://example.com/file.csv"
        with self.assertRaisesRegex(CFBParticipationSourceError, "ASSET_URL_INVALID"):
            select_participation_asset(release, dataset="play_participants", season=2026)


if __name__ == "__main__":
    unittest.main()
