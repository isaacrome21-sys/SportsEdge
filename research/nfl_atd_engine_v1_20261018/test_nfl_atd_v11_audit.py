"""v1.1 audit fixes (NOT CLEARED on b2358d86). RED first.
Run: python3 -m unittest test_nfl_atd_v11_audit -v
"""
import csv
import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import atd_refresh as rf
import score_nfl_atd_forward as sc
from test_nfl_atd_v11_refresh import SCHED_COLS, STAT_COLS, _games, _gz, _stats
from test_nfl_atd_v11_scorer import _ledger, _review, records_wt

CAP = "2026-10-25T11:00:00-05:00"


def at(iso):
    return lambda: datetime.fromisoformat(iso).astimezone(timezone.utc)


class Base(unittest.TestCase):
    def setUp(self):
        self._now = rf._utcnow
        self.tmp = Path(tempfile.mkdtemp())
        self.stats = self.tmp / "stats_player_week_2026.csv.gz"
        self.sched = self.tmp / "games.csv"
        self.write_stats(_stats())
        with open(self.sched, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=SCHED_COLS)
            w.writeheader()
            w.writerows(_games())
        rf.record_download(self.sched, source="test")

    def tearDown(self):
        rf._utcnow = self._now

    def write_stats(self, rows, fetched="2026-10-25T08:00:00-05:00"):
        _gz(self.stats, STAT_COLS, rows)
        rf._utcnow = at(fetched)
        rf.record_download(self.stats, source="test")
        rf.record_download(self.sched, source="test") if self.sched.exists() else None

    def load(self, cap=CAP):
        return rf.load_current_season(self.stats, self.sched, season=2026,
                                      captured_at=cap)


