from pathlib import Path


CONTEXT_WORKFLOW = Path(".github/workflows/mlb-game-context-refresh.yml")
PROP_WORKFLOW = Path(".github/workflows/mlb-prop-pit-archive.yml")


def test_prop_archive_hourly_clock_is_covered_by_fresh_context_all_day():
    context = CONTEXT_WORKFLOW.read_text(encoding="utf-8")
    props = PROP_WORKFLOW.read_text(encoding="utf-8")

    assert "- cron: '17 * * * *'" in props
    assert "- cron: '8,23,38,53 15-23 * * *'" in context
    assert "- cron: '8,23,38,53 0-5 * * *'" in context
    assert "- cron: '8 6-14 * * *'" in context

    # The judged forward lane freezes context freshness at <=20 minutes.
    # Every hourly :17 quote capture now has a same-hour :08 context capture.
    assert 17 - 8 <= 20


def test_context_gap_fill_does_not_expand_high_frequency_hours():
    context = CONTEXT_WORKFLOW.read_text(encoding="utf-8")
    assert context.count("8,23,38,53") == 2
    assert context.count("8 6-14") == 1
