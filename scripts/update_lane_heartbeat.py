#!/usr/bin/env python3
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def build_pointer(
    root: Path,
    lane: str,
    source_artifact: str,
    expected_sha: str,
    status: str,
    workflow_run_id: str | None,
    trigger: str | None,
    source_event_at_utc: str | None = None,
    evidence_count: int | None = None,
) -> dict:
    root = root.resolve()
    source = (root / source_artifact).resolve()
    try:
        source.relative_to(root)
    except ValueError as exc:
        raise SystemExit("source_artifact escapes data root") from exc
    if not source.is_file():
        raise SystemExit(f"durable source artifact missing: {source_artifact}")

    head = _git(root, "rev-parse", "HEAD")
    if head != expected_sha:
        raise SystemExit(f"durable SHA mismatch: expected {expected_sha}, got {head}")

    tracked = _git(root, "ls-tree", "-r", "--name-only", "HEAD", "--", source_artifact)
    if tracked.strip() != source_artifact:
        raise SystemExit(f"source artifact is not tracked at durable SHA: {source_artifact}")

    payload = {
        "lane": lane,
        "last_durable_at_utc": source_event_at_utc or datetime.now(timezone.utc).isoformat(),
        "pointer_updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_artifact": source_artifact,
        "source_artifact_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "durable_commit_sha": head,
        "status": status,
        "workflow_run_id": workflow_run_id,
        "trigger": trigger,
        "pointer_role": "DERIVED_CACHE_CANONICAL_ARTIFACT_WINS",
    }
    if evidence_count is not None:
        payload["evidence_count"] = evidence_count
    return payload


def write_pointer(root: Path, pointer_relpath: str, payload: dict) -> Path:
    path = root / pointer_relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--lane", required=True)
    ap.add_argument("--source-artifact", required=True)
    ap.add_argument("--durable-sha", required=True)
    ap.add_argument("--status", required=True)
    ap.add_argument("--pointer", required=True)
    ap.add_argument("--workflow-run-id")
    ap.add_argument("--trigger")
    ap.add_argument("--source-event-at-utc")
    ap.add_argument("--evidence-count", type=int)
    args = ap.parse_args()

    root = Path(args.data_root)
    payload = build_pointer(
        root,
        args.lane,
        args.source_artifact,
        args.durable_sha,
        args.status,
        args.workflow_run_id,
        args.trigger,
        args.source_event_at_utc,
        args.evidence_count,
    )
    path = write_pointer(root, args.pointer, payload)
    print(json.dumps({"pointer": str(path), **payload}, sort_keys=True))


if __name__ == "__main__":
    main()
