"""A delayed StatsAPI reply cannot inherit a pre-request source timestamp."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

from scripts import refresh_mlb_game_context as refresh


def test_slow_schedule_and_game_context_use_individual_postfetch_clocks(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    initial = datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 10, 27, 0, 0, tzinfo=timezone.utc)
    seen = []

    class TestClock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return initial if not seen else finished

    # Exact signatures make any stale `now=initial` injection an immediate
    # failing regression. A slow network response's time is owned by the
    # fetcher *after* the bytes arrive, independently for each request.
    def schedule(date_iso):
        seen.append(("schedule", date_iso))
        return [SimpleNamespace(game_pk=12345)]

    def context(game_pk):
        seen.append(("context", game_pk))
        return SimpleNamespace(
            game_id="12345", retrieved_at=finished.isoformat(),
            source="MLB_STATSAPI", source_states={
                "weather_first_pitch_forecast": "ABSENT",
                "confirmed_lineup": "ABSENT", "plate_umpire": "ABSENT",
                "starting_catcher": "ABSENT",
            },
            weather={}, umpire={}, lineups=(), catchers=(),
        )

    monkeypatch.setattr(refresh, "datetime", TestClock)
    monkeypatch.setattr(refresh, "fetch_schedule", schedule)
    monkeypatch.setattr(refresh, "fetch_game_context", context)

    assert refresh.main() == 0
    slate = tmp_path / "artifacts" / "mlb-context" / "2026-10-26"
    receipt = json.loads((slate / "game_12345.json").read_text())
    manifest = json.loads((slate / "manifest.json").read_text())
    assert seen == [("schedule", "2026-10-26"), ("context", 12345)]
    assert receipt["retrieved_at"] == finished.isoformat()
    assert manifest["started_at"] == initial.isoformat()
    assert manifest["retrieved_at"] == finished.isoformat()
    assert manifest["status"] == "PASS"
