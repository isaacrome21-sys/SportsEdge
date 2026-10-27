"""Run the pinned NBA TT count gate regressions in hosted `pytest -q tests`.

The dedicated count-gate tests live beside the frozen NBA TT research
evaluator and are not discovered by the default repository CI command.
Import the exact five cases into the ordinary tests/ tree so the real
public-entry matching-forged-SHA regression cannot silently go untested.
No frozen evaluator or statistical terms are changed.
"""
from __future__ import annotations

import sys
from pathlib import Path

_RESEARCH_DIR = (
    Path(__file__).resolve().parents[1]
    / "research" / "nba_team_totals_forward_20261022"
)
if str(_RESEARCH_DIR) not in sys.path:
    sys.path.insert(0, str(_RESEARCH_DIR))

from test_count_gate_nba_team_totals_v1 import (  # noqa: E402, F401
    test_count_gate_no_receipt_refuses_before_scoring,
    test_count_gate_matching_forged_receipt_refused,
    test_count_gate_pre_pin_rows_refused,
    test_count_gate_forged_config_refused,
    test_count_gate_synthetic_reviewed_pin_positive_path,
)
