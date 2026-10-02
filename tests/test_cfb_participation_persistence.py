from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb.participation_persistence import (
    CFBParticipationPersistenceError,
    GZIP_WRAPPER,
    audit_persisted_participation_snapshot,
    pack_participation_snapshot,
    restore_participation_snapshot,
)
from sportsedge.sports.cfb.participation_pit_readiness import audit_cfb_participation_snapshot
from sportsedge.sports.cfb.participation_source_capture import (
    PARTICIPATION_DATASETS,
    PBP_SOURCE_TO_CANONICAL,
    cache_participation_source,
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


def _pbp_bytes() -> bytes:
    fields = list(PBP_SOURCE_TO_CANONICAL)
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
    }
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerow(values)
    return stream.getvalue().encode("utf-8")


def _release(dataset: str, body: bytes):
    tag, prefix = PARTICIPATION_DATASETS[dataset]
    name = f"{prefix}_2026.csv"
    url = f"https://github.com/sportsdataverse/sportsdataverse-data/releases/download/{tag}/{name}"
    payload = {
        "id": 1000 + list(PARTICIPATION_DATASETS).index(dataset),
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "updated_at": "2026-09-12T14:00:00Z",
        "assets": [{
            "id": 2000 + list(PARTICIPATION_DATASETS).index(dataset),
            "name": name,
            "state": "uploaded",
            "size": len(body),
            "digest": "sha256:" + sha256(body).hexdigest(),
            "browser_download_url": url,
        }],
    }
    api = (
        "https://api.github.com/repos/sportsdataverse/sportsdataverse-data/"
        f"releases/tags/{tag}"
    )
    return api, url, payload


def _capture(root: Path) -> Path:
    source = root / "source"
    rows = []
    for dataset in PARTICIPATION_DATASETS:
        body = _pbp_bytes() if dataset == "play_by_play" else b"game_id,athlete_id\n401000001,99\n"
        api, asset_url, release = _release(dataset, body)
        opener = _Opener({
            api: json.dumps(release).encode("utf-8"),
            asset_url: body,
        })
        cached = cache_participation_source(
            dataset=dataset,
            season=2026,
            cache_root=source,
            opener=opener,
            retrieved_at=datetime(2026, 9, 12, 14, 5, tzinfo=timezone.utc),
        )
        manifest = json.loads(Path(cached["manifest_file"]).read_text(encoding="utf-8"))
        asset = manifest["asset"]
        rows.append({
            "dataset": dataset,
            "season": 2026,
            "release_tag": asset["release_tag"],
            "release_id": asset["release_id"],
            "asset_id": asset["asset_id"],
            "asset_name": asset["asset_name"],
            "content_sha256": manifest["content_sha256"],
            "source_retrieved_at": manifest["retrieved_at"],
            "manifest_sha256": manifest["manifest_sha256"],
            "cache_relative_path": manifest["cache_relative_path"],
            "raw_market_data_present": manifest["raw_market_data_present"],
            "raw_predictive_input_allowed": manifest["raw_predictive_input_allowed"],
            "predictive_projection": manifest["predictive_projection"],
        })

    capture = root / "capture"
    capture.mkdir(parents=True)
    classification = {
        "schema_version": "CFB_FORWARD_PARTICIPATION_CAPTURE_V1",
        "sport": "CFB",
        "capture_git_sha": "a" * 40,
        "season": 2026,
        "captured_at_utc": "2026-09-12T14:06:00Z",
        "pit_classification": "FORWARD_PARTICIPATION_SOURCE_SNAPSHOT_FROM_RETRIEVAL_TIME_ONLY",
        "point_in_time_from_capture_forward": True,
        "retroactive_point_in_time_claim": False,
        "promotion_evidence": False,
        "model_p_created": False,
        "eligibility_changed": False,
        "raw_market_data_present_in_provenance": True,
        "market_data_in_predictive_capture": False,
        "participation_model_fit_performed": False,
        "asset_count": len(rows),
        "assets": sorted(rows, key=lambda row: row["dataset"]),
    }
    (capture / "classification.json").write_text(
        json.dumps(classification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (capture / "id.txt").write_text("20260912T140600Z-aaaaaaaaaaaa\n", encoding="utf-8")
    (capture / "sources.json").write_text("{}\n", encoding="utf-8")
    ready = audit_cfb_participation_snapshot(capture / "classification.json")
    assert ready["participation_source_asof_ready"] is True, ready
    return root


class CFBParticipationPersistenceTests(unittest.TestCase):
    def test_pack_audit_and_restore_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            capture_root = _capture(base / "capture_root")
            persisted = base / "persisted"
            restored = base / "restored"

            manifest = pack_participation_snapshot(
                capture_root=capture_root,
                output_root=persisted,
            )
            self.assertFalse(manifest["model_p_created"])
            self.assertFalse(manifest["promotion_authority"])
            raw_rows = [row for row in manifest["files"] if row["kind"] == "RAW_SOURCE"]
            self.assertEqual(len(raw_rows), 4)
            self.assertTrue(all(row["compression"] == GZIP_WRAPPER for row in raw_rows))
            self.assertTrue(all(Path(row["stored_relative_path"]).suffix == ".gz" for row in raw_rows))

            audit = audit_persisted_participation_snapshot(persisted)
            self.assertEqual(audit["status"], "PERSISTED_SNAPSHOT_VERIFIED")
            self.assertEqual(audit["raw_source_count"], 4)
            self.assertEqual(audit["projection_count"], 1)
            self.assertFalse(audit["model_p_created"])

            restored_report = restore_participation_snapshot(
                persisted_root=persisted,
                output_root=restored,
            )
            self.assertTrue(restored_report["restored_participation_source_asof_ready"])
            ready = audit_cfb_participation_snapshot(restored / "capture" / "classification.json")
            self.assertTrue(ready["participation_source_asof_ready"])

    def test_tampered_storage_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            capture_root = _capture(base / "capture_root")
            persisted = base / "persisted"
            manifest = pack_participation_snapshot(
                capture_root=capture_root,
                output_root=persisted,
            )
            raw = next(row for row in manifest["files"] if row["kind"] == "RAW_SOURCE")
            target = persisted / raw["stored_relative_path"]
            target.write_bytes(target.read_bytes() + b"tamper")
            with self.assertRaisesRegex(
                CFBParticipationPersistenceError,
                "PERSISTED_HASH_MISMATCH",
            ):
                audit_persisted_participation_snapshot(persisted)

    def test_git_blob_size_guard_fails_before_persistence(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            capture_root = _capture(base / "capture_root")
            with self.assertRaisesRegex(
                CFBParticipationPersistenceError,
                "PERSISTED_FILE_TOO_LARGE",
            ):
                pack_participation_snapshot(
                    capture_root=capture_root,
                    output_root=base / "persisted",
                    max_stored_bytes=1,
                )


if __name__ == "__main__":
    unittest.main()
