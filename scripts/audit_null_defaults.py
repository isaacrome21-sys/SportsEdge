#!/usr/bin/env python3
"""Inventory Python `or <empty>` defaults that can erase unknown state.

The scanner is intentionally syntax-based rather than grep-based so multiline
expressions are included. It does not decide business semantics by itself; each
hit is emitted with enough context for an explicit SAFE_DEFAULT or
FALSE_ZERO_DEFECT adjudication.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

TARGETS = {"0", "0.0", "[]", '""', "''"}
SKIP_PARTS = {".git", ".venv", "venv", "__pycache__", ".data-branch"}


def _is_target(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return node.value in (0, 0.0, "")
    return isinstance(node, ast.List) and not node.elts


def _left_kind(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "get":
            return "mapping_get"
        if isinstance(node.func, ast.Name) and node.func.id == "getattr":
            return "getattr"
        return "call"
    if isinstance(node, ast.Subscript):
        return "subscript"
    if isinstance(node, ast.Name):
        return "name"
    if isinstance(node, ast.Attribute):
        return "attribute"
    return type(node).__name__


def scan_file(path: Path, *, root: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
    except Exception as exc:
        return [{
            "path": path.relative_to(root).as_posix(),
            "line": 0,
            "expression": "",
            "left_kind": "parse_error",
            "verdict": "REVIEW_REQUIRED",
            "reason": f"{type(exc).__name__}: {exc}",
        }]

    out: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BoolOp) or not isinstance(node.op, ast.Or):
            continue
        values = list(node.values)
        if len(values) < 2 or not _is_target(values[-1]):
            continue
        fallback = ast.get_source_segment(text, values[-1]) or ""
        if fallback not in TARGETS and not (isinstance(values[-1], ast.List) and not values[-1].elts):
            continue
        expression = ast.get_source_segment(text, node) or ""
        rel = path.relative_to(root).as_posix()
        out.append({
            "path": rel,
            "line": int(getattr(node, "lineno", 0)),
            "expression": " ".join(expression.split()),
            "fallback": fallback,
            "left_kind": _left_kind(values[-2]),
            "verdict": "REVIEW_REQUIRED",
            "reason": "Empty fallback can collapse missing/unknown into a real value; requires explicit semantic adjudication.",
        })
    return out


def scan_repo(root: Path) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        hits.extend(scan_file(path, root=root))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    hits = scan_repo(root)
    payload = {
        "audit": "python_null_default_idioms_v1",
        "patterns": ["or 0", "or 0.0", "or []", "or empty-string"],
        "hit_count": len(hits),
        "hits": hits,
    }
    rendered = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
