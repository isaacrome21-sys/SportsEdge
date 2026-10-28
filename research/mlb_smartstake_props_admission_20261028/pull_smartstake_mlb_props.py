#!/usr/bin/env python3
"""Pull + pin-verify the SmartStake MLB player-props dataset (canonical repo).

Admission packet: research/mlb_smartstake_props_admission_20261028/.
The dataset is pinned by (dataset id, revision) plus a per-partition
sha256 manifest (admission_manifest.json). This script re-pulls every
partition at the pinned revision and accepts a file ONLY when its size
and sha256 equal the manifest pin (which equals the Hugging Face LFS oid
published at that revision). Transport is untrusted-but-verified: bytes
are admitted by hash, never by route.

The HF CDN drops connections mid-stream on some egress networks, and it
honors HTTP Range, so downloads use an append-resume loop. Data bytes are
written to the local pulls directory only; nothing is committed to git.

Usage: python3 pull_smartstake_mlb_props.py <output_dir>
"""
import hashlib
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

DATASET = "SmartStake/mlb-player-props"
REVISION = "7cedfd3fe29f2de4f675039410a48160739323fc"
MANIFEST = Path(__file__).with_name("admission_manifest.json")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_oids() -> dict:
    url = f"https://huggingface.co/api/datasets/{DATASET}/tree/{REVISION}?recursive=true"
    with urllib.request.urlopen(url) as resp:  # noqa: S310 - pinned canonical host
        tree = json.load(resp)
    return {e["path"]: e["lfs"]["oid"] for e in tree
            if e.get("type") == "file" and e["path"].endswith(".parquet")}


def resume_download(url: str, tmp: Path, want_bytes: int) -> None:
    for _ in range(120):
        cur = tmp.stat().st_size if tmp.exists() else 0
        if cur == want_bytes:
            return
        if cur > want_bytes:
            tmp.unlink()
            continue
        subprocess.run(  # noqa: S603 - fixed argv, pinned URL
            ["curl", "-sL", "-C", "-", "--connect-timeout", "20", "--max-time", "240",
             url, "-o", str(tmp)], check=False)
    if not tmp.exists() or tmp.stat().st_size != want_bytes:
        raise SystemExit(f"download incomplete for {url}")


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pulls")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    live = tree_oids()
    ok = True
    for entry in manifest["partitions"]:
        path, want_bytes, want_sha = entry["path"], entry["bytes"], entry["sha256"]
        if live.get(path) != want_sha:
            print(f"REVISION DRIFT {path}: manifest {want_sha} != live oid {live.get(path)}")
            ok = False
            continue
        dest = out_dir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.stat().st_size == want_bytes and sha256_of(dest) == want_sha:
            print(f"PIN_MATCH (cached) {path}")
            continue
        tmp = dest.with_suffix(dest.suffix + ".part")
        resume_download(
            f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{path}",
            tmp, want_bytes)
        if sha256_of(tmp) == want_sha:
            tmp.replace(dest)
            print(f"PIN_MATCH {path}")
        else:
            print(f"PIN_MISMATCH {path}")
            ok = False
    print("ALL PIN_MATCH" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
