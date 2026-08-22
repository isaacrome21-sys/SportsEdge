#!/usr/bin/env python3
"""Fail if any Python source constructs AutoRunReport with positional args.

Research/freeze utility only. This does not alter model behavior. It is intended to
be run against the exact composed tree before integration is declared.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys

EXCLUDED_DIRS = {".git", ".venv", "venv", "build", "dist", "__pycache__"}


def find_violations(root: Path) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            violations.append(f"PARSE_ERROR {path}: {exc}")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            if name == "AutoRunReport" and node.args:
                violations.append(
                    f"POSITIONAL_AUTORUNREPORT {path}:{node.lineno} positional_args={len(node.args)}"
                )
    return violations


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path(args[0] if args else ".").resolve()
    violations = find_violations(root)
    if violations:
        print("\n".join(violations))
        return 1
    print("AUTORUNREPORT_KEYWORD_ONLY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
