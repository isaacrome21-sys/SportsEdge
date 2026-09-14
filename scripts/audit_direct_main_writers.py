#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

WORKFLOW_SUFFIXES = (".yml", ".yaml")
NON_GIT_MAIN_PATTERNS = (
    ("GH_API_MAIN_REF", re.compile(r"\bgh\s+api\b[^\n]*/git/refs/heads/main\b")),
    ("GH_API_CONTENTS_WRITE", re.compile(r"\bgh\s+api\b[^\n]*/contents/")),
    ("HTTP_MAIN_REF_API", re.compile(r"\b(?:curl|wget)\b[^\n]*/git/refs/heads/main\b")),
    ("HTTP_CONTENTS_API_WRITE", re.compile(r"\b(?:curl|wget)\b[^\n]*/contents/")),
    ("GITHUB_SCRIPT_CONTENT_WRITE", re.compile(r"\b(?:createOrUpdateFileContents|updateRef|createRef)\b")),
    ("GIT_AUTO_COMMIT_ACTION", re.compile(r"stefanzweifel/git-auto-commit-action@", re.I)),
    ("GITHUB_PUSH_ACTION", re.compile(r"ad-m/github-push-action@", re.I)),
)


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"WRITER_GUARD_GIT_FAILED:{' '.join(args)}:{proc.returncode}")
    return proc.stdout


def _read(repo: Path, ref: str, path: str) -> str:
    return _git(repo, "show", f"{ref}:{path}")


def _tree(repo: Path, ref: str) -> list[str]:
    return sorted(p for p in _git(repo, "ls-tree", "-r", "--name-only", ref).splitlines() if p)


def _checkout_static_non_main(text: str) -> str | None:
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        if "uses:" not in line or "actions/checkout@" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        for follow in lines[idx + 1 :]:
            stripped = follow.strip()
            if not stripped:
                continue
            follow_indent = len(follow) - len(follow.lstrip())
            if follow_indent <= indent:
                break
            match = re.match(r"ref:\s*['\"]?([^'\"#\s]+)", stripped)
            if match:
                ref = match.group(1)
                if "${{" in ref or "$" in ref:
                    return None
                normalized = ref.removeprefix("refs/heads/")
                if normalized != "main":
                    return normalized
                return None
    return None


def _classify_refspec(token: str, checkout_non_main: str | None) -> tuple[str, str]:
    if "${{" in token or "$" in token or "$(" in token:
        return "UNRESOLVABLE", "PUSH_TARGET_INTERPOLATED"
    if token in {"main", "HEAD:main", "refs/heads/main"} or token.endswith(":refs/heads/main"):
        return "MAIN_WRITER", "PUSH_TARGET_MAIN"
    if token == "HEAD":
        if checkout_non_main:
            return "NON_MAIN", "PUSH_HEAD_CHECKOUT_PROVEN_NON_MAIN"
        return "UNRESOLVABLE", "PUSH_HEAD_TARGET_UNRESOLVED"
    if ":" in token:
        _src, dst = token.rsplit(":", 1)
        normalized = dst.removeprefix("refs/heads/")
        if normalized == "main":
            return "MAIN_WRITER", "PUSH_TARGET_MAIN"
        if normalized:
            return "NON_MAIN", "PUSH_TARGET_PROVEN_NON_MAIN"
    normalized = token.removeprefix("refs/heads/")
    if normalized and normalized not in {"HEAD", "main"} and re.fullmatch(r"[A-Za-z0-9._/-]+", normalized):
        return "NON_MAIN", "PUSH_TARGET_PROVEN_NON_MAIN"
    return "UNRESOLVABLE", "PUSH_TARGET_UNRESOLVED"


def classify_git_push(command: str, checkout_non_main: str | None = None) -> tuple[str, str]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return "UNRESOLVABLE", "PUSH_COMMAND_UNPARSEABLE"
    try:
        idx = next(i for i in range(len(tokens) - 1) if tokens[i] == "git" and tokens[i + 1] == "push")
    except StopIteration:
        return "NON_WRITER", "NO_GIT_PUSH"
    args = tokens[idx + 2 :]
    if "--all" in args:
        return "MAIN_WRITER", "PUSH_ALL_INCLUDES_MAIN"
    if "--mirror" in args:
        return "MAIN_WRITER", "PUSH_MIRROR_INCLUDES_MAIN"
    if any("${{" in tok or "$(" in tok or tok.startswith("$") for tok in args):
        return "UNRESOLVABLE", "PUSH_TARGET_INTERPOLATED"
    positional = [tok for tok in args if not tok.startswith("-")]
    if not positional or len(positional) == 1:
        return "UNRESOLVABLE", "BARE_GIT_PUSH_TARGET_UNRESOLVED"
    refspecs = positional[1:]
    classifications = [_classify_refspec(token, checkout_non_main) for token in refspecs]
    if any(kind == "MAIN_WRITER" for kind, _ in classifications):
        return next(item for item in classifications if item[0] == "MAIN_WRITER")
    if any(kind == "UNRESOLVABLE" for kind, _ in classifications):
        return next(item for item in classifications if item[0] == "UNRESOLVABLE")
    return "NON_MAIN", "PUSH_TARGETS_PROVEN_NON_MAIN"


