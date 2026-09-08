#!/usr/bin/env python3
from __future__ import annotations

import io, json, os, re, subprocess, sys, tarfile, zipfile
from pathlib import Path

ARCHIVE_EXTS = (".zip",".whl",".jar",".tar",".tar.gz",".tgz",".tar.bz2",".tbz2",".tar.xz",".txz",".gz",".bz2",".xz",".7z")
DANGEROUS_NAME = re.compile(r"(^|/)(\.env($|\.)|.*credential.*|.*secret.*|.*token.*|.*service[-_]?account.*|.*\.pem$|.*\.key$|.*\.p12$|.*\.pfx$|.*bankroll.*|.*balance.*|.*account.*|.*bet[-_]?ledger.*|.*wager.*)", re.I)
PATTERNS = [
    ("generic_api_assignment", re.compile(rb"(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[A-Za-z0-9._~+\-/]{12,}", re.I)),
    ("bearer", re.compile(rb"Bearer\s+[A-Za-z0-9._~+\-/]{12,}", re.I)),
    ("embedded_url_credentials", re.compile(rb"https?://[^/@\s:]+:[^/@\s]+@")),
    ("github_pat", re.compile(rb"github_pat_[A-Za-z0-9_]{12,}")),
    ("github_classic_pat", re.compile(rb"ghp_[A-Za-z0-9]{20,}")),
    ("openai_key", re.compile(rb"sk-[A-Za-z0-9_-]{16,}")),
    ("aws_access_key", re.compile(rb"AKIA[A-Z0-9]{16}")),
]
TEXT_EXTS = {".py",".json",".jsonl",".txt",".md",".yaml",".yml",".toml",".ini",".cfg",".csv",".env",".sh",".ps1",".joblib"}


def git(*args: str, input_bytes: bytes | None = None) -> bytes:
    return subprocess.check_output(["git", *args], input=input_bytes)


def archive_path(path: str) -> bool:
    p = path.lower()
    return any(p.endswith(ext) for ext in ARCHIVE_EXTS)


def scan_bytes(data: bytes) -> list[str]:
    hits = []
    for name, rx in PATTERNS:
        if rx.search(data):
            hits.append(name)
    return hits


def scan_zip(data: bytes) -> tuple[list[str], list[dict]]:
    names, hits = [], []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            names.append(info.filename)
            if info.is_dir():
                continue
            dangerous = bool(DANGEROUS_NAME.search(info.filename))
            member_hits = []
            try:
                member = z.read(info)
                if len(member) <= 20_000_000:
                    member_hits = scan_bytes(member)
            except Exception as exc:
                member_hits = [f"READ_ERROR:{type(exc).__name__}"]
            if dangerous or member_hits:
                hits.append({"member":info.filename,"dangerous_name":dangerous,"patterns":member_hits,"size":info.file_size})
    return names, hits


def scan_tar(data: bytes) -> tuple[list[str], list[dict]]:
    names, hits = [], []
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as tf:
        for info in tf.getmembers():
            names.append(info.name)
            if not info.isfile():
                continue
            dangerous = bool(DANGEROUS_NAME.search(info.name))
            member_hits = []
            try:
                f = tf.extractfile(info)
                member = f.read() if f else b""
                if len(member) <= 20_000_000:
                    member_hits = scan_bytes(member)
            except Exception as exc:
                member_hits = [f"READ_ERROR:{type(exc).__name__}"]
            if dangerous or member_hits:
                hits.append({"member":info.name,"dangerous_name":dangerous,"patterns":member_hits,"size":info.size})
    return names, hits


def main() -> int:
    rows = git("rev-list","--objects","--all").decode("utf-8","replace").splitlines()
    blobs = {}
    for line in rows:
        if " " not in line:
            continue
        sha, path = line.split(" ",1)
        if archive_path(path):
            blobs.setdefault(sha,set()).add(path)

    report = {"archive_blob_count":len(blobs),"archives":[],"sensitive_hits":[]}
    for sha, paths in sorted(blobs.items(), key=lambda kv: sorted(kv[1])[0]):
        data = git("cat-file","blob",sha)
        entry = {"blob_sha":sha,"paths":sorted(paths),"size":len(data),"members":[],"member_count":None,"scan_error":None}
        try:
            sample = sorted(paths)[0].lower()
            if sample.endswith((".zip",".whl",".jar")):
                names, hits = scan_zip(data)
            elif sample.endswith((".tar",".tar.gz",".tgz",".tar.bz2",".tbz2",".tar.xz",".txz")):
                names, hits = scan_tar(data)
            else:
                names, hits = [], []
                raw_hits = scan_bytes(data)
                if raw_hits:
                    hits.append({"member":"<raw-archive-bytes>","dangerous_name":False,"patterns":raw_hits,"size":len(data)})
            entry["members"] = names[:500]
            entry["member_count"] = len(names)
            for hit in hits:
                report["sensitive_hits"].append({"blob_sha":sha,"paths":sorted(paths),**hit})
        except Exception as exc:
            entry["scan_error"] = f"{type(exc).__name__}:{exc}"
            raw_hits = scan_bytes(data)
            if raw_hits:
                report["sensitive_hits"].append({"blob_sha":sha,"paths":sorted(paths),"member":"<raw-archive-bytes>","dangerous_name":False,"patterns":raw_hits,"size":len(data)})
        report["archives"].append(entry)

    Path("artifacts/security").mkdir(parents=True, exist_ok=True)
    Path("artifacts/security/archive-history-scan.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")

    root = next((x for x in report["archives"] if "SportsEdge_Automation_Wrapper_v1_1_1.zip" in x["paths"]), None)
    print(json.dumps({
        "archive_blob_count":report["archive_blob_count"],
        "root_zip":root,
        "sensitive_hit_count":len(report["sensitive_hits"]),
        "sensitive_hits":report["sensitive_hits"],
    }, indent=2, sort_keys=True))
    return 2 if report["sensitive_hits"] else 0

if __name__ == "__main__":
    raise SystemExit(main())
