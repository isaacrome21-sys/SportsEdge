#!/usr/bin/env python3
"""Tests for the NFL anytime-TD v1.1 capture -> records assembler.

Self-contained: synthetic pinned player-data files, a synthetic schedule,
and synthetic captures. The frozen-family acceptance proof lives in
dry_run_fixture.py (it needs the frozen tree, which is branch-only and
absent on main by design).
"""
import gzip
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atd_assembler as A

# One game: Dallas Cowboys @ Philadelphia Eagles, Mon Oct 26 2026,
# 20:15 ET = 19:15 CT = 2026-10-27T00:15:00Z, nflverse 2026_07_DAL_PHI.
SCHEDULE_CSV = """game_id,season,game_type,week,gameday,weekday,gametime,away_team,home_team,result
2026_06_DAL_NYG,2026,REG,6,2026-10-18,Sunday,13:00,DAL,NYG,7
2026_07_DAL_PHI,2026,REG,7,2026-10-26,Monday,20:15,DAL,PHI,
"""

STATS_HEADER = ("player_id,player_display_name,season,season_type,week,"
                "recent_team,game_id")

# Base snapshot: Williams last seen for DEN (2025); Barkley/Lamb for their
# 2026 teams; a Giant whose normalized name collides with a Cowboy.
BASE_ROWS = [
    ("00-001", "Javonte Williams", 2025, 10, "DEN", "2025_10_DEN_KC"),
    ("00-002", "Saquon Barkley", 2025, 10, "PHI", "2025_10_PHI_DAL"),
    ("00-003", "CeeDee Lamb", 2025, 10, "DAL", "2025_10_PHI_DAL"),
    ("00-004", "Chris Collide", 2025, 10, "DAL", "2025_10_PHI_DAL"),
    ("00-005", "Chris Collide", 2025, 10, "PHI", "2025_10_PHI_DAL"),
    ("00-006", "Third Team", 2025, 10, "NYG", "2025_10_NYG_DAL"),
]

# Current-season stats: Williams now DAL (week 6, completed game);
# a rookie who exists only here.
STATS_ROWS = [
    ("00-001", "Javonte Williams", 2026, 6, "DAL", "2026_06_DAL_NYG"),
    ("00-007", "Rookie One", 2026, 6, "PHI", "2026_06_DAL_NYG"),
]


def _write_stats_gz(path, rows):
    lines = [STATS_HEADER] + [
        f"{pid},{name},{season},REG,{week},{team},{gid}"
        for pid, name, season, week, team, gid in rows]
    with gzip.open(path, "wt", newline="") as fh:
        fh.write("\n".join(lines) + "\n")


def make_data_dir(root, rows=BASE_ROWS):
    """Eight tiny pinned files; only ps_2018 carries rows. Returns pins."""
    root = Path(root)
    pins = {}
    for i, fname in enumerate(A.REQUIRED_FILES):
        _write_stats_gz(root / fname, rows if i == 0 else [])
        pins[fname] = hashlib.sha256((root / fname).read_bytes()).hexdigest()
    return pins


def capture_json(**kw):
    base = {
        "game": "Dallas Cowboys @ Philadelphia Eagles",
        "dk_event_id": 34118071,
        "kickoff": "2026-10-26T19:15:00-05:00",
        "captured_at": "2026-10-26T18:15:00-05:00",  # T-60m: inside T-1H band
        "td_scorers": [
            {"player_name": "Javonte Williams", "yes_price": -160},
            {"player_name": "Saquon Barkley", "yes_price": 115},
            {"player_name": "CeeDee Lamb", "yes_price": 135},
            {"player_name": "DAL Cowboys D/ST", "yes_price": 450},
            {"player_name": "No Touchdown Scorer", "yes_price": None},
            {"player_name": "Priceless Player", "yes_price": None},
        ],
    }
    base.update(kw)
    return base


DETAILED_TEXT = """FULL DRAFTKINGS BOARD — RENDERED PAGES ONLY, SIGNED OUT

Event: Dallas Cowboys @ Philadelphia Eagles, DK event 34118071
Capture window: Monday, October 26, 2026, 4:57 PM–5:01 PM CT (DraftKings server time shown on page: 4:57:20 PM to 5:01:40 PM). Kickoff: Today 7:15 PM CT, shown as "Starts In: 02:17:29" at 4:57 PM.

3) TOUCHDOWN SCORERS — "TD Scorer" table, TD Scorers tab at 4:59 PM. Columns in order: Anytime TD Scorer / First TD Scorer / 2+ TDs.
Javonte Williams −160 / +400 / +340; DAL Cowboys D/ST +450 / +1700 / +1400; No Touchdown Scorer +10000 (shown in the First TD Scorer column only; the other two columns were locked for this row)
Drift note: an earlier Popular-tab read had Williams −165. The table above is the 4:59 PM TD Scorers tab snapshot, not a blend.
"""


class AssemblerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.data_dir = root / "data"
        self.data_dir.mkdir()
        self.pins = make_data_dir(self.data_dir)
        self.schedule = A.load_schedule_rows(SCHEDULE_CSV)
        self.stats_path = root / "stats_player_week_2026.csv.gz"
        _write_stats_gz(self.stats_path, STATS_ROWS)
        self.index, _ = A.load_pinned_index(self.data_dir, pins=self.pins)

    def capture(self, **kw):
        path = Path(self.tmp.name) / "cap.json"
        path.write_text(json.dumps(capture_json(**kw)))
        return A.load_capture_json(path)


class TestBoard(AssemblerCase):
    def test_board_happy_path_with_stats_merge(self):
        res = A.assemble_board(self.capture(), self.index, self.schedule,
                               stats_path=self.stats_path)
        body = res["body"]
        self.assertEqual(body["season"], 2026)
        self.assertEqual(body["week"], 7)
        self.assertEqual(body["game_id"], "34118071")
        self.assertEqual(body["game_teams"], ["DAL", "PHI"])
        self.assertEqual(body["kickoff"], "2026-10-27T00:15:00Z")
        self.assertEqual(body["captured_at"], "2026-10-26T23:15:00Z")
        self.assertEqual(body["slate_id"], "ASM-2026W07-DAL-PHI")
        by_name = {r["player_name"]: r for r in body["rows"]}
        # Williams resolves ONLY because the point-in-time merge moved
        # his latest team DEN -> DAL.
        self.assertEqual(by_name["Javonte Williams"]["player_id"], "00-001")
        self.assertEqual(by_name["Saquon Barkley"]["player_id"], "00-002")
        self.assertEqual(by_name["CeeDee Lamb"]["yes_price"], 135)
        self.assertEqual(res["report"]["rows_extracted"], 6)
        codes = {e["code"] for e in res["report"]["exclusions"]}
        self.assertEqual(codes, {"NOT_A_PLAYER_ROW", "NO_ANYTIME_PRICE"})
        self.assertEqual(res["report"]["warnings"], [])
        self.assertTrue(res["path"].startswith("nfl_atd_v1_1/boards/2026-W7/"))
        self.assertEqual(hashlib.sha256(res["bytes"]).hexdigest(),
                         res["sha256"])
        prov = body["assembler_provenance"]
        self.assertEqual(prov["assembler_version"], A.ASSEMBLER_VERSION)
        self.assertEqual(prov["nflverse_game_id"], "2026_07_DAL_PHI")

    def test_board_without_stats_merge_refuses_by_name(self):
        # Without the current-season merge Williams' latest team is DEN:
        # named TEAM_MISMATCH refusal, kept out of the board, not guessed.
        res = A.assemble_board(self.capture(), self.index, self.schedule)
        refusals = {r["player_name"]: r for r in res["report"]["refusals"]}
        self.assertEqual(refusals["Javonte Williams"]["code"], "NAME_UNRESOLVED")
        self.assertEqual(refusals["Javonte Williams"]["reason"], "TEAM_MISMATCH")
        names = {r["player_name"] for r in res["body"]["rows"]}
        self.assertNotIn("Javonte Williams", names)

    def test_unresolved_no_match_and_ambiguous(self):
        cap = self.capture(td_scorers=[
            {"player_name": "Ghost Player", "yes_price": 500},
            {"player_name": "Chris Collide", "yes_price": 500},
            {"player_name": "Third Team", "yes_price": 500},
            {"player_name": "Saquon Barkley", "yes_price": 115},
        ])
        res = A.assemble_board(cap, self.index, self.schedule,
                               stats_path=self.stats_path)
        reasons = {r["player_name"]: r["reason"]
                   for r in res["report"]["refusals"]}
        self.assertEqual(reasons, {"Ghost Player": "NO_MATCH",
                                   "Chris Collide": "AMBIGUOUS",
                                   "Third Team": "TEAM_MISMATCH"})
        self.assertEqual([r["player_name"] for r in res["body"]["rows"]],
                         ["Saquon Barkley"])

    def test_rookie_resolves_only_with_stats_merge(self):
        cap = self.capture(td_scorers=[
            {"player_name": "Rookie One", "yes_price": 900},
            {"player_name": "Saquon Barkley", "yes_price": 115}])
        bare = A.assemble_board(cap, self.index, self.schedule)
        self.assertEqual(bare["report"]["refusals"][0]["reason"], "NO_MATCH")
        merged = A.assemble_board(cap, self.index, self.schedule,
                                  stats_path=self.stats_path)
        self.assertEqual({r["player_name"] for r in merged["body"]["rows"]},
                         {"Rookie One", "Saquon Barkley"})

    def test_board_refuses_close_window_capture(self):
        cap = self.capture(captured_at="2026-10-26T19:05:00-05:00")  # T-10m
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.assemble_board(cap, self.index, self.schedule,
                             stats_path=self.stats_path)
        self.assertEqual(ctx.exception.code, "CAPTURE_IN_CLOSE_WINDOW")

    def test_board_refuses_capture_at_or_after_kickoff(self):
        cap = self.capture(captured_at="2026-10-26T19:15:00-05:00")
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.assemble_board(cap, self.index, self.schedule)
        self.assertEqual(ctx.exception.code, "CAPTURED_AFTER_KICKOFF")

    def test_board_outside_t1h_band_warns_but_assembles(self):
        cap = self.capture(captured_at="2026-10-26T17:01:00-05:00")  # T-134m
        res = A.assemble_board(cap, self.index, self.schedule,
                               stats_path=self.stats_path)
        self.assertEqual([w["code"] for w in res["report"]["warnings"]],
                         ["CAPTURE_OUTSIDE_T1H_BAND"])

    def test_kickoff_schedule_mismatch_refused(self):
        cap = self.capture(kickoff="2026-10-26T19:25:00-05:00")  # 10m off
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.assemble_board(cap, self.index, self.schedule)
        self.assertEqual(ctx.exception.code, "KICKOFF_SCHEDULE_MISMATCH")

    def test_all_rows_refused_refuses_board(self):
        cap = self.capture(td_scorers=[
            {"player_name": "Ghost Player", "yes_price": 500}])
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.assemble_board(cap, self.index, self.schedule)
        self.assertEqual(ctx.exception.code, "NO_RESOLVED_ROWS")

    def test_invalid_price_is_a_named_row_refusal(self):
        cap = self.capture(td_scorers=[
            {"player_name": "Saquon Barkley", "yes_price": 50},
            {"player_name": "CeeDee Lamb", "yes_price": 135}])
        res = A.assemble_board(cap, self.index, self.schedule)
        self.assertEqual(res["report"]["refusals"][0]["code"], "PRICE_INVALID")


