#!/usr/bin/env python3
"""LIVE RUN IT: live/in-game research card from free provider game state.

Phone-shaped intake: Isaac sends live lines, gets a research card back.
RESEARCH ONLY -- no auto-betting, no bet execution, no bet-placement code
paths. See sportsedge/live_run_it.py and docs/live_inplay.md.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sportsedge.live_run_it import main

if __name__ == "__main__":
    raise SystemExit(main())
