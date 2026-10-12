"""Tests for scripts/archive_cfbd_advanced.py. No network, no real secrets."""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "archive_cfbd_advanced.py"
SPEC = importlib.util.spec_from_file_location("archive_cfbd_advanced", SCRIPT)
mod = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(mod)

UTC = timezone.utc


def test_self_test_passes():
    assert mod.self_test() == 0


def test_weekly_plan_fits_budget():
    now = datetime(2026, 10, 11, tzinfo=UTC)
    ledger = {"runs": [{"month": "2026-10", "calls_made": 40}]}
    # Steady state: /info + season/advanced + game/advanced + ppa/games.
    mod.check_budget({"limit": 1000, "remaining": 900}, 4, ledger, now,
                     max_calls=60)


def test_plan_exceeding_remaining_fails_closed():
    import pytest

    now = datetime(2026, 10, 11, tzinfo=UTC)
    ledger = {"runs": []}
    with pytest.raises(mod.CFBDBudgetExhausted):
        mod.check_budget({"limit": 1000, "remaining": 3}, 10, ledger, now,
                         max_calls=60)


def test_plan_exceeding_max_calls_fails_closed():
    import pytest

    now = datetime(2026, 10, 11, tzinfo=UTC)
    ledger = {"runs": []}
    with pytest.raises(mod.CFBDBudgetExhausted):
        mod.check_budget({"limit": 1000, "remaining": 1000}, 61, ledger, now,
                         max_calls=60)


def test_backfill_budget_math_documented():
    """The one-time 2022-2025 backfill must fit inside one month's budget."""
    now = datetime(2026, 10, 11, tzinfo=UTC)
    ledger = {"runs": []}
    # 4 seasons x 1 season/advanced + 4 x 15 weeks x 2 (game+ppa).
    backfill_calls = 4 + 4 * 15 * 2
    assert backfill_calls == 124
    mod.check_budget({"limit": 1000, "remaining": 1000}, backfill_calls,
                     ledger, now, max_calls=200)


def test_ledger_month_accounting():
    now = datetime(2026, 10, 11, tzinfo=UTC)
    ledger = {"runs": [
        {"month": "2026-09", "calls_made": 900},
        {"month": "2026-10", "calls_made": 12},
    ]}
    assert mod.ledger_calls_this_month(ledger, now) == 12
    assert mod.month_key(now) == "2026-10"


def test_completed_weeks_are_never_replanned(tmp_path):
    """already_archived: a valid archived file means zero new calls."""
    out_dir = tmp_path / "data"
    path = mod.week_file(out_dir, 2025, 7)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": mod.SCHEMA_VERSION,
        "status": "ARCHIVED",
        "rows": [],
    }))
    assert mod.already_archived(path) is True
    assert mod.already_archived(mod.week_file(out_dir, 2025, 8)) is False


def test_status_out_written(tmp_path, monkeypatch):
    """--status-out writes the run result JSON for the workflow artifact."""
    import io

    status_path = tmp_path / "artifacts" / "status.json"

    class FakeClient:
        calls_made = 3

        def get_info(self):
            return {"tier": "free", "limit": 1000, "remaining": 997}

    monkeypatch.setattr(mod.CFBDClient, "from_env",
                        classmethod(lambda cls: FakeClient()))
    monkeypatch.setattr(mod, "run_weekly",
                        lambda *a, **k: {"mode": "weekly", "archived": []})
    code = mod.main(["--mode", "weekly", "--out-dir", str(tmp_path),
                     "--status-out", str(status_path)])
    assert code == 0
    payload = json.loads(status_path.read_text())
    assert payload["status"] == "ARCHIVED"
    assert payload["calls_made"] == 3
    ledger = json.loads((tmp_path / mod.LEDGER_REL).read_text())
    assert ledger["last_status"] == "ARCHIVED"
