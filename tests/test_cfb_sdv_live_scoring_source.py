import csv
import hashlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sportsedge.sports.cfb import sdv_live_scoring_source as sdv
from sportsedge.sports.cfb.sportsdataverse_history import TeamSnapshot


def team_row(gid, team, *, epa=0.2):
    return {
        "season": "2026", "game_id": str(gid), "pos_team_id": str(team),
        "pos_team": str(team),
        "EPA_rushing_per_play": str(epa),
        "EPA_passing_per_play": str(epa),
        "EPA_explosive_rate": str(epa),
        "EPA_success_rate": str(epa),
        "EPA_standard_down_per_play": str(epa),
        "EPA_success_passing_down_rate": str(epa),
        "avg_field_position": "65.0",
    }


def game(gid, *, week=6, start="2026-10-03T17:00:00Z", completed="TRUE"):
    return {
        "game_id": str(gid), "season": "2026", "week": str(week),
        "season_type": "regular", "fbs_game": "TRUE",
        "completed": completed, "start_date": start,
        "home_id": "1", "away_id": "2",
        "home_team": "Home", "away_team": "Away",
        "neutral_site": "FALSE",
    }


def snapshot(tid, *, year=2025):
    return TeamSnapshot(
        team_id=tid, season=year, through_week=15,
        games_in_sample=12, off_ppa_rush=0.1,
        off_ppa_dropback=0.1, off_success_rate=0.1,
        def_ppa_rush_allowed=0.1, def_ppa_dropback_allowed=0.1,
        def_success_rate_allowed=0.1, standard_down_ppa=0.1,
        passing_down_success_rate=0.1, explosive_rate=0.1,
        net_field_position=-65.0,
    )


class PublicSDVLiveTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 9, 23, tzinfo=timezone.utc)
        prior_game = game(101)
        upcoming = game(102, week=7, start="2026-10-10T01:00:00Z", completed="FALSE")
        rows = [team_row(101, 1), team_row(101, 2)]
        future_rows = [team_row(102, 1, epa=999.0),
                       team_row(102, 2, epa=999.0)]
        self.data = {
            (2026, "cfb_schedules"): [prior_game, upcoming],
            (2026, "adv_team"): [*rows, *future_rows],
            (2026, "adv_situational"): [*rows, *future_rows],
            (2026, "adv_drives"): [*rows, *future_rows],
        }

        for name in sdv.DATASETS:
            self.data[(2025, name)] = []

    def test_prior_week_excludes_current_game_even_if_rows_present(self):
        snaps = sdv._current_snapshots(
            self.data, season=2026, target_week=7, now=self.now
        )
        self.assertEqual(snaps[1].games_in_sample, 1)
        self.assertEqual(snaps[1].through_week, 6)
        self.assertAlmostEqual(snaps[1].off_ppa_rush, 0.2)
        self.assertAlmostEqual(snaps[1].net_field_position, -65.0)

    def test_incomplete_prior_game_fails_closed(self):
        self.data[(2026, "adv_drives")] = [team_row(101, 1)]
        with self.assertRaisesRegex(sdv.SDVLiveError, "PRIOR_GAME_COVERAGE"):
            sdv._current_snapshots(
                self.data, season=2026, target_week=7, now=self.now
            )

    def test_future_dated_completed_game_is_rejected(self):
        self.data[(2026, "cfb_schedules")] = [
            game(101, start="2026-10-10T02:00:00Z")
        ]
        with self.assertRaisesRegex(sdv.SDVLiveError, "AFTER_ASOF"):
            sdv._current_snapshots(
                self.data, season=2026, target_week=7, now=self.now
            )

    def test_live_row_contains_native_dual_snapshots_and_receipt(self):
        self.data[(2025, "adv_team")] = []
        with patch.object(
            sdv, "_read_bundle", return_value=(self.data, {
                "capture_time": self.now.isoformat(),
                "source_contract": sdv.LIVE_CONTRACT,
                "file_sha256": {},
            })
        ), patch.object(sdv, "build_prior_season_fallback_snapshots",
                        return_value=[snapshot(1), snapshot(2)]):
            rows, provenance = sdv.build_live_rows(
                [{"home": "Home", "away": "Away", "quotes": [
                    {"market": "SPREAD", "side": "HOME",
                     "line": -3.5, "american_odds": -110},
                ]}],
                directory="unused", now=self.now,
                expand_compact=lambda r: r,
                normalize_name=lambda s: str(s).strip().lower(),
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["week"], 7)
        self.assertEqual(rows[0]["home_current_metrics"]["through_week"], 6)
        self.assertEqual(rows[0]["home_prior_metrics"]["season"], 2025)
        self.assertEqual(rows[0]["weather"]["fallback"], "TRAINING_MEAN")
        self.assertEqual(provenance["source_contract"], sdv.LIVE_CONTRACT)

    def test_no_current_kickoff_eligible(self):
        self.data[(2026, "cfb_schedules")][1]["start_date"] = "2026-10-09T23:00:00Z"
        with patch.object(sdv, "_read_bundle", return_value=(self.data, {})), \
             patch.object(sdv, "build_prior_season_fallback_snapshots",
                          return_value=[snapshot(1), snapshot(2)]):
            with self.assertRaisesRegex(sdv.SDVLiveError, "NO_RESOLVED_GAMES"):
                sdv.build_live_rows(
                    [{"home": "Home", "away": "Away", "quotes": []}],
                    directory="unused", now=self.now,
                    expand_compact=lambda r: r,
                    normalize_name=lambda s: str(s).strip().lower(),
                )


    def test_started_game_does_not_block_remaining_board(self):
        started = game(103, week=7, start="2026-10-09T22:00:00Z", completed="FALSE")
        started.update(home_team="Started Home", away_team="Started Away")
        self.data[(2026, "cfb_schedules")].append(started)
        with patch.object(sdv, "_read_bundle", return_value=(self.data, {})), \
             patch.object(sdv, "build_prior_season_fallback_snapshots",
                          return_value=[snapshot(1), snapshot(2)]):
            rows, _ = sdv.build_live_rows(
                [{"home": "Started Home", "away": "Started Away", "quotes": []},
                 {"home": "Home", "away": "Away", "quotes": []}],
                directory="unused", now=self.now,
                expand_compact=lambda r: r,
                normalize_name=lambda s: str(s).strip().lower(),
            )
        self.assertEqual([r["game_id"] for r in rows], ["102"])

    def test_unmatched_game_is_skipped_without_blocking_other_games(self):
        self.data[(2026, "cfb_schedules")].append(
            {**game(107, week=7, start="2026-10-10T02:00:00Z", completed="FALSE"),
             "home_team": "Other Host", "away_team": "Other Away"}
        )
        for name in ("adv_team", "adv_situational", "adv_drives", "cfb_schedules"):
            self.data[(2025, name)] = []
        with patch.object(sdv, "_read_bundle", return_value=(self.data, {})), \
             patch.object(sdv, "build_prior_season_fallback_snapshots",
                          return_value=[snapshot(1), snapshot(2)]):
            rows, _ = sdv.build_live_rows(
                [{"home": "Missing", "away": "Unknown", "quotes": []},
                 {"home": "Home", "away": "Away", "quotes": []}],
                directory="unused", now=self.now,
                expand_compact=lambda r: r,
                normalize_name=lambda s: str(s).strip().lower(),
            )
        self.assertEqual([row["game_id"] for row in rows], ["102"])

    def test_one_target_with_missing_native_snapshots_does_not_destroy_valid_slate(self):
        unsupported = {
            **game(108, week=7, start="2026-10-10T02:00:00Z", completed="FALSE"),
            "home_id": "3", "away_id": "4",
            "home_team": "Unsupported Home", "away_team": "Unsupported Away",
        }
        self.data[(2026, "cfb_schedules")].append(unsupported)
        original = {
            "capture_time": self.now.isoformat(),
            "source_contract": sdv.LIVE_CONTRACT,
            "file_sha256": {"immutable": "a" * 64},
        }
        board = [
            {"home": "Unsupported Home", "away": "Unsupported Away", "quotes": []},
            {"home": "Home", "away": "Away", "quotes": []},
        ]
        with patch.object(sdv, "_read_bundle", return_value=(self.data, original)), \
             patch.object(sdv, "build_prior_season_fallback_snapshots",
                          return_value=[snapshot(1), snapshot(2)]):
            rows, receipt = sdv.build_live_rows(
                board, directory="unused", now=self.now,
                expand_compact=lambda r: r,
                normalize_name=lambda s: str(s).strip().lower(),
            )
        self.assertEqual([row["game_id"] for row in rows], ["102"])
        self.assertEqual(receipt["skipped_missing_target_snapshot_count"], 1)
        self.assertEqual(
            receipt["skipped_missing_target_snapshot_games"][0],
            {"game_id": "108", "home_team": "Unsupported Home",
             "away_team": "Unsupported Away",
             "reason": "MISSING_NATIVE_PRIOR_OR_CURRENT_TEAM_SNAPSHOT"},
        )
        self.assertEqual(receipt["file_sha256"], original["file_sha256"])
        self.assertNotIn("skipped_missing_target_snapshot_count", original)

    def test_every_target_without_snapshots_still_fails_closed(self):
        unavailable = {
            **game(109, week=7, start="2026-10-10T02:00:00Z", completed="FALSE"),
            "home_id": "3", "away_id": "4",
            "home_team": "Unsupported Home", "away_team": "Unsupported Away",
        }
        self.data[(2026, "cfb_schedules")].append(unavailable)
        with patch.object(sdv, "_read_bundle", return_value=(self.data, {})), \
             patch.object(sdv, "build_prior_season_fallback_snapshots",
                          return_value=[snapshot(1), snapshot(2)]):
            with self.assertRaisesRegex(sdv.SDVLiveError, "NO_RESOLVED_GAMES"):
                sdv.build_live_rows(
                    [{"home": "Unsupported Home", "away": "Unsupported Away", "quotes": []}],
                    directory="unused", now=self.now,
                    expand_compact=lambda r: r,
                    normalize_name=lambda s: str(s).strip().lower(),
                )

    def test_receipt_cannot_be_reused_for_past_asof(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipts = {}
            for (year, name), filename in sdv.FILES.items():
                fields = (["game_id", "season", "pos_team"] if name != "cfb_schedules"
                          else ["game_id", "season", "week", "home_id", "away_id",
                                "home_team", "away_team", "start_date", "completed",
                                "fbs_game", "season_type", "neutral_site"])
                rec = {key: "123" for key in fields}
                rec["season"] = str(year)
                f = io.StringIO()
                wr = csv.DictWriter(f, fieldnames=fields)
                wr.writeheader()
                wr.writerow(rec)
                raw = f.getvalue().encode("utf-8")
                (root / filename).write_bytes(raw)
                receipts[filename] = {
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "url": "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
                           + name + "/" + filename,
                }
            (root / "receipt.json").write_text(json.dumps({
                "schema": sdv.LIVE_CONTRACT,
                "captured_at": "2026-10-10T03:00:00Z",
                "files": receipts,
            }))
            with self.assertRaisesRegex(sdv.SDVLiveError, "AFTER_ASOF"):
                sdv._read_bundle(root, self.now)

    def test_untrusted_source_receipt_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "receipt.json").write_text(json.dumps({
                "schema": "bad",
                "captured_at": self.now.isoformat(),
            }))
            with self.assertRaisesRegex(sdv.SDVLiveError, "SCHEMA"):
                sdv._read_bundle(root, self.now)


if __name__ == "__main__":
    unittest.main()
