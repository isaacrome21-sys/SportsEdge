"""Regression guard for retired CFB market-anchored Lane B.

Checks structural fail-closed behavior without synthetic market quotes.
"""
from pathlib import Path


def test_cfb_lane_b_retired_before_market_anchor():
    source = Path("artifacts/free_models.py").read_text(encoding="utf-8")
    start = source.index('    anchor_weight = 0.0 if sport == "CFB" else ANCHOR_WEIGHT')
    end = source.index('    if lane_b_blocked is None:', start)
    block = source[start:end]
    assert 'if sport == "CFB":\n        lane_b_blocked = "CFB_LANE_B_RETIRED_UNVALIDATED"' in block
    assert block.index('if sport == "CFB":') < block.index('elif market == "TOTAL":')
    assert block.index('if sport == "CFB":') < block.index('elif market == "SPREAD":')
    assert block.index('if sport == "CFB":') < block.index('opposite = row.get("opposite_odds")')
    assert 'elif market == "TEAM_TOTALS":' in block


def test_unavailable_lane_b_cannot_be_primary_price():
    source = Path("artifacts/free_models.py").read_text(encoding="utf-8")
    assert 'if lane == "B" and lane_b.get("status") == "LANE_B_UNAVAILABLE":' in source
    assert '"research_only": True}' in source
