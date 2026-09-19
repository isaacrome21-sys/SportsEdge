"""Reconstructed CFB selection acquisition (venue-skip aware).

Implementation is split across sibling private part files for maintainability.
"""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parent
_src = (_DIR / "_acquire_reconstructed_selection_part1.py").read_text(encoding="utf-8")
_src += (_DIR / "_acquire_reconstructed_selection_part2.py").read_text(encoding="utf-8")
_ns: dict = {"__name__": __name__, "__file__": str(Path(__file__).resolve())}
exec(compile(_src, str(Path(__file__).resolve()), "exec"), _ns)
main = _ns["main"]
CFBAcquisitionError = _ns["CFBAcquisitionError"]
build_request_plan = _ns["build_request_plan"]
