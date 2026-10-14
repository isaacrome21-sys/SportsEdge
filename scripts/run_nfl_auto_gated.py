#!/usr/bin/env python3
"""Registry-gated entry point for scripts/run_nfl_auto.py (t126).

scripts/run_nfl_auto.py is pinned byte-for-byte in the frozen NFL M2 code
surface (config/nfl_m2_code_surface_v1.json), so it cannot be edited
without a governance re-pin. This wrapper runs it unchanged, then passes
the card it wrote through sportsedge.registry_gate before anything
downstream reads it. If the card cannot be read or re-written, the output
is replaced by a BLOCKED card (fail closed).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.registry_gate import gate_and_stamp as _registry_gate_and_stamp

RUNNER = "scripts/run_nfl_auto_gated.py (wraps scripts/run_nfl_auto.py)"


def _output_path(argv):
    for i, arg in enumerate(argv):
        if arg == "--output" and i + 1 < len(argv):
            return Path(argv[i + 1])
        if arg.startswith("--output="):
            return Path(arg.split("=", 1)[1])
    return Path("artifacts/run_it/nfl_card.json")


def gate_output(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("card is not an object")
    except (OSError, ValueError) as exc:
        payload = {"schema_version": "NFL_AUTO_RUN_V2", "status": "BLOCKED",
                   "blocker": "REGISTRY_GATE_UNREADABLE_CARD:" + type(exc).__name__}
    payload = _registry_gate_and_stamp(payload, "NFL", RUNNER)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "run_nfl_auto_frozen", _REPO_ROOT / "scripts/run_nfl_auto.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = _output_path(argv)
    out.parent.mkdir(parents=True, exist_ok=True)
    # The frozen runner can only publish into a private staging directory.
    # Neither an ungated card nor an older card is consumed as this result.
    with tempfile.TemporaryDirectory(prefix=".nfl-registry-", dir=out.parent) as tmp:
        staged = Path(tmp) / "card.json"
        child_argv = []
        skip = False
        for arg in argv:
            if skip:
                skip = False
                continue
            if arg == "--output":
                skip = True
                continue
            if arg.startswith("--output="):
                continue
            child_argv.append(arg)
        child_argv.extend(["--output", str(staged)])
        saved = sys.argv
        sys.argv = ["scripts/run_nfl_auto.py", *child_argv]
        try:
            code = mod.main()
        except Exception:
            # Publish only a fresh blocker when the child crashes.
            staged.write_text(json.dumps({"status": "BLOCKED",
                "blocker": "NFL_AUTO_CHILD_FAILED"}), encoding="utf-8")
            code = 2
        finally:
            sys.argv = saved
        try:
            gate_output(staged)
        except Exception:
            # A gate failure must never expose the frozen runner's raw result.
            staged.write_text(json.dumps({"status": "BLOCKED",
                "blocker": "REGISTRY_GATE_FAILED"}) + "\n", encoding="utf-8")
            code = 2
        with staged.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(staged, out)
        return code


if __name__ == "__main__":
    raise SystemExit(main())
