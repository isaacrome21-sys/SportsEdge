"""v1.1 (A) current-season refresh tests. RED first.
Run: python3 -m unittest test_nfl_atd_v11_refresh -v
"""
import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import atd_refresh as rf

SCHED_COLS = ["game_id", "season", "game_type", "week", "gameday", "gametime",
              "away_team", "home_team", "result"]
STAT_COLS = ["player_id", "player_display_name", "position_group", "season",
             "week", "season_type", "game_id", "team", "opponent_team",
             "rushing_tds", "receiving_tds", "special_teams_tds"]


def _gz(path, cols, rows):
    with gzip.open(path, "wt", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def _games():
    # Week 6 Sun 12:00 ET, week 6 MNF 20:15 ET, week 7 TNF Thu 20:15 ET.
    return [
        dict(game_id="2026_06_DAL_GB", season=2026, game_type="REG", week=6,
             gameday="2026-10-18", gametime="13:00", away_team="DAL",
             home_team="GB", result="3"),
        dict(game_id="2026_06_BAL_NYJ", season=2026, game_type="REG", week=6,
             gameday="2026-10-19", gametime="20:15", away_team="BAL",
             home_team="NYJ", result="7"),
        dict(game_id="2026_07_MIA_BUF", season=2026, game_type="REG", week=7,
             gameday="2026-10-22", gametime="20:15", away_team="MIA",
             home_team="BUF", result="3"),
    ]


def _stats(game_ids=("2026_06_DAL_GB", "2026_06_BAL_NYJ", "2026_07_MIA_BUF")):
    out = []
    for gid in game_ids:
        wk = int(gid[5:7])
        a, h = gid.split("_")[2:]
        out.append(dict(player_id=f"p_{a}", player_display_name=f"P {a}",
                        position_group="RB", season=2026, week=wk,
                        season_type="REG", game_id=gid, team=a,
                        opponent_team=h, rushing_tds=1, receiving_tds=0,
                        special_teams_tds=0))
    return out


class RefreshCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.stats = self.tmp / "stats_player_week_2026.csv.gz"
        self.sched = self.tmp / "games.csv"
        _gz(self.stats, STAT_COLS, _stats())
        with open(self.sched, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=SCHED_COLS)
            w.writeheader()
            w.writerows(_games())

    def stamp(self, fetched_at="2026-10-25T08:00:00-05:00"):
        """Simulate the download step: sidecar sha256 + clock fetched_at."""
        orig = rf._utcnow
        rf._utcnow = lambda: datetime.fromisoformat(fetched_at).astimezone(timezone.utc)
        try:
            for f in (self.stats, self.sched):
                if f.exists():
                    rf.record_download(f, source="test")
        finally:
            rf._utcnow = orig

    def load(self, captured_at="2026-10-25T11:00:00-05:00",
             fetched_at="2026-10-25T08:00:00-05:00", **kw):
        self.stamp(fetched_at)
        return rf.load_current_season(self.stats, self.sched, season=2026,
                                      captured_at=captured_at, **kw)


class TestPointInTime(RefreshCase):
    def test_only_games_completed_before_capture(self):
        # Sunday capture: both week-6 games done (MNF ended), TNF wk7
        # completed Thursday 20:15 ET + 4h buffer -> included too.
        out = self.load()
        self.assertEqual(sorted({a["game_id"] for a in out["appearances"]}),
                         ["2026_06_BAL_NYJ", "2026_06_DAL_GB", "2026_07_MIA_BUF"])

    def test_game_not_yet_completed_excluded(self):
        # Capture Thursday 7:00 PM CT, before TNF kickoff: TNF rows excluded
        # even though the (later-fetched) file holds them.
        out = self.load(captured_at="2026-10-22T19:00:00-05:00",
                        fetched_at="2026-10-22T18:00:00-05:00")
        gids = {a["game_id"] for a in out["appearances"]}
        self.assertNotIn("2026_07_MIA_BUF", gids)
        self.assertEqual(len(gids), 2)

    def test_in_progress_game_excluded(self):
        # 2h after TNF kickoff, inside the completion buffer.
        out = self.load(captured_at="2026-10-22T21:15:00-05:00",
                        fetched_at="2026-10-22T21:00:00-05:00")
        self.assertNotIn("2026_07_MIA_BUF",
                         {a["game_id"] for a in out["appearances"]})

    def test_appearance_shape_matches_engine(self):
        a = self.load()["appearances"][0]
        self.assertEqual(set(a), {"season", "week", "pid", "position_group",
                                  "team", "opp", "td", "st_td", "game_id"})


class TestFailClosed(RefreshCase):
    def test_missing_file(self):
        self.stats.unlink()
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load()
        self.assertEqual(cm.exception.code, "REFRESH_MISSING")

    def test_corrupt_file(self):
        self.stats.write_bytes(b"not gzip")
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load()
        self.assertEqual(cm.exception.code, "REFRESH_FAILED")

    def test_stale_completed_game_absent(self):
        _gz(self.stats, STAT_COLS, _stats(("2026_06_DAL_GB",)))
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load()
        self.assertEqual(cm.exception.code, "REFRESH_STALE")

    def test_stale_fetch_too_old(self):
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load(fetched_at="2026-10-20T08:00:00-05:00")
        self.assertEqual(cm.exception.code, "REFRESH_STALE")

    def test_fetch_after_capture_fails(self):
        # Audit: fetched_at must be <= captured_at (two-sided window).
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load(captured_at="2026-10-22T19:00:00-05:00",
                      fetched_at="2026-10-23T09:00:00-05:00")
        self.assertEqual(cm.exception.code, "REFRESH_FETCHED_AFTER_CAPTURE")

    def test_unknown_game_id_fails(self):
        rows = _stats() + [dict(_stats()[0], game_id="2026_06_XXX_YYY")]
        _gz(self.stats, STAT_COLS, rows)
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load()
        self.assertEqual(cm.exception.code, "REFRESH_SCHEDULE_MISMATCH")

    def test_missing_timestamps_fail(self):
        for kw in ({"captured_at": None}, {"captured_at": "x"}):
            with self.subTest(**{k: repr(v) for k, v in kw.items()}):
                with self.assertRaises(rf.RefreshFailed) as cm:
                    self.load(**kw)
                self.assertEqual(cm.exception.code, "REFRESH_TIMESTAMP_INVALID")

    def test_no_2025_only_fallback_flag(self):
        self.assertFalse(hasattr(rf, "ALLOW_PRIOR_SEASON_ONLY"))


class TestRunRecord(RefreshCase):
    def setUp(self):
        super().setUp()
        self.stamp()
        self._orig = rf._utcnow
        rf._utcnow = lambda: datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc)

    def tearDown(self):
        rf._utcnow = self._orig

    def test_sha_recorded_before_pricing(self):
        events = []
        rec_path = self.tmp / "run_record.json"

        def pricer(data):
            events.append(("priced", json.loads(rec_path.read_text())))
            return {"rows": []}

        rf.run_slate(stats_path=self.stats, schedule_path=self.sched,
                     season=2026, captured_at="2026-10-25T11:00:00-05:00",
                     kickoff="2026-10-25T12:00:00-05:00",
                     run_record_path=rec_path, base_data=None, pricer=pricer)
        self.assertEqual(len(events), 1)
        rec = events[0][1]
        self.assertEqual(rec["refresh"]["stats_sha256"],
                         hashlib.sha256(self.stats.read_bytes()).hexdigest())
        self.assertEqual(rec["refresh"]["schedule_sha256"],
                         hashlib.sha256(self.sched.read_bytes()).hexdigest())
        self.assertEqual(rec["status"], "REFRESH_OK_PRICING_STARTED")
        final = json.loads(rec_path.read_text())
        self.assertEqual(final["status"], "PRICED")
        self.assertEqual(final["refresh"], rec["refresh"])

    def test_failed_refresh_never_prices(self):
        self.stats.unlink()
        rec_path = self.tmp / "run_record.json"
        called = []
        with self.assertRaises(rf.RefreshFailed):
            rf.run_slate(stats_path=self.stats, schedule_path=self.sched,
                         season=2026, captured_at="2026-10-25T11:00:00-05:00",
                         kickoff="2026-10-25T12:00:00-05:00",
                         run_record_path=rec_path, base_data=None,
                         pricer=lambda d: called.append(1))
        self.assertEqual(called, [])
        rec = json.loads(rec_path.read_text())
        self.assertEqual(rec["status"], "FAILED_CLOSED")
        self.assertEqual(rec["failure"], "REFRESH_MISSING")

    def test_merge_into_engine_data(self):
        base = {"by_player": {}, "by_season": {}, "meta": {}}
        out = self.load()
        merged = rf.merge_into(base, out["appearances"], out["names"])
        self.assertIn("p_DAL", merged["by_player"])
        self.assertEqual(merged["meta"]["p_DAL"]["team"], "DAL")
        self.assertIn(2026, merged["by_season"])


if __name__ == "__main__":
    unittest.main()
