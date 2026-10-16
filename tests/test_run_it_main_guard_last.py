"""RED (audit t208/t209): run_it_full must define every name main() needs
before the ``if __name__ == "__main__": main()`` guard executes.

Branches t208 (run_full wrapper) and t209-nfl (_nfl_canonical_distribution)
append defs AFTER the guard, so ``python artifacts/run_it_full.py ...``
raises NameError while imports (and therefore the test suite) pass.
"""
import ast
import json
import runpy
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "artifacts" / "run_it_full.py"


def test_no_definitions_after_main_guard():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    guard = None
    for i, node in enumerate(tree.body):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"):
            guard = i
    assert guard is not None
    late = [getattr(n, "name", type(n).__name__) for n in tree.body[guard + 1:]]
    assert late == [], f"statements after __main__ guard: {late}"


def test_cli_script_mode_runs_without_nameerror(tmp_path, monkeypatch):
    lines = tmp_path / "lines.json"
    lines.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(SRC), "--lines", str(lines), "--no-fetch"])
    try:
        runpy.run_path(str(SRC), run_name="__main__")
    except SystemExit:
        pass
    except NameError as exc:  # the defect
        pytest.fail(f"script-mode NameError: {exc}")
