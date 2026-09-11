from __future__ import annotations

import json
from pathlib import Path

from sportsedge.v7_feature_bundle import V7_MODEL_FEATURE_PATHS

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config/v7_feature_backfill_policy_v1.json"


def _policy() -> dict:
    value = json.loads(POLICY.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_policy_covers_exact_v7_feature_surface() -> None:
    policy = _policy()
    rows = policy["features"]
    assert [row["index"] for row in rows] == list(range(1, 47))
    assert [row["path"] for row in rows] == list(V7_MODEL_FEATURE_PATHS)
    assert len({row["path"] for row in rows}) == 46


def test_policy_uses_only_frozen_class_vocabulary() -> None:
    policy = _policy()
    allowed = set(policy["classes"])
    assert allowed == {"BACKFILLABLE", "IF_TIMESTAMPED", "IF_RECOMPUTED", "FORWARD_ONLY"}
    for row in policy["features"]:
        classes = row["classes"]
        assert classes
        assert set(classes) <= allowed


def test_initial_backfill_never_approves_timestamped_or_forward_only_features() -> None:
    policy = _policy()
    by_path = {row["path"]: row for row in policy["features"]}
    approved = policy["initial_backfill_approval"]["approved_paths"]
    for path in approved:
        classes = set(by_path[path]["classes"])
        assert "IF_TIMESTAMPED" not in classes
        assert "FORWARD_ONLY" not in classes
    assert "context.umpire.assignment_known" not in approved
    assert "context.catcher.catcher_known" not in approved


def test_starter_features_remain_blocked_until_source_attested() -> None:
    policy = _policy()
    blocked = set(policy["initial_backfill_approval"]["blocked_until_source_attested"])
    starter = {path for path in V7_MODEL_FEATURE_PATHS if path.startswith("baseball.starter.")}
    assert blocked == starter


def test_roof_is_conditional_not_blanket_backfillable() -> None:
    policy = _policy()
    rows = {row["path"]: row for row in policy["features"]}
    roof = rows["context.weather.roof_closed"]
    assert set(roof["classes"]) == {"BACKFILLABLE", "IF_TIMESTAMPED"}
    assert policy["initial_backfill_approval"]["conditional_roof_path"] == roof["path"]
    assert roof["path"] not in policy["initial_backfill_approval"]["approved_paths"]


def test_no_zero_fill_escape_hatch() -> None:
    policy = _policy()
    rule = policy["rules"]["unapproved_features"].lower()
    assert "drop" in rule
    assert "zero-fill" in rule