def _referenced_local_paths(text: str) -> list[tuple[str, str]]:
    refs: set[tuple[str, str]] = set()
    for match in re.finditer(r"(?:bash|sh)\s+([^\s;&|]+)|(?:^|\s)(\./[^\s;&|]+)", text, re.M):
        value = match.group(1) or match.group(2)
        if value and "$" not in value and "${{" not in value:
            refs.add((value.removeprefix("./"), "FILE"))
    for match in re.finditer(r"uses:\s*\.\/([^\s#]+)", text):
        refs.add((match.group(1).rstrip("/"), "COMPOSITE"))
    return sorted(refs)


def _permissions_state(text: str) -> tuple[str, str]:
    if re.search(r"(?m)^\s*contents:\s*write\s*$", text):
        return "WRITE", "CONTENTS_WRITE_EXPLICIT"
    if re.search(r"(?m)^\s*contents:\s*read\s*$", text):
        return "READ_ONLY", "CONTENTS_READ_EXPLICIT"
    return "UNRESOLVABLE", "CONTENTS_PERMISSION_INHERITED_OR_UNSPECIFIED"


def audit(repo: Path, ref: str = "HEAD") -> dict[str, Any]:
    tree = _tree(repo, ref)
    tree_set = set(tree)
    workflows = [p for p in tree if p.startswith(".github/workflows/") and p.endswith(WORKFLOW_SUFFIXES)]
    findings: list[dict[str, Any]] = []
    for path in workflows:
        text = _read(repo, ref, path)
        checkout_non_main = _checkout_static_non_main(text)
        permission_state, permission_reason = _permissions_state(text)
        sources: list[tuple[str, str]] = [(path, text)]
        for local, kind in _referenced_local_paths(text):
            candidates = [local] if kind == "FILE" else [local + "/action.yml", local + "/action.yaml"]
            existing = [candidate for candidate in candidates if candidate in tree_set]
            if not existing:
                findings.append({"workflow": path, "source": local, "classification": "UNRESOLVABLE", "reason": "CALLED_LOCAL_SOURCE_NOT_FOUND", "permission_state": permission_state, "permission_reason": permission_reason})
                continue
            for candidate in existing:
                sources.append((candidate, _read(repo, ref, candidate)))
        for source_path, source_text in sources:
            for line_no, line in enumerate(source_text.splitlines(), 1):
                if "git push" in line:
                    classification, reason = classify_git_push(line.strip(), checkout_non_main)
                    if classification not in {"NON_MAIN", "NON_WRITER"}:
                        findings.append({"workflow": path, "source": source_path, "line": line_no, "classification": classification, "reason": reason, "permission_state": permission_state, "permission_reason": permission_reason, "snippet": line.strip()})
            for reason, pattern in NON_GIT_MAIN_PATTERNS:
                for match in pattern.finditer(source_text):
                    line_no = source_text.count("\n", 0, match.start()) + 1
                    findings.append({"workflow": path, "source": source_path, "line": line_no, "classification": "MAIN_WRITER", "reason": reason, "permission_state": permission_state, "permission_reason": permission_reason})
    blocking = [f for f in findings if f["classification"] in {"MAIN_WRITER", "UNRESOLVABLE"}]
    status = "QUIESCED" if not blocking else "BLOCKED_OR_UNRESOLVED"
    return {
        "schema": "SPORTSEDGE_DIRECT_MAIN_WRITER_GUARD_V2",
        "status": status,
        "ref": ref,
        "resolved_head_sha": _git(repo, "rev-parse", ref).strip(),
        "workflow_count": len(workflows),
        "findings": findings,
        "blocking_findings": blocking,
        "authority": {k: False for k in ("model_p", "truth_gate", "promotion", "staking", "official", "validation_attempt", "untouched_readout")},
        "proof_ceiling": "NO_DECLARED_OR_STATICALLY_REACHABLE_MAIN_WRITER_DETECTED_AT_THIS_REF; DOES_NOT_PROVE_MAIN_CANNOT_ADVANCE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed target-aware audit for workflow paths that can write default main.")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--ref", default="HEAD")
    parser.add_argument("--output")
    parser.add_argument("--require-quiesced", action="store_true")
    args = parser.parse_args()
    report = audit(Path(args.repo).resolve(), args.ref)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if args.require_quiesced and report["blocking_findings"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
