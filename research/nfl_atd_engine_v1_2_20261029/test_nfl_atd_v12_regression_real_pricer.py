"""v1.2 REGRESSION — the frozen v1.1 scorer defect, proven fixed end-to-end
on REAL pricer output.

The defect (found by the assembler build, PR #2920 BUILD_RECORD; verified
in the Oct 28 pre-flight): the real pricer's rows
(atd_engine.price_board_row) carry NO "week" key, but v1.1's
score_nfl_atd_forward._games()/score_row() index row["week"], so
score_slate_rows and the scorer CLI's review() raise KeyError: 'week' on
ANY real-priced slate. The frozen v1.1 tests miss it: the scorer/closes
tests run on the fake pricer (whose ledger rows carry "week") and the
replay tests never call score_slate_rows. Adding "week" to the rows is
foreclosed: the loader's replay check requires run rows
canonical-identical to pricer output (an edited row -> RUN_REPLAY_MISMATCH
-> SCREEN).

The v1.2 fix (single change): the scorer takes the week from the slate's
own run-record metadata (record["week"] — the value the records layout
files boards/closes under, as <season>-W<week>) in _rows()/_games();
pricer output rows are byte-identical and untouched.

Part A (self-contained): the family's own synthetic_world priced by the
REAL pricer, published, closed, settled, then scored and reviewed.
Part B (real fixture): the Oct 26, 2026 DAL @ PHI capture assembled
through the merged assembler (research/nfl_atd_assembler_20261028/),
priced by the REAL frozen pricer via pricer.replay, loaded (COUNTS),
scored, reviewed, and run through the scorer CLI in its
ATD_TEST_FAKE_STATE non-binding mode — the exact path that died with
KeyError under v1.1. Part B's settlement values are PLACEHOLDERS chosen
only to exercise the settlement path (all priced players settled 0);
this file asserts nothing about the real game's outcomes. Part B skips
unless its input files exist (paths overridable via the ATD_V12_*
environment variables).

Run: python3 -m pytest test_nfl_atd_v12_regression_real_pricer.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ASSEMBLER_DIR = HERE.parent / "nfl_atd_assembler_20261028"
if ASSEMBLER_DIR.is_dir():
    sys.path.insert(0, str(ASSEMBLER_DIR))

import atd_provenance as pv
import fake_github_api as fk
import price_nfl_atd_board_v11 as pricer
import score_nfl_atd_forward as scorer

NOW = datetime(2026, 11, 30, tzinfo=timezone.utc)


def _fixtures(testcase):
    """Start the fake-replayer + env-guard patches (as the dry run does)."""
    setup, teardown = fk.module_fixtures(guard=True)
    setup()
    testcase.addCleanup(teardown)


class TestSyntheticWorldRealPricer(unittest.TestCase):
    """Part A — synthetic_world + REAL pricer: load, score, review."""

    def setUp(self):
        _fixtures(self)
        self.w = fk.synthetic_world().__enter__()
        self.addCleanup(self.w.__exit__)
        self.rows = pricer.replay(
            self.w.inputs(), now=datetime(2026, 10, 25, 16, 30,
                                          tzinfo=timezone.utc),
            fetched_at={"stats": "2026-10-25T15:00:00+00:00",
                        "schedule": "2026-10-25T15:01:00+00:00"})

    def test_real_pricer_rows_carry_no_week(self):
        # The defect precondition: if this ever fails, the rows changed
        # and the regression's premise must be re-examined.
        self.assertTrue(self.rows)
        for r in self.rows:
            self.assertNotIn("week", r)

    def test_score_and_review_real_priced_slate(self):
        api = fk.FakeGitHub()
        self.w.publish(api, self.rows)
        gid = next(r["game_id"] for r in self.rows
                   if r.get("status") == "PRICED")
        ko = fk.synthetic_world.KO
        fk.publish_close(
            api, gid, ko, "2026-10-25T16:30:00Z",
            [{"player_id": "P1", "yes_price": 200,
              "captured_at": "2026-10-25T16:30:00Z"},
             {"player_id": "P2", "yes_price": 500,
              "captured_at": "2026-10-25T16:30:00Z"}],
            "2026-10-25T16:35:00Z", season=2026, week=8)
        fk.publish_settlements(api, {(gid, "P1"): 1, (gid, "P2"): 0},
                               "2026-10-25T22:00:00Z", week=8)
        st = pv.load_slate(api, "W1")
        self.assertEqual(st["status"], "COUNTS", st["reasons"])

        scored = scorer.score_slate_rows(api, "W1")   # KeyError under v1.1
        by = {r["player_id"]: r for r in scored}
        self.assertEqual(set(by), {"P1", "P2"})
        for r in scored:
            self.assertEqual(r["week"], 8)            # slate metadata week
            self.assertEqual(r["clv_status"], "OK")
            self.assertEqual(r["outcome_status"], "SETTLED")
        self.assertAlmostEqual(by["P1"]["clv"],
                               scorer.implied(200) - scorer.implied(250))
        self.assertAlmostEqual(by["P2"]["clv"],
                               scorer.implied(500) - scorer.implied(400))

        v = scorer.review(["W1"], records_worktree=fk.records_worktree(),
                          api=api)
        self.assertEqual(v["status"], "NO_REVIEW_GATES_NOT_MET")
        self.assertEqual(v["n_weeks"], 1)             # week 8, from metadata
        self.assertEqual(v["n_games"], 1)
        self.assertEqual(v["n_picked"],
                         sum(r["selection"] == "YES" for r in scored))


# ---------------------------------------------------------------------------
# Part B — the real Oct 26, 2026 DAL @ PHI fixture, through the assembler.
# Fixture prep helpers mirror the assembler's dry_run_fixture.py (the
# issue body is only the transport the detailed read was delivered in;
# the assembler itself never parses issue bodies).

def _env_path(var, default):
    return Path(os.environ.get(var, default)).expanduser()


FIXTURE = _env_path("ATD_V12_FIXTURE_TEXT",
                    "~/workspace/sportsedge/mnf_capture_20261026/"
                    "issue_2618_body.txt")
RECORD_ONLY = _env_path("ATD_V12_RECORD_ONLY",
                        "~/workspace/sportsedge/lane_intakes/"
                        "record_only_dal_phi_20261026_1851.json")
PLAYER_DATA = _env_path("ATD_V12_PLAYER_DATA_DIR",
                        "~/workspace/sportsedge/nfl_player_data")
STATS_2026 = _env_path("ATD_V12_STATS_2026",
                       "~/workspace/atd-assembler-20261028/dryrun_inputs/"
                       "stats_player_week_2026.csv.gz")
SCHEDULE = _env_path("ATD_V12_SCHEDULE",
                     "~/workspace/atd-assembler-20261028/dryrun_inputs/"
                     "games.csv")
INPUTS_PRESENT = (ASSEMBLER_DIR.is_dir()
                  and all(p.is_file() for p in
                          (FIXTURE, RECORD_ONLY, STATS_2026, SCHEDULE))
                  and PLAYER_DATA.is_dir())


def _extract_detailed_read(fixture_text):
    m = re.search(r"<!--\n(FULL DRAFTKINGS BOARD.*?)-->", fixture_text, re.S)
    if not m:
        raise AssertionError("fixture: detailed-read block not found")
    return m.group(1)


def _build_close_capture(A, board_capture, record_only):
    note = record_only["prices_summary"]["props_note"]
    pairs = re.findall(r"(Williams|Barkley|Lamb|Pickens|Goedert|Ferguson)"
                       r"\s+([+-]?\d+)", note)
    if len(pairs) != 6:
        raise AssertionError(f"close fixture: expected 6 prices, got {pairs}")
    by_surname = {}
    for row in board_capture.td_rows:
        by_surname.setdefault(row["player_name"].split()[-1],
                              []).append(row["player_name"])
    rows = []
    for surname, price in pairs:
        names = by_surname.get(surname, [])
        if len(names) != 1:
            raise AssertionError(f"close fixture: {surname} not unique")
        rows.append({"player_name": names[0], "yes_price": int(price)})
    start, _, end = record_only["page_server_times"].partition(" to ")
    if "T" not in end:
        end = start.split("T")[0] + "T" + end
    return A.Capture(board_capture.away_name, board_capture.home_name,
                     board_capture.dk_event_id, board_capture.kickoff,
                     A.parse_timestamp(end), rows, "capture_json",
                     "record_only_dal_phi_20261026_1851.json (transcribed)")


@unittest.skipUnless(INPUTS_PRESENT,
                     "Oct 26 fixture inputs not present (see ATD_V12_* "
                     "environment variables)")
class TestDalPhiFixtureRealPricer(unittest.TestCase):
    """Part B — assemble -> real price -> load COUNTS -> score -> review
    -> scorer CLI, on the real Oct 26 capture. NON_COUNTED throughout:
    everything lives in the in-memory FakeGitHub; nothing is pushed."""

    # Fake-state push timeline (UTC), from the assembler's dry run.
    # Kickoff 2026-10-27T00:15:00Z; board capture 2026-10-26T22:01:00Z;
    # close capture 2026-10-27T00:09:08Z.
    T_DATA = "2026-10-26T20:00:00Z"
    T_BOARD = "2026-10-26T22:30:00Z"
    T_RUN = "2026-10-26T23:00:00Z"
    T_CLOSE = "2026-10-27T00:10:00Z"     # <= kickoff + 15 min (frozen grace)
    T_SETTLE = "2026-10-27T12:00:00Z"    # > kickoff + 4 h (frozen buffer)
    RUN_NOW = datetime(2026, 10, 26, 23, 0, tzinfo=timezone.utc)

    @classmethod
    def setUpClass(cls):
        import atd_assembler as A
        cls.A = A
        _setup, _teardown = fk.module_fixtures(guard=True)
        _setup()
        cls.addClassCleanup(_teardown)

        # --- assemble board + close through the merged assembler --------
        read_text = _extract_detailed_read(FIXTURE.read_text())
        board_capture = A.parse_detailed_read_text(read_text,
                                                   "fixture detailed read")
        schedule_rows = A.load_schedule_rows(SCHEDULE.read_text())
        base_index, _pin_shas = A.load_pinned_index(str(PLAYER_DATA))
        board = A.assemble_board(board_capture, base_index, schedule_rows,
                                 stats_path=str(STATS_2026))
        cls.board = board
        record_only = json.loads(RECORD_ONLY.read_text())
        close_capture = _build_close_capture(A, board_capture, record_only)
        cls.close = A.assemble_close([board_capture, close_capture],
                                     base_index, schedule_rows,
                                     stats_path=str(STATS_2026))

        # --- publish into the fake records branch -----------------------
        import atd_engine as eng
        api = fk.FakeGitHub()
        cls.api = api
        br = pv.RECORDS_BRANCH
        stats_bytes = STATS_2026.read_bytes()
        schedule_bytes = SCHEDULE.read_bytes()
        stats_sha = fk.publish_data(api, stats_bytes, cls.T_DATA,
                                    name="stats", ext="csv.gz")
        sched_sha = fk.publish_data(api, schedule_bytes, cls.T_DATA,
                                    name="schedule", ext="csv")
        pins = eng.check_data_pins(PLAYER_DATA)
        player_bytes = {}
        for fname in A.REQUIRED_FILES:
            player_bytes[fname] = (PLAYER_DATA / fname).read_bytes()
            fk.publish_data(api, player_bytes[fname], cls.T_DATA,
                            name=fname.rsplit(".", 2)[0], ext="csv.gz")
        api.commit(br, {board["path"]: board["bytes"].decode()}, cls.T_BOARD)

        # --- price with the REAL pricer (the review's own entry point) --
        rows = pricer.replay(
            {"board": board["bytes"], "stats": stats_bytes,
             "schedule": schedule_bytes, "player_data": player_bytes},
            now=cls.RUN_NOW,
            fetched_at={"stats": cls.T_DATA, "schedule": cls.T_DATA})
        cls.rows = rows

        def fetch_event(sha):
            return next(e for e in api.events
                        if e["after"] == api.file_commits(
                            br, pv.fetch_record_path(sha))[0])

        import platform as _platform
        gid = board["report"]["nflverse_game_id"]
        cls.gid = gid
        rec = {
            "slate_id": board["body"]["slate_id"],
            "captured_at": board["body"]["captured_at"],
            "season": board["body"]["season"], "week": board["body"]["week"],
            "python_version": _platform.python_version(),
            "platform": _platform.platform(),
            "first_kickoff": board["body"]["kickoff"],
            "game_teams": {gid: board["body"]["game_teams"]},
            "schedule_kickoffs": {gid: board["body"]["kickoff"]},
            "stats_sha256": stats_sha, "schedule_sha256": sched_sha,
            "pricer_sha256": pricer.pricer_sha256(),
            "inputs": {"board": board["sha256"], "stats": stats_sha,
                       "schedule": sched_sha, "player_data": pins},
            "fetch_provenance": {"stats": {"event": fetch_event(stats_sha)},
                                 "schedule": {"event": fetch_event(sched_sha)}},
            "rows": rows,
        }
        cls.slate_id = rec["slate_id"]
        api.commit(br, {pv.run_record_path(cls.slate_id):
                        json.dumps(rec, sort_keys=True)}, cls.T_RUN)
        api.commit(br, {cls.close["path"]: cls.close["bytes"].decode()},
                   cls.T_CLOSE)
        # PLACEHOLDER settlements (all 0): exercise the settlement path
        # only; NOT the real game's outcomes (see module docstring).
        priced_pids = [r["player_id"] for r in rows
                       if r.get("status") == "PRICED"]
        fk.publish_settlements(api, {(gid, p): 0 for p in priced_pids},
                               cls.T_SETTLE, week=board["body"]["week"])

    def test_assembly_matches_dry_run_record(self):
        rep = self.board["report"]
        self.assertEqual(rep["rows_extracted"], 29)
        self.assertEqual(len(rep["resolved"]), 23)
        self.assertEqual({(r["player_name"], r["reason"])
                          for r in rep["refusals"]},
                         {("Eli Stowers", "NO_MATCH"),
                          ("Camden Brown", "NO_MATCH"),
                          ("Elijah Mitchell", "TEAM_MISMATCH")})
        self.assertEqual(len(self.close["body"]["captures"]), 6)

    def test_real_pricer_rows_carry_no_week(self):
        self.assertEqual(len(self.rows), 23)
        for r in self.rows:
            self.assertNotIn("week", r)
        self.assertEqual(
            sum(r.get("selection") == "YES" for r in self.rows), 11)
        self.assertEqual(
            sum(r.get("selection") == "PASS" for r in self.rows), 11)

    def test_load_counts_and_score(self):
        st = pv.load_slate(self.api, self.slate_id)
        self.assertEqual(st["status"], "COUNTS", st["reasons"])
        scored = scorer.score_slate_rows(self.api, self.slate_id)
        # ^ KeyError: 'week' under v1.1 — the regression itself.
        self.assertEqual(len(scored), 22)             # 11 YES + 11 PASS
        for r in scored:
            self.assertEqual(r["week"], 7)            # 2026-W7, from the
            #                                           run record's metadata
            self.assertEqual(r["outcome_status"], "SETTLED")
        closed = {c["player_id"] for c in self.close["body"]["captures"]}
        self.assertEqual(len(closed), 6)
        for r in scored:
            if r["player_id"] in closed:
                self.assertEqual(r["clv_status"], "OK", r)
                self.assertIsNotNone(r["clv"])
            else:
                self.assertEqual(r["clv_status"], "CLV_MISSING", r)
                self.assertEqual(r["clv_reason"], "NO_CLOSE_ROW", r)

    def test_review_completes(self):
        orig = scorer._utcnow
        scorer._utcnow = lambda: NOW
        try:
            v = scorer.review([self.slate_id],
                              records_worktree=fk.records_worktree(),
                              api=self.api)
        finally:
            scorer._utcnow = orig
        self.assertEqual(v["status"], "NO_REVIEW_GATES_NOT_MET")
        self.assertEqual(v["n_weeks"], 1)             # week 7 slate counts
        self.assertEqual(v["n_games"], 1)

    def test_scorer_cli_fake_state_mode(self):
        # The exact CLI path that died with KeyError under v1.1: it must
        # now run the review and emit the gates-not-met JSON line.
        work = Path(tempfile.mkdtemp(prefix="atd_v12_cli_"))
        # The fake-state file written below is ~136 MB; without cleanup
        # this dir leaked into /tmp on every run (it filled /tmp during
        # the v1.2 draft review). Test-side teardown only.
        self.addCleanup(shutil.rmtree, work, True)
        state = work / "fake_state.json"
        state.write_text(self.api.to_json())
        wt = fk.records_worktree()
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        env["PYTHONPATH"] = str(HERE)
        env["ATD_TEST_FAKE_STATE"] = str(state)
        env["ATD_TEST_NOW"] = NOW.isoformat()
        proc = subprocess.run(
            [sys.executable, str(HERE / "score_nfl_atd_forward.py"),
             "--records-worktree", str(wt), self.slate_id],
            cwd=str(work), env=env, capture_output=True, text=True,
            timeout=900)
        self.assertEqual(proc.returncode, 2, proc.stderr[-2000:])
        emit = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(emit["refusal"], "NO_REVIEW_GATES_NOT_MET")
        self.assertFalse(emit["binding"])


if __name__ == "__main__":
    unittest.main()
