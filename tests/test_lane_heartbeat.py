import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.build_lane_status import build
from scripts.update_lane_heartbeat import build_pointer, write_pointer


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    subprocess.check_call(["git", "-C", str(root), "init", "-q"])
    subprocess.check_call(["git", "-C", str(root), "config", "user.email", "test@example.com"])
    subprocess.check_call(["git", "-C", str(root), "config", "user.name", "test"])
    return root


def _commit(root: Path, rel: str, content: str) -> str:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    subprocess.check_call(["git", "-C", str(root), "add", rel])
    subprocess.check_call(["git", "-C", str(root), "commit", "-qm", "evidence"])
    return _git(root, "rev-parse", "HEAD")


def test_pointer_references_tracked_durable_artifact(tmp_path):
    root = _repo(tmp_path)
    sha = _commit(root, "runtime/archive-status/2026-08-21/run.json", '{"status":"CAPTURED"}\n')
    payload = build_pointer(root, "mlb_archive", "runtime/archive-status/2026-08-21/run.json", sha, "CAPTURED", "123", "schedule")
    path = write_pointer(root, "runtime/heartbeat/archive_latest.json", payload)
    saved = json.loads(path.read_text())
    assert saved["durable_commit_sha"] == sha
    assert saved["source_artifact"].endswith("run.json")
    assert saved["pointer_role"] == "DERIVED_CACHE_CANONICAL_ARTIFACT_WINS"


def test_persistence_failure_does_not_move_pointer(tmp_path):
    root = _repo(tmp_path)
    old_sha = _commit(root, "runtime/archive-status/2026-08-20/run.json", '{"status":"CAPTURED"}\n')
    old = build_pointer(root, "mlb_archive", "runtime/archive-status/2026-08-20/run.json", old_sha, "CAPTURED", "100", "schedule")
    pointer = write_pointer(root, "runtime/heartbeat/archive_latest.json", old)
    before = pointer.read_text()

    with pytest.raises(SystemExit, match="durable source artifact missing"):
        build_pointer(root, "mlb_archive", "runtime/archive-status/2026-08-21/missing.json", old_sha, "CAPTURED", "101", "schedule")

    assert pointer.read_text() == before


def test_sha_mismatch_does_not_move_pointer(tmp_path):
    root = _repo(tmp_path)
    sha = _commit(root, "runtime/archive-status/2026-08-21/run.json", '{}\n')
    pointer = root / "runtime/heartbeat/archive_latest.json"
    pointer.parent.mkdir(parents=True, exist_ok=True)
    pointer.write_text('{"sentinel":true}\n')

    with pytest.raises(SystemExit, match="durable SHA mismatch"):
        build_pointer(root, "mlb_archive", "runtime/archive-status/2026-08-21/run.json", "0" * 40, "CAPTURED", None, None)

    assert json.loads(pointer.read_text()) == {"sentinel": True}


def test_status_distinguishes_missing_unreadable_and_stale(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    hb = root / "runtime/heartbeat"
    hb.mkdir(parents=True)

    # Archive pointer exists but is malformed: this is pointer failure, not staleness.
    (hb / "archive_latest.json").write_text('{not-json\n', encoding="utf-8")

    # NRFI pointer is valid and its canonical source exists, but evidence is old.
    source_rel = "runtime/model-validation/NRFI_YRFI/runs/123/report.json"
    source = root / source_rel
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('{}\n', encoding="utf-8")
    (hb / "nrfi_latest.json").write_text(json.dumps({
        "last_durable_at_utc": "2026-08-20T00:00:00+00:00",
        "source_artifact": source_rel,
        "durable_commit_sha": "a" * 40,
        "status": "MODEL_NOT_ELIGIBLE",
        "evidence_count": 53,
    }) + "\n", encoding="utf-8")

    status = build(root, now=datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc))
    assert status["lanes"]["archive"]["state"] == "POINTER_UNREADABLE"
    assert status["lanes"]["archive"]["pointer_state"] == "UNREADABLE"
    assert status["lanes"]["nrfi"]["state"] == "LANE_STALE"
    assert status["lanes"]["nrfi"]["pointer_state"] == "OK"


def test_status_marks_missing_pointer_separately(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    status = build(root, now=datetime(2026, 8, 22, 0, 0, tzinfo=timezone.utc))
    assert status["lanes"]["archive"]["state"] == "POINTER_MISSING"
    assert status["lanes"]["nrfi"]["state"] == "POINTER_MISSING"
