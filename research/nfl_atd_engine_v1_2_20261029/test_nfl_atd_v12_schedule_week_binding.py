"""v1.2 draft only: real-pricer run/board week must match pinned schedule week.

No live records, provider quotes, or counted evidence are used. The fake GitHub
records are created append-only (one commit per path); tests do not mutate
existing records or the frozen v1.1 package.
"""
import hashlib
import json
import platform
import unittest
from datetime import datetime, timezone

import atd_provenance as pv
import fake_github_api as fk
import price_nfl_atd_board_v11 as pricer


class TestScheduleWeekBinding(unittest.TestCase):
    def setUp(self):
        setup, teardown = fk.module_fixtures(guard=True)
        setup()
        self.addCleanup(teardown)
        self.world = fk.synthetic_world().__enter__()
        self.addCleanup(self.world.__exit__)

    def _load(self, *, board_week=8, run_week=8, schedule_week=8, all_unpriced=False,
              board_season=2026, run_season=2026, record_mutator=None,
              mixed_unpriced=False):
        w = self.world
        w.board["week"] = board_week
        w.board["season"] = board_season
        if all_unpriced:
            # Genuine pricer, but no recognized player can receive a price.
            w.board["rows"] = [{"player_id": "ZZ", "player_name": "Nobody",
                                "yes_price": 300}]
        elif mixed_unpriced:
            # Keep the real priced player and add a genuinely unpriced row
            # through the real pricer, so replay remains canonical.
            w.board["rows"].append({"player_id": "ZZ", "player_name": "Nobody",
                                    "yes_price": 300})
        if schedule_week != 8:
            lines = w.schedule.decode().splitlines()
            changed = 0
            for i, line in enumerate(lines):
                if line.startswith("2026_08_"):
                    fields = line.split(",")
                    self.assertEqual(fields[3], "8")
                    fields[3] = str(schedule_week)
                    lines[i] = ",".join(fields)
                    changed += 1
            self.assertEqual(changed, 1)
            w.schedule = ("\n".join(lines) + "\n").encode()

        inputs = w.inputs()
        rows = pricer.replay(
            inputs, now=datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc),
            fetched_at={"stats": "2026-10-25T15:00:00Z",
                        "schedule": "2026-10-25T15:01:00Z"})
        self.assertTrue(rows)
        if all_unpriced:
            self.assertTrue(all(r.get("status") == "UNPRICED" for r in rows))
        else:
            self.assertTrue(any(r.get("status") == "PRICED" for r in rows))
        if mixed_unpriced:
            self.assertTrue(any(r.get("status") == "UNPRICED" for r in rows))
        self.assertTrue(all("week" not in r for r in rows))

        api = fk.FakeGitHub()
        br = pv.RECORDS_BRANCH
        st = fk.publish_data(api, w.stats, "2026-10-25T15:00:00Z",
                             "stats", "csv.gz")
        sc = fk.publish_data(api, w.schedule.decode(),
                             "2026-10-25T15:01:00Z")
        pins = {}
        for name, raw in w.player_data.items():
            digest = hashlib.sha256(raw).hexdigest()
            pins[name] = digest
            api.commit(br, {pv.data_record_path(digest, "csv.gz"): raw},
                       "2026-10-25T15:02:00Z")

        board_raw = inputs["board"]
        board_sha = hashlib.sha256(board_raw).hexdigest()
        api.commit(br, {pv.board_record_path(board_sha, 2026, board_week):
                        board_raw.decode()}, "2026-10-25T16:10:00Z")
        events = {
            sha: next(e for e in api.events
                      if e["after"] == api.file_commits(
                          br, pv.fetch_record_path(sha))[0])
            for sha in (st, sc)
        }
        gid = next((r.get("game_id") for r in rows if r.get("game_id")), None)
        self.assertIsNotNone(gid)
        record = {
            "slate_id": "W1", "captured_at": w.CAP, "season": run_season,
            "week": run_week, "first_kickoff": w.KO,
            "game_teams": {gid: ["KC", "LV"]},
            "schedule_kickoffs": {gid: w.KO},
            "stats_sha256": st, "schedule_sha256": sc,
            "pricer_sha256": pricer.pricer_sha256(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "inputs": {"board": board_sha, "stats": st, "schedule": sc,
                       "player_data": pins},
            "fetch_provenance": {
                "stats": {"event": events[st]},
                "schedule": {"event": events[sc]}},
            "rows": rows,
        }
        if record_mutator is not None:
            record_mutator(record)
        api.commit(br, {pv.run_record_path("W1"):
                        json.dumps(record, sort_keys=True)},
                   "2026-10-25T16:30:00Z")
        return pv.load_slate(api, "W1")

    def test_valid_real_pricer_week_counts(self):
        result = self._load()
        self.assertEqual(result["status"], "COUNTS", result["reasons"])

    def test_all_unpriced_valid_week_cannot_count(self):
        result = self._load(all_unpriced=True)
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_NO_PRICED_ROWS", result["reasons"])

    def test_all_unpriced_wrong_week_cannot_bypass_binding(self):
        result = self._load(board_week=9, run_week=9, schedule_week=8,
                            all_unpriced=True)
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_NO_PRICED_ROWS", result["reasons"])

    def test_numeric_string_board_week_cannot_replay_as_integer_week(self):
        # board_record_path and the real pricer both coerce "8" to int 8;
        # replay equality alone is not proof of exact metadata identity.
        result = self._load(board_week="8", run_week=8, schedule_week=8)
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_BOARD_MISMATCH", result["reasons"])

    def test_matching_board_run_but_wrong_schedule_week_refuses(self):
        result = self._load(board_week=9, run_week=9, schedule_week=8)
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("ROW_KICKOFF_SCHEDULE_MISMATCH", result["reasons"])

    def test_schedule_week_changed_but_board_run_unchanged_refuses(self):
        result = self._load(board_week=8, run_week=8, schedule_week=9)
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("ROW_KICKOFF_SCHEDULE_MISMATCH", result["reasons"])

    def test_run_week_bool_refuses_without_numeric_coercion(self):
        result = self._load(run_week=True)
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_RECORD_MALFORMED", result["reasons"])

    def test_run_week_float_refuses_without_numeric_coercion(self):
        result = self._load(run_week=8.0)
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_RECORD_MALFORMED", result["reasons"])

    def test_run_week_numeric_string_refuses_without_coercion(self):
        result = self._load(run_week="8")
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_RECORD_MALFORMED", result["reasons"])


    def test_run_season_numeric_string_refuses_without_coercion(self):
        result = self._load(run_season="2026")
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_RECORD_MALFORMED", result["reasons"])

    def test_run_season_float_refuses_without_coercion(self):
        result = self._load(run_season=2026.0)
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_RECORD_MALFORMED", result["reasons"])

    def test_run_season_bool_refuses_without_coercion(self):
        result = self._load(run_season=True)
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_RECORD_MALFORMED", result["reasons"])

    def test_board_season_numeric_string_refuses_even_if_pricer_coerces(self):
        result = self._load(board_season="2026")
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_BOARD_MISMATCH", result["reasons"])

    def test_board_season_float_refuses_even_if_pricer_coerces(self):
        result = self._load(board_season=2026.0)
        self.assertEqual(result["status"], "SCREEN")
        self.assertIn("RUN_BOARD_MISMATCH", result["reasons"])

    def test_malformed_run_rows_fail_closed_without_exception(self):
        # The run is immutable on fake GitHub; the malformed JSON is its
        # original pushed content, not an edited branch record.
        for bad_rows in (None, 7, "bad", {}, [None], [7], ["bad"],
                         [{"status": "PRICED", "game_id": "fake",
                           "kickoff": "2026-10-25T17:00:00Z"}, None]):
            with self.subTest(bad_rows=repr(bad_rows)):
                result = self._load(record_mutator=lambda rec, bad=bad_rows:
                                    rec.__setitem__("rows", bad))
                self.assertEqual(result["status"], "SCREEN")
                self.assertIn("RUN_RECORD_MALFORMED", result["reasons"])
                self.assertIn("run_proof", result)

    def test_nonobject_fetch_provenance_entries_fail_closed(self):
        for key in ("stats", "schedule", "freeze", "board"):
            for bad in (7, "bad", [], None):
                with self.subTest(key=key, bad=repr(bad)):
                    result = self._load(record_mutator=lambda rec, k=key, v=bad:
                                        rec["fetch_provenance"].__setitem__(k, v))
                    self.assertEqual(result["status"], "SCREEN")
                    self.assertIn("RUN_RECORD_MALFORMED", result["reasons"])
                    self.assertIn("run_proof", result)

    def test_nonobject_fetch_provenance_root_fails_closed(self):
        for bad in (7, "bad", []):
            with self.subTest(bad=repr(bad)):
                result = self._load(record_mutator=lambda rec, v=bad:
                                    rec.__setitem__("fetch_provenance", v))
                self.assertEqual(result["status"], "SCREEN")
                self.assertIn("RUN_RECORD_MALFORMED", result["reasons"])


    def test_real_pricer_valid_mixed_rows_count_and_tally(self):
        result = self._load(mixed_unpriced=True)
        self.assertEqual(result["status"], "COUNTS", result["reasons"])
        self.assertTrue(result["refusals"])
        self.assertTrue(all(isinstance(key, str) and key for key in result["refusals"]))

    def test_nonstring_unpriced_refusal_reason_fails_closed(self):
        def corrupt(rec, value):
            unpriced = next(row for row in rec["rows"]
                            if row.get("status") == "UNPRICED")
            unpriced["reason"] = value

        for bad_reason in (["NO_PLAYER"], {"code": "NO_PLAYER"}, None,
                           True, 7, "", " "):
            with self.subTest(bad_reason=repr(bad_reason)):
                result = self._load(mixed_unpriced=True,
                                    record_mutator=lambda rec, value=bad_reason:
                                    corrupt(rec, value))
                self.assertEqual(result["status"], "SCREEN")
                self.assertIn("RUN_RECORD_MALFORMED", result["reasons"])
                self.assertIn("run_proof", result)



if __name__ == "__main__":
    unittest.main()