class TestClose(AssemblerCase):
    def test_close_picks_latest_before_kickoff(self):
        early = self.capture(captured_at="2026-10-26T18:30:00-05:00",
                             td_scorers=[{"player_name": "Saquon Barkley",
                                          "yes_price": 120}])
        late = self.capture(captured_at="2026-10-26T19:09:00-05:00",
                            td_scorers=[{"player_name": "Saquon Barkley",
                                         "yes_price": 110}])
        res = A.assemble_close([early, late], self.index, self.schedule)
        body = res["body"]
        self.assertEqual(body["game_id"], "2026_07_DAL_PHI")
        self.assertEqual(body["captured_at"], "2026-10-27T00:09:00Z")
        self.assertEqual(body["captures"], [{
            "player_id": "00-002", "yes_price": 110,
            "captured_at": "2026-10-27T00:09:00Z"}])
        self.assertTrue(res["path"].startswith("nfl_atd_v1_1/closes/2026-W7/"))

    def test_close_stale_refused(self):
        old = self.capture(captured_at="2026-10-26T18:14:00-05:00")  # T-61m
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.assemble_close([old], self.index, self.schedule)
        self.assertEqual(ctx.exception.code, "CLOSE_STALE")

    def test_close_exactly_sixty_minutes_is_not_stale(self):
        edge = self.capture(captured_at="2026-10-26T18:15:00-05:00")  # T-60m
        res = A.assemble_close([edge], self.index, self.schedule)
        self.assertEqual(res["report"]["minutes_before_kickoff"], 60.0)

    def test_close_missing_capture_refused(self):
        after = self.capture(captured_at="2026-10-26T19:20:00-05:00")
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.assemble_close([after], self.index, self.schedule)
        self.assertEqual(ctx.exception.code, "CLOSE_NO_CAPTURE_BEFORE_KICKOFF")
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.assemble_close([], self.index, self.schedule)
        self.assertEqual(ctx.exception.code, "CLOSE_NO_CAPTURE")


