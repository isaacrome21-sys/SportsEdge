#!/usr/bin/env python3
"""Repair reconstructed-selection week-bound drift before holdout evaluation.

The frozen CFBD request plan requests current-season advanced metrics for endWeek
1 through max_regular_week_planning_bound-1 (1..15 for the frozen bound of 16).
The private-payload builder previously iterated range(1, 20), which would request
unfetched identities at endWeek 16 after all provider calls had completed.

This transformer makes the plan and payload builder share one config-derived helper.
It changes no provider call count, model logic, features, weights, seeds, thresholds,
line policy, or holdout authority.
"""
from __future__ import annotations

from hashlib import sha1
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/acquire_cfb_reconstructed_selection.py"
TEST = ROOT / "tests/test_cfb_reconstructed_week_bound.py"
EXPECTED_INPUT_GIT_BLOB_SHA1 = "ee17b9be4c5ce52d917b159907d843b9499d7d4d"
PATCH_MARKER = "CFB_RECONSTRUCTED_WEEK_BOUND_V1"


def _git_blob_sha(text: str) -> str:
    raw = text.encode("utf-8")
    return sha1(f"blob {len(raw)}\0".encode("ascii") + raw).hexdigest()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"CFB_WEEK_BOUND_REPAIR_REPLACEMENT_COUNT:{label}:{count}")
    return text.replace(old, new, 1)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if PATCH_MARKER in text:
        print("CFB_RECONSTRUCTED_WEEK_BOUND_REPAIR_ALREADY_APPLIED")
        return 0
    actual = _git_blob_sha(text)
    if actual != EXPECTED_INPUT_GIT_BLOB_SHA1:
        raise SystemExit(f"CFB_WEEK_BOUND_REPAIR_SOURCE_BLOB_MISMATCH:{actual}")

    text = _replace_once(
        text,
        'CFB_RECONSTRUCTED_TEAM_ID_BINDING_V1 = "CFBD_TEAM_ID_FIRST_ALIAS_FALLBACK_V1"\n',
        'CFB_RECONSTRUCTED_TEAM_ID_BINDING_V1 = "CFBD_TEAM_ID_FIRST_ALIAS_FALLBACK_V1"\n'
        'CFB_RECONSTRUCTED_WEEK_BOUND_V1 = "CONFIG_MAX_REGULAR_WEEK_EXCLUSIVE_V1"\n',
        "marker",
    )

    old_plan = '''    max_week = int(config["max_regular_week_planning_bound"])
    weather = config.get("weather_reconstruction") or {}
'''
    new_plan = '''    end_weeks = _planned_end_weeks(config)
    weather = config.get("weather_reconstruction") or {}
'''
    text = _replace_once(text, old_plan, new_plan, "plan_bound")

    old_loop = '''    for season in range(start, end + 1):
        for end_week in range(1, max_week):
'''
    new_loop = '''    for season in range(start, end + 1):
        for end_week in end_weeks:
'''
    text = _replace_once(text, old_loop, new_loop, "plan_loop")

    insertion_anchor = '''def build_request_plan(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build only the quota-bearing CFBD request plan."""
'''
    helper = '''def _planned_end_weeks(config: Mapping[str, Any]) -> range:
    max_week = int(config["max_regular_week_planning_bound"])
    if max_week < 2:
        raise CFBAcquisitionError(f"CFB_ACQUISITION_MAX_WEEK_INVALID:{max_week}")
    return range(1, max_week)


def build_request_plan(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Build only the quota-bearing CFBD request plan."""
'''
    text = _replace_once(text, insertion_anchor, helper, "helper")

    old_payload_loop = '''    for season in range(2015, 2026):
        alias_index = build_team_alias_index(membership_by_season[season])
        id_index = _membership_id_index(membership_by_season[season])
        for end_week in range(1, 20):
'''
    new_payload_loop = '''    for season in range(2015, 2026):
        alias_index = build_team_alias_index(membership_by_season[season])
        id_index = _membership_id_index(membership_by_season[season])
        for end_week in _planned_end_weeks(config):
'''
    text = _replace_once(text, old_payload_loop, new_payload_loop, "payload_loop")

    test_text = '''from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.acquire_cfb_reconstructed_selection import (
    CONFIG,
    _planned_end_weeks,
    build_request_plan,
)


class TestCFBReconstructedWeekBound(unittest.TestCase):
    def test_frozen_bound_matches_planned_and_consumed_end_weeks(self):
        config = json.loads(Path(CONFIG).read_text(encoding="utf-8"))
        self.assertEqual(list(_planned_end_weeks(config)), list(range(1, 16)))
        plan = build_request_plan(config)
        current = [
            row for row in plan
            if row["endpoint"] == "/stats/season/advanced"
            and "endWeek" in row["params"]
        ]
        self.assertEqual(len(current), 11 * 15)
        self.assertEqual({int(row["params"]["endWeek"]) for row in current}, set(range(1, 16)))
        self.assertEqual(len(plan), 200)

    def test_invalid_bound_fails_closed(self):
        with self.assertRaisesRegex(Exception, "CFB_ACQUISITION_MAX_WEEK_INVALID"):
            list(_planned_end_weeks({"max_regular_week_planning_bound": 1}))


if __name__ == "__main__":
    unittest.main()
'''

    TARGET.write_text(text, encoding="utf-8")
    TEST.write_text(test_text, encoding="utf-8")
    print("CFB_RECONSTRUCTED_WEEK_BOUND_REPAIR_APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
