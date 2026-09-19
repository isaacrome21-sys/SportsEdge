#!/usr/bin/env python3
"""Acquire the frozen 2015-2025 reconstructed CFB selection inputs.

Incomplete CFBD venue rows are skipped; games without resolvable coordinates
are omitted from reconstructed weather. Creates no Model_P / OFFICIAL authority.

See sportsedge.sports.cfb.venue_coordinates for skip helpers.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Re-export and run the full acquire implementation from the package module.
from sportsedge.sports.cfb.acquire_reconstructed_selection import main

if __name__ == "__main__":
    raise SystemExit(main())
