from pathlib import Path


def test_attempt4_dispatch_is_owner_only_and_serialized_across_events():
    workflow = Path(".github/workflows/nfl-v2k-attempt4-development-validation.yml").read_text()
    gate = workflow.split("  evaluate:", 1)[1].split("    needs:", 1)[0]
    assert "github.actor == github.repository_owner && github.ref == 'refs/heads/main' && (" in gate
    assert "group: nfl-v2k-attempt4-${{ github.repository }}" in workflow
    assert "github.event_name }}" not in workflow
    assert "cancel-in-progress: false" in workflow