class TestFetchedAt(Base):
    def test_fetched_at_from_sidecar(self):
        out = self.load()
        self.assertEqual(out["fetched_at"], "2026-10-25T13:00:00+00:00")
        side = json.loads(rf.sidecar_path(self.stats).read_text())
        self.assertEqual(side["sha256"], out["stats_sha256"])

    def test_no_fetched_at_argument(self):
        with self.assertRaises(TypeError):
            rf.load_current_season(self.stats, self.sched, season=2026,
                                   captured_at=CAP, fetched_at=CAP)

    def test_missing_sidecar_fails(self):
        rf.sidecar_path(self.stats).unlink()
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load()
        self.assertEqual(cm.exception.code, "REFRESH_FETCH_RECORD_MISSING")

    def test_sidecar_hash_mismatch_fails(self):
        p = rf.sidecar_path(self.stats)
        d = json.loads(p.read_text()); d["sha256"] = "0" * 64
        p.write_text(json.dumps(d))
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load()
        self.assertEqual(cm.exception.code, "REFRESH_FETCH_RECORD_MISMATCH")

    def test_fetched_after_capture_fails(self):
        self.write_stats(_stats(), fetched="2026-11-04T12:00:00+00:00")
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load()
        self.assertEqual(cm.exception.code, "REFRESH_FETCHED_AFTER_CAPTURE")

    def test_fetched_73h_before_fails_72h_ok(self):
        self.write_stats(_stats(), fetched="2026-10-22T09:59:00-05:00")
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load()
        self.assertEqual(cm.exception.code, "REFRESH_STALE")
        # exactly 72h before: inside the window (synthetic file is complete)
        self.write_stats(_stats(), fetched="2026-10-22T11:00:00-05:00")
        out = self.load(cap="2026-10-25T11:00:00-05:00")
        self.assertTrue(out)

    def test_blank_or_tbd_gametime_fails(self):
        for gt in ("", "TBD"):
            with self.subTest(gametime=gt):
                g = _games(); g[2]["gametime"] = gt
                with open(self.sched, "w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=SCHED_COLS)
                    w.writeheader(); w.writerows(g)
                rf.record_download(self.sched, source="test")
                with self.assertRaises(rf.RefreshFailed) as cm:
                    self.load()
                self.assertEqual(cm.exception.code, "REFRESH_FAILED")


class TestDuplicates(Base):
    def test_duplicate_player_game_fails(self):
        rows = _stats(); rows.append(dict(rows[0]))
        self.write_stats(rows)
        with self.assertRaises(rf.RefreshFailed) as cm:
            self.load()
        self.assertEqual(cm.exception.code, "REFRESH_FAILED")
        self.assertIn("duplicate", cm.exception.detail)


class TestRunTime(Base):
    def run_at(self, now, kickoff="2026-10-25T12:00:00-05:00"):
        rf._utcnow = at(now)
        rec = self.tmp / "rr.json"
        called = []
        if True:
            rf.run_slate(stats_path=self.stats, schedule_path=self.sched,
                         season=2026, captured_at=CAP, kickoff=kickoff,
                         run_record_path=rec, base_data=None,
                         pricer=lambda d: called.append(1) or [])
        return json.loads(rec.read_text()), called

    def test_run_before_kickoff_records_time(self):
        rec, called = self.run_at("2026-10-25T11:30:00-05:00")
        self.assertEqual(called, [1])
        self.assertEqual(rec["run_started_at"], "2026-10-25T16:30:00+00:00")

    def test_run_at_or_after_kickoff_fails(self):
        for now in ("2026-10-25T12:00:00-05:00", "2026-10-25T13:00:00-05:00"):
            with self.subTest(now=now):
                with self.assertRaises(rf.RefreshFailed) as cm:
                    self.run_at(now)
                self.assertEqual(cm.exception.code, "RUN_AFTER_KICKOFF")


def _cap(gid, pid, t, price):
    return {"game_id": gid, "player_id": pid, "captured_at": t, "yes_price": price}


class TestCloseAndKeys(unittest.TestCase):
    KO = "2026-10-25T17:00:00Z"

    def test_latest_invalid_no_fallback(self):
        caps = [_cap("g1", "P", "2026-10-25T16:30:00Z", 200),
                _cap("g1", "P", "2026-10-25T16:55:00Z", None)]
        self.assertEqual(sc.find_close(caps, "g1", "P", self.KO),
                         "CLOSE_LATEST_INVALID")

    def test_match_on_game_and_player(self):
        caps = [_cap("g2", "P", "2026-10-25T16:55:00Z", 150)]
        self.assertEqual(sc.find_close(caps, "g1", "P", self.KO), "NO_CLOSE_ROW")
        e = {"status": "PRICED", "player_id": "P", "selection": "YES",
             "game_id": "g1", "week": 8, "kickoff": self.KO,
             "raw_implied": sc.implied(200)}
        r = sc.score_row(e, caps, {("g2", "P"): 1})
        self.assertEqual(r["outcome_status"], "UNSETTLED")
        r = sc.score_row(e, caps, {("g1", "P"): 1})
        self.assertEqual(r["outcome"], 1)


class TestReviewOnce(unittest.TestCase):
    def setUp(self):
        self.rec = records_wt()

    def test_verdict_written_create_only_with_input_hash(self):
        led = _ledger(5, 14, 3, clv=0.02)
        v = _review(led, self.rec)
        p = self.rec / sc.VERDICT_PATH
        on_disk = json.loads(p.read_text())
        self.assertEqual(on_disk["verdict"], v["verdict"])
        self.assertEqual(on_disk["inputs_sha256"], sc.inputs_sha256(led[:4]))

    def test_refuses_if_verdict_exists_regardless_of_args(self):
        led = _ledger(5, 14, 3, clv=0.02)
        _review(led, self.rec)
        for args in (led, led[:4], _ledger(6, 20, 3, clv=-0.02)):
            with self.assertRaises(sc.ReviewAlreadyRecorded):
                _review(args, self.rec)

    def test_checked_before_review(self):
        (self.rec / sc.VERDICT_PATH).parent.mkdir(parents=True)
        (self.rec / sc.VERDICT_PATH).write_text("{}")
        with self.assertRaises(sc.ReviewAlreadyRecorded):
            _review([], self.rec)

    def test_records_dir_required(self):
        with self.assertRaises(TypeError):
            sc.review(_ledger(5, 14, 3))

    def test_gates_not_met_writes_nothing(self):
        v = _review(_ledger(3, 14, 3), self.rec)
        self.assertEqual(v["status"], "NO_REVIEW_GATES_NOT_MET")
        self.assertFalse((self.rec / sc.VERDICT_PATH).exists())

    def test_insufficient_close_data(self):
        led = _ledger(4, 14, 3, clv=0.02)
        n = 0
        for s in led:
            for r in s["rows"]:
                if r["selection"] == "YES" and n < 35:   # 35/168 = 20.8%
                    r.update(clv=None, clv_status="CLV_MISSING",
                             clv_reason="NO_CLOSE_ROW"); n += 1
        v = _review(led, self.rec)
        self.assertEqual(v["verdict"], "INSUFFICIENT_CLOSE_DATA")

    def test_twenty_percent_exactly_not_tripped(self):
        led = _ledger(4, 20, 3, clv=0.02)  # 240 picked, 48 = 20%
        n = 0
        for s in led:
            for r in s["rows"]:
                if r["selection"] == "YES" and n < 48:
                    r.update(clv=None, clv_status="CLV_MISSING",
                             clv_reason="NO_CLOSE_ROW"); n += 1
        v = _review(led, self.rec)
        self.assertNotEqual(v["verdict"], "INSUFFICIENT_CLOSE_DATA")

    def test_all_picked_game_clv_adj_zero(self):
        rows = [{"player_id": p, "selection": "YES", "game_id": "g",
                 "clv": c, "clv_status": "OK"} for p, c in (("a", .03), ("b", .01))]
        sc.cut_drift_adjust(rows)
        self.assertAlmostEqual(sum(r["clv_adj"] for r in rows), 0.0)


if __name__ == "__main__":
    unittest.main()
