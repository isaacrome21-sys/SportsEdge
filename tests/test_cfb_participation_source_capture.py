from __future__ import annotations

import csv
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
    PBP_PREDICTIVE_COLUMNS,
    PBP_PROJECTION_CONTRACT,
    PBP_SOURCE_TO_CANONICAL,
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

    def pbp_bytes(self, *, spread="-21.5", total="55.5") -> bytes:
        fields = list(PBP_SOURCE_TO_CANONICAL) + [
            "gameSpread", "homeFavorite", "gameSpreadAvailable", "overUnder",
            "homeTeamSpread", "start.pos_team_spread", "start.spread_time",
        ]
        values = {
            "game_id": "401000001",
            "season": "2026",
            "week": "2",
            "id": "401000001100001001",
            "game_play_number": "1",
            "sequenceNumber": "10001001",
            "period.number": "4",
            "clock.minutes": "8",
            "clock.seconds": "12",
            "start.pos_team.id": "11",
            "homeTeamId": "11",
            "awayTeamId": "22",
            "start.homeScore": "35",
            "start.awayScore": "10",
            "start.yardsToEndzone": "42",
            "type.text": "Pass Reception",
            "orig_play_type": "Pass Reception",
            "status_type_completed": "TRUE",
            "gameSpread": spread,
            "homeFavorite": "TRUE",
            "gameSpreadAvailable": "TRUE",
            "overUnder": total,
            "homeTeamSpread": spread,
            "start.pos_team_spread": spread,
            "start.spread_time": "-8.6",
        }
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerow(values)
        return stream.getvalue().encode("utf-8")

    def cache_with_body(self, *, dataset: str, body: bytes, root: str):
        release, raw, asset_url = self.release(dataset=dataset, raw=body, gz=False)
        tag, _ = PARTICIPATION_DATASETS[dataset]
        release_url = (
            "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/"
            f"releases/tags/{tag}"
        )
        opener = _Opener({
            release_url: json.dumps(release).encode("utf-8"),
            asset_url: raw,
        })
        return cache_participation_source(
            dataset=dataset,
            season=2026,
            cache_root=root,
            opener=opener,
            retrieved_at=datetime(2026, 9, 12, 14, 5, tzinfo=timezone.utc),
        )

    def test_dataset_allowlist_is_player_participation_only(self):
        self.assertEqual(set(PARTICIPATION_DATASETS), {
            "play_by_play", "play_participants", "player_box", "game_rosters"
        })
        with self.assertRaisesRegex(CFBParticipationSourceError, "DATASET_UNSUPPORTED"):
            select_participation_asset({}, dataset="betting", season=2026)

    def test_csv_gz_is_preferred_deterministically(self):
        plain_release, _, _ = self.release(gz=False)
        gz_release, _, gz_url = self.release(gz=True)
        payload = dict(plain_release)
        payload["assets"] = gz_release["assets"] + plain_release["assets"]
        asset = select_participation_asset(payload, dataset="play_participants", season=2026)
        self.assertTrue(asset.asset_name.endswith(".csv.gz"))
        self.assertEqual(asset.browser_download_url, gz_url)

    def test_non_pbp_cache_is_hash_bound_forward_only_and_non_authoritative(self):
        with tempfile.TemporaryDirectory() as td:
            body = b"game_id,athlete_id\n1,2\n"
            row = self.cache_with_body(dataset="play_participants", body=body, root=td)
            manifest = json.loads(Path(row["manifest_file"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["contract"], PARTICIPATION_CAPTURE_CONTRACT)
            self.assertFalse(manifest["raw_market_data_present"])
            self.assertTrue(manifest["raw_predictive_input_allowed"])
            self.assertIsNone(manifest["predictive_projection"])
            self.assertTrue(manifest["point_in_time_from_retrieval_forward"])
            self.assertFalse(manifest["retroactive_point_in_time_claim"])
            self.assertFalse(manifest["model_p_created"])
            self.assertFalse(manifest["promotion_authority"])
            self.assertEqual(manifest["content_sha256"], sha256(body).hexdigest())
            self.assertEqual(row["row_count"], 1)

    def test_raw_pbp_is_provenance_only_and_projection_is_exact_allowlist(self):
        with tempfile.TemporaryDirectory() as td:
            row = self.cache_with_body(
                dataset="play_by_play", body=self.pbp_bytes(), root=td
            )
            manifest = json.loads(Path(row["manifest_file"]).read_text(encoding="utf-8"))
            projection = manifest["predictive_projection"]
            self.assertTrue(manifest["raw_market_data_present"])
            self.assertFalse(manifest["raw_predictive_input_allowed"])
            self.assertEqual(projection["contract"], PBP_PROJECTION_CONTRACT)
            self.assertTrue(projection["projection_predictive_input_allowed"])
            self.assertFalse(projection["market_data_in_projection"])
            self.assertEqual(tuple(projection["predictive_columns"]), PBP_PREDICTIVE_COLUMNS)
            projection_path = Path(td) / projection["projection_relative_path"]
            with projection_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(tuple(reader.fieldnames or ()), PBP_PREDICTIVE_COLUMNS)
                rows = list(reader)
            self.assertEqual(len(rows), 1)
            forbidden = {
                "gameSpread", "homeFavorite", "gameSpreadAvailable", "overUnder",
                "homeTeamSpread", "start.pos_team_spread", "start.spread_time",
            }
            self.assertTrue(forbidden.isdisjoint(rows[0]))

    def test_pbp_projection_is_invariant_to_market_field_values(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            first = self.cache_with_body(
                dataset="play_by_play",
                body=self.pbp_bytes(spread="-21.5", total="55.5"),
                root=a,
            )
            second = self.cache_with_body(
                dataset="play_by_play",
                body=self.pbp_bytes(spread="+3.5", total="79.5"),
                root=b,
            )
            self.assertNotEqual(first["content_sha256"], second["content_sha256"])
            self.assertEqual(
                first["predictive_projection"]["projection_sha256"],
                second["predictive_projection"]["projection_sha256"],
            )

    def test_wrong_asset_digest_cannot_be_selected(self):
        release, _, _ = self.release(gz=False)
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