class TestInputs(AssemblerCase):
    def test_missing_capture_file_refused(self):
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.load_capture(Path(self.tmp.name) / "nope.json")
        self.assertEqual(ctx.exception.code, "CAPTURE_MISSING")

    def test_pin_mismatch_refused(self):
        bad = dict(self.pins)
        bad["ps_2018.csv.gz"] = "0" * 64
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.load_pinned_index(self.data_dir, pins=bad)
        self.assertEqual(ctx.exception.code, "PLAYER_DATA_PIN_MISMATCH")

    def test_default_pins_are_the_frozen_eight(self):
        self.assertEqual(set(A.PINNED_SHA256), set(A.REQUIRED_FILES))
        self.assertEqual(
            A.PINNED_SHA256["sp_2025.csv.gz"],
            "c7401e321bdb369443f3280b9acd74ba6e16d82e710383bf1c01acabfebeac0b")

    def test_detailed_read_text_parsing(self):
        cap = A.parse_detailed_read_text(DETAILED_TEXT, "mini.txt")
        self.assertEqual((cap.away_name, cap.home_name),
                         ("Dallas Cowboys", "Philadelphia Eagles"))
        self.assertEqual(cap.dk_event_id, 34118071)
        self.assertEqual(A.zulu(cap.captured_at), "2026-10-26T22:01:00Z")
        self.assertEqual(A.zulu(cap.kickoff), "2026-10-27T00:15:00Z")
        rows = {r["player_name"]: r["yes_price"] for r in cap.td_rows}
        self.assertEqual(rows["Javonte Williams"], "-160")  # not the -165 drift
        self.assertEqual(rows["DAL Cowboys D/ST"], "+450")
        self.assertIsNone(rows["No Touchdown Scorer"])

    def test_detailed_read_without_designation_refused(self):
        text = DETAILED_TEXT.replace(
            "The table above is the 4:59 PM TD Scorers tab snapshot, "
            "not a blend.", "Prices moved during the window.")
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.parse_detailed_read_text(text, "mini.txt")
        self.assertEqual(ctx.exception.code, "TEXT_SNAPSHOT_NOT_DESIGNATED")

    def test_detailed_read_without_td_section_refused(self):
        text = DETAILED_TEXT.replace("TOUCHDOWN SCORERS", "SCORING PLAYS")
        with self.assertRaises(A.AssemblyRefusal) as ctx:
            A.parse_detailed_read_text(text, "mini.txt")
        self.assertEqual(ctx.exception.code, "CAPTURE_TD_TABLE_MISSING")

    def test_team_column_fallback(self):
        # Current nflverse extracts carry `team`, not `recent_team`; the
        # frozen reader falls back recent_team -> team, and so must we.
        root = Path(self.tmp.name) / "data_team_only"
        root.mkdir()
        pins = {}
        for i, fname in enumerate(A.REQUIRED_FILES):
            lines = ["player_id,player_display_name,season,season_type,"
                     "week,team,game_id"]
            if i == 0:
                lines += ["00-002,Saquon Barkley,2025,REG,10,PHI,"
                          "2025_10_PHI_DAL"]
            with gzip.open(root / fname, "wt", newline="") as fh:
                fh.write("\n".join(lines) + "\n")
            pins[fname] = hashlib.sha256((root / fname).read_bytes()).hexdigest()
        index, _ = A.load_pinned_index(root, pins=pins)
        pid, reason = index.resolve("Saquon Barkley", ["DAL", "PHI"])
        self.assertEqual((pid, reason), ("00-002", None))

    def test_house_timestamp_format(self):
        dt = A.parse_timestamp("2026-10-26 6:15 PM CT")
        self.assertEqual(A.zulu(dt), "2026-10-26T23:15:00Z")
        with self.assertRaises(A.AssemblyRefusal):
            A.parse_timestamp("2026-10-26 18:15")  # naive refused

    def test_cli_board_end_to_end(self):
        cap_path = Path(self.tmp.name) / "cap.json"
        cap_path.write_text(json.dumps(capture_json()))
        sched_path = Path(self.tmp.name) / "games.csv"
        sched_path.write_text(SCHEDULE_CSV)
        stats = Path(self.tmp.name) / "stats.csv.gz"
        _write_stats_gz(stats, STATS_ROWS)
        out = io.StringIO()
        old_pins = A.PINNED_SHA256
        A.PINNED_SHA256 = self.pins
        try:
            import contextlib
            with contextlib.redirect_stdout(out):
                rc = A.main(["board", "--capture", str(cap_path),
                             "--player-data-dir", str(self.data_dir),
                             "--schedule", str(sched_path),
                             "--stats", str(stats),
                             "--out-dir", str(Path(self.tmp.name) / "records")])
        finally:
            A.PINNED_SHA256 = old_pins
        self.assertEqual(rc, 0)
        report = json.loads(out.getvalue())
        written = Path(report["written_to"])
        self.assertTrue(written.is_file())
        body = json.loads(written.read_text())
        self.assertEqual(body["slate_id"], "ASM-2026W07-DAL-PHI")


if __name__ == "__main__":
    unittest.main()
