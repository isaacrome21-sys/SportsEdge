import re
from pathlib import Path


CONTEXT_WORKFLOW = Path(".github/workflows/mlb-game-context-refresh.yml")
PROP_WORKFLOW = Path(".github/workflows/mlb-prop-pit-archive.yml")


def _active_crons(text):
    """Real (uncommented) cron entries; comment text never counts."""
    return [m.group(1) for m in re.finditer(r"^\s*-\s*cron:\s*['\"]([^'\"]+)['\"]", text, re.M)]


def _on_keys(text):
    keys, inside = [], False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if re.match(r"^on\s*:", line):
            inside = True
            continue
        if inside:
            if not line.startswith(" "):
                break
            m = re.match(r"^  ([A-Za-z_][\w-]*)\s*:", line)
            if m:
                keys.append(m.group(1))
    return keys


def test_prop_archive_is_manual_only_and_context_clock_unchanged():
    # Grok ruling 2026-10-23 (t234u, DK rendered pages only): the prop PIT archive
    # reaches a DraftKings API URL builder, so it no longer runs on a clock or on
    # push/pull_request; only workflow_dispatch remains.
    context = CONTEXT_WORKFLOW.read_text(encoding="utf-8")
    props = PROP_WORKFLOW.read_text(encoding="utf-8")

    assert _on_keys(props) == ["workflow_dispatch"]
    assert _active_crons(props) == []
    assert "cron" not in props

    crons = _active_crons(context)
    assert "8,23,38,53 15-23 * * *" in crons
    assert "8,23,38,53 0-5 * * *" in crons
    assert "8 6-14 * * *" in crons


def test_context_gap_fill_does_not_expand_high_frequency_hours():
    crons = _active_crons(CONTEXT_WORKFLOW.read_text(encoding="utf-8"))
    assert sum(c.startswith("8,23,38,53") for c in crons) == 2
    assert sum(c.startswith("8 6-14") for c in crons) == 1
