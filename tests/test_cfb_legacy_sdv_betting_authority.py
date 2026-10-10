"""Legacy CFB manual card must not confer betting authority from raw model edge."""
import json
import subprocess
import sys
from pathlib import Path


def test_legacy_sdv_has_no_official_bet_promotion():
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_cfb_sdv_card.py"
    source = script.read_text(encoding="utf-8")
    assert '"bet_status": "BLOCKED"' in source
    assert '"reason": "LEGACY_UNCALIBRATED_PROBABILITY_NO_BETTING_AUTHORITY"' in source
    assert '"bet_status": "OFFICIAL_BET" if edge > 0' not in source
