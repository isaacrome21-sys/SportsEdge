from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).parents[1] / "scripts" / "build_mlb_replay_archive.py"
spec = importlib.util.spec_from_file_location("build_mlb_replay_archive", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class ReplayArchiveV8Tests(unittest.TestCase):
    def test_plan_groups_shared_first_pitch_targets(self):
        games = [
            {"game_pk":"1","commence_time_utc":"2026-07-01T23:10:00Z","home_team":"A","away_team":"B"},
            {"game_pk":"2","commence_time_utc":"2026-07-01T23:10:00Z","home_team":"C","away_team":"D"},
            {"game_pk":"3","commence_time_utc":"2026-07-02T00:10:00Z","home_team":"E","away_team":"F"},
        ]
        plan = mod.build_plan(games, ["T-90","CLOSE_PRESTART"], market_count=3, region_count=1)
        self.assertEqual(plan["game_count"], 3)
        self.assertEqual(plan["unique_snapshot_requests"], 4)
        self.assertEqual(plan["estimated_provider_credits"], 120)

    def test_close_target_is_strictly_prestart(self):
        commence = datetime(2026, 7, 1, 23, 10, tzinfo=timezone.utc)
        close = mod.checkpoint_target(commence, "CLOSE_PRESTART")
        self.assertEqual((commence-close).total_seconds(), 1)

    def test_match_requires_team_identity_and_near_time(self):
        event={"home_team":"Chicago Cubs","away_team":"St. Louis Cardinals","commence_time":"2026-07-01T23:10:00Z"}
        wanted=[{"game_pk":"9","home_team":"Chicago Cubs","away_team":"St Louis Cardinals","commence_time_utc":"2026-07-01T23:10:00Z"}]
        self.assertEqual(mod._match_game(event,wanted)["game_pk"],"9")


if __name__ == "__main__": unittest.main()
