from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.sports.cfb.participation_pit_readiness import (
    REQUIRED_DATASETS,
    SNAPSHOT_SCHEMA,
    audit_cfb_participation_snapshot,
)
from sportsedge.sports.cfb.participation_source_capture import PARTICIPATION_CAPTURE_CONTRACT


class CFBParticipationPITReadinessTests(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        base = root / "artifacts/cfb_forward_participation"
        source = base / "source"
        capture = base / "capture"
        capture.mkdir(parents=True)
        rows = []
        for idx, dataset in enumerate(sorted(REQUIRED_DATASETS), start=1):
            body = f"game_id,player_id\n{idx},{idx * 10}\n".encode("utf-8")
            rel = Path(dataset) / "2026" / f"{dataset}_2026.csv"
            cache_path = source / rel
            cache_path.parent.mkdir(parents=True)
            cache_path.write_bytes(body)
            content_sha = sha256(body).hexdigest()
            manifest = {
                "contract": PARTICIPATION_CAPTURE_CONTRACT,
                "asset": {
                    "dataset": dataset,
                    "season": 2026,
                    "release_tag": f"tag-{dataset}",
                    "release_id": idx,
                    "release_updated_at": "2026-09-12T13:50:00Z",
                    "asset_id": idx + 100,
                    "asset_name": cache_path.name,
                    "browser_download_url": f"https://github.com/sportsdataverse/sportsdataverse-data/releases/download/tag-{dataset}/{cache_path.name}",
                    "sha256": content_sha,
                    "size": len(body),
                    "usage": "PREDICTIVE_PARTICIPATION_INPUT",
                },
                "retrieved_at": "2026-09-12T14:00:00+00:00",
                "content_sha256": content_sha,
                "row_count": 1,
                "market_role": "PREDICTIVE_PARTICIPATION_INPUT",
                "cache_relative_path": rel.as_posix(),
                "cache_reused": False,
                "market_data": False,
                "point_in_time_from_retrieval_forward": True,
                "retroactive_point_in_time_claim": False,
                "model_p_created": False,
                "promotion_authority": False,
            }
            digest = sha256(
                json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
            ).hexdigest()
            manifest["manifest_sha256"] = digest
            (cache_path.parent / "manifest.json").write_text(
                json.dumps(manifest, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            rows.append({
                "dataset": dataset,
                "season": 2026,
                "release_tag": f"tag-{dataset}",
                "release_id": idx,
                "asset_id": idx + 100,
                "asset_name": cache_path.name,
                "content_sha256": content_sha,
                "source_retrieved_at": "2026-09-12T14:00:00+00:00",
                "manifest_sha256": digest,
                "cache_relative_path": rel.as_posix(),
            })
        classification = {
            "schema_version": SNAPSHOT_SCHEMA,
            "sport": "CFB",
            "capture_git_sha": "a" * 40,
            "season": 2026,
            "captured_at_utc": "2026-09-12T14:05:00Z",
            "pit_classification": "FORWARD_PARTICIPATION_SOURCE_SNAPSHOT_FROM_RETRIEVAL_TIME_ONLY",
            "point_in_time_from_capture_forward": True,
            "retroactive_point_in_time_claim": False,
            "promotion_evidence": False,
            "model_p_created": False,
            "eligibility_changed": False,
            "market_data_in_predictive_capture": False,
            "participation_model_fit_performed": False,
            "asset_count": len(rows),
            "assets": rows,
        }
        path = capture / "classification.json"
        path.write_text(json.dumps(classification, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return path

    def test_complete_snapshot_is_source_ready_but_never_truth_gate_ready(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._fixture(Path(td))
            report = audit_cfb_participation_snapshot(path)
            self.assertTrue(report["participation_source_asof_ready"])
            self.assertEqual(report["verified_asset_count"], 4)
            self.assertEqual(report["blockers"], [])
            self.assertFalse(report["truth_gate_ready"])
            self.assertFalse(report["model_p_created"])
            self.assertFalse(report["promotion_authority"])
            self.assertFalse(report["eligibility_changed"])
            self.assertFalse(report["retroactive_point_in_time_claim"])

    def test_missing_dataset_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._fixture(Path(td))
            payload = json.loads(path.read_text(encoding="utf-8"))
            missing = payload["assets"].pop()
            path.write_text(json.dumps(payload), encoding="utf-8")
            report = audit_cfb_participation_snapshot(path)
            self.assertFalse(report["participation_source_asof_ready"])
            self.assertTrue(any(code.startswith("CFB_PARTICIPATION_DATASETS_MISSING:") for code in report["blockers"]))

    def test_tampered_source_bytes_block(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = self._fixture(root)
            payload = json.loads(path.read_text(encoding="utf-8"))
            rel = payload["assets"][0]["cache_relative_path"]
            cache_path = root / "artifacts/cfb_forward_participation/source" / rel
            cache_path.write_bytes(cache_path.read_bytes() + b"tamper")
            report = audit_cfb_participation_snapshot(path)
            self.assertFalse(report["participation_source_asof_ready"])
            self.assertTrue(any("CONTENT_HASH_MISMATCH" in code for code in report["blockers"]))

    def test_retroactive_pit_claim_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._fixture(Path(td))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["retroactive_point_in_time_claim"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            report = audit_cfb_participation_snapshot(path)
            self.assertFalse(report["participation_source_asof_ready"])
            self.assertIn("CFB_PARTICIPATION_RETROACTIVE_PIT_FORBIDDEN", report["blockers"])

    def test_market_contamination_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            path = self._fixture(Path(td))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["market_data_in_predictive_capture"] = True
            path.write_text(json.dumps(payload), encoding="utf-8")
            report = audit_cfb_participation_snapshot(path)
            self.assertFalse(report["participation_source_asof_ready"])
            self.assertIn("CFB_PARTICIPATION_MARKET_CONTAMINATION", report["blockers"])


if __name__ == "__main__":
    unittest.main()
