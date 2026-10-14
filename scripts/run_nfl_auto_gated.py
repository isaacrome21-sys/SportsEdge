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
    return None


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
    saved = sys.argv
    sys.argv = ["scripts/run_nfl_auto.py", *argv]
    try:
        code = mod.main()
    finally:
        sys.argv = saved
    out = _output_path(argv)
    if out is not None and out.exists():
        gate_output(out)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
