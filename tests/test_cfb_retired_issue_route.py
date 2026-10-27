"""The retired CFB phone issue route must never emit probation stakes."""

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/cfb-lines-issue.yml"


def test_retired_route_issues_only_named_zero_unit_refusal():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "CFB_INCUMBENT_RETIRED_NO_OOS_WIN" in workflow
    assert "PAPER / 0u" in workflow
    assert 'gh issue comment "$ISSUE" --body' in workflow
    assert "CFB_SDV_PROBATION_PLAY" not in workflow
    assert "run_cfb_sdv_card_v2.py" not in workflow


def test_retired_route_cannot_republish_stale_card_or_execute_model():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "artifacts/run_it/cfb_sdv_card.json",
        "--board-json",
        "apply_probation(",
        "python scripts/",
        "card.txt",
    ):
        assert forbidden not in workflow


def test_retired_route_remains_owner_only_and_has_no_counting_side_effects():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "github.actor == github.repository_owner" in workflow
    assert "startsWith(github.event.issue.title, '[CFB LINES]')" in workflow
    assert "contents: read" in workflow
    assert "issues: write" in workflow
    assert "CFB_SDV_" not in workflow
    assert "stake_units" not in workflow


def test_other_sdv_entrypoints_cannot_invoke_or_upload_retired_model():
    workflows = WORKFLOW.parent
    for name in ("cfb-sdv-card.yml", "cfb-saturday-full-fbs-board.yml"):
        content = (workflows / name).read_text(encoding="utf-8")
        assert "CFB_INCUMBENT_RETIRED_NO_OOS_WIN" in content
        assert "PAPER / 0u" in content
        assert "run_cfb_sdv_card_v2.py" not in content
        assert "cfb_sdv_card.json" not in content
        assert "cfb_saturday_full_scored_card.json" not in content
        assert "cfb_saturday_full_bias_audit.json" not in content


def test_public_cfb_capture_remains_research_only_in_other_workflows():
    saturday = (WORKFLOW.parent / "cfb-saturday-full-fbs-board.yml").read_text(encoding="utf-8")
    assert "fetch_cfb_dk_public_full_slate.py" in saturday
    assert "cfb_saturday_full_public_board.json" in saturday
    assert "cfb_saturday_full_capture_audit.json" in saturday
    assert "python scripts/run_cfb_sdv_card_v2.py" not in saturday
