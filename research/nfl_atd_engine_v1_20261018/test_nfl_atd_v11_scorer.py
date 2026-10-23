"""v1.1 (B) forward scorer tests (#2399 Rules 4-6). RED first.
Run: python3 -m unittest test_nfl_atd_v11_scorer -v
"""
import subprocess
import tempfile
import unittest
from pathlib import Path

import score_nfl_atd_forward as sc

KO = "2026-10-25T12:00:00-05:00"


def records_wt():
    """Temp bare origin + worktree on the records branch (real git)."""
    import atd_provenance as pv
    t = Path(tempfile.mkdtemp())
    g = lambda cwd, *a: subprocess.run(["git", *a], cwd=cwd, check=True,
                                       capture_output=True)
    g(t, "init", "-q", "--bare", "o.git")
    g(t, "init", "-q", "-b", pv.RECORDS_BRANCH, "wt")
    wt = t / "wt"
    g(wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
      "--allow-empty", "-m", "init")
    g(wt, "remote", "add", "origin", str(t / "o.git"))
    g(wt, "push", "-q", "origin", pv.RECORDS_BRANCH)
    return wt


def _review(led, wt=None):
    """Review with every slate's provenance treated as COUNTS (provenance
    itself is tested in test_nfl_atd_v11_provenance)."""
    return sc.review(led, records_worktree=wt or records_wt(), api=None,
                     slate_status=lambda api, s: {"status": "COUNTS", "reasons": []})


def entry(pid, sel, price, game="g1", week=8, kickoff=KO):
    return {"status": "PRICED", "player_id": pid, "selection": sel,
            "yes_price": price, "game_id": game, "week": week,
            "kickoff": kickoff, "raw_implied": sc.implied(price)}


class TestRule4Close(unittest.TestCase):
    def test_last_capture_within_60(self):
        caps = [{"game_id": "g1", "player_id": "a", "yes_price": 200,
                 "captured_at": "2026-10-25T10:30:00-05:00"},
                {"game_id": "g1", "player_id": "a", "yes_price": 150,
                 "captured_at": "2026-10-25T11:50:00-05:00"},
                {"game_id": "g1", "player_id": "a", "yes_price": 100,
                 "captured_at": "2026-10-25T12:00:00-05:00"}]  # at KO: no
        c = sc.find_close(caps, "g1", "a", KO)
        self.assertEqual(c["yes_price"], 150)

    def test_stale_and_missing(self):
        caps = [{"game_id": "g1", "player_id": "a", "yes_price": 200,
                 "captured_at": "2026-10-25T10:59:00-05:00"}]
        self.assertEqual(sc.find_close(caps, "g1", "a", KO), "CLOSE_STALE")
        self.assertEqual(sc.find_close([], "g1", "a", KO), "NO_CLOSE_ROW")
        ok = [{"game_id": "g1", "player_id": "a", "yes_price": 200,
               "captured_at": "2026-10-25T11:00:00-05:00"}]  # exactly 60
        self.assertEqual(sc.find_close(ok, "g1", "a", KO)["yes_price"], 200)

    def test_clv_sign(self):
        caps = [{"game_id": "g1", "player_id": "a", "yes_price": 150,
                 "captured_at": "2026-10-25T11:50:00-05:00"}]
        r = sc.score_row(entry("a", "YES", 200), caps, {("g1", "a"): 1})
        self.assertAlmostEqual(r["clv"], sc.implied(150) - sc.implied(200))
        self.assertGreater(r["clv"], 0)
        self.assertEqual(r["outcome"], 1)

    def test_clv_missing_row_keeps_outcome(self):
        r = sc.score_row(entry("a", "YES", 200), [], {("g1", "a"): 0})
        self.assertEqual(r["clv_status"], "CLV_MISSING")
        self.assertEqual(r["clv_reason"], "NO_CLOSE_ROW")
        self.assertIsNone(r["clv"])
        self.assertEqual(r["outcome"], 0)

    def test_unpriced_rows_not_scored(self):
        r = sc.score_row({"status": "UNPRICED", "reason": "X",
                          "player_id": "a", "game_id": "g1", "week": 8},
                         [], {("g1", "a"): 1})
        self.assertIsNone(r)

    def test_unsettled_row_refused(self):
        r = sc.score_row(entry("a", "YES", 200), [], {})
        self.assertEqual(r["outcome_status"], "UNSETTLED")


class TestRule5CutDrift(unittest.TestCase):
    def test_game_drift_removed(self):
        # Every price in the game shortens by the same implied amount:
        # pure cut drift -> drift-adjusted CLV of the pick is ~0.
        rows = []
        for pid, sel in (("a", "YES"), ("b", "PASS"), ("c", "PASS")):
            rows.append({"player_id": pid, "selection": sel, "game_id": "g1",
                         "clv": 0.02, "clv_status": "OK"})
        adj = sc.cut_drift_adjust(rows)
        self.assertAlmostEqual(adj["g1"]["drift"], 0.02)
        self.assertAlmostEqual(rows[0]["clv_adj"], 0.0)

    def test_drift_flag(self):
        rows = [{"player_id": p, "selection": "PASS", "game_id": "g1",
                 "clv": 0.05, "clv_status": "OK"} for p in "abcd"]
        adj = sc.cut_drift_adjust(rows)
        self.assertTrue(adj["g1"]["drifted"])


def _ledger(n_weeks, games_per_week, picks_per_game, clv=0.01):
    slates = []
    for w in range(n_weeks):
        rows = []
        for g in range(games_per_week):
            gid = f"w{w}g{g}"
            for i in range(picks_per_game):
                rows.append({"player_id": f"{gid}y{i}", "selection": "YES",
                             "game_id": gid, "week": w + 1,
                             "clv": clv + 0.001 * (i % 3) + 0.002 * (g % 5), "clv_status": "OK",
                             "outcome": i % 2, "outcome_status": "SETTLED",
                             "raw_implied": 0.3})
            rows.append({"player_id": f"{gid}p", "selection": "PASS",
                         "game_id": gid, "week": w + 1, "clv": -0.01,
                         "clv_status": "OK", "outcome": 0,
                         "outcome_status": "SETTLED", "raw_implied": 0.3})
        slates.append({"slate_id": f"2026-W{w + 1}", "rows": rows})
    return slates


class TestRule6Gates(unittest.TestCase):
    def test_gates_not_met(self):
        v = _review(_ledger(3, 14, 4))  # 3 weeks only
        self.assertEqual(v["status"], "NO_REVIEW_GATES_NOT_MET")
        v = _review(_ledger(4, 9, 5))   # 36 games
        self.assertEqual(v["status"], "NO_REVIEW_GATES_NOT_MET")
        v = _review(_ledger(4, 12, 3))  # 144 picks
        self.assertEqual(v["status"], "NO_REVIEW_GATES_NOT_MET")

    def test_single_review_at_first_slate_meeting_gates(self):
        led = _ledger(6, 14, 3)  # gates met at week 4 (56 games, 168 picks)
        v = _review(led)
        self.assertEqual(v["status"], "REVIEWED")
        self.assertEqual(v["review_slate"], "2026-W4")
        self.assertEqual(v["n_picked"], 168)
        self.assertEqual(v["n_games"], 56)
        # Later slates do not enter the sample of record.
        self.assertEqual(v, _review(led[:4]))

    def test_games_minimum_not_cap(self):
        v = _review(_ledger(4, 20, 2))  # 80 games > 40, 160 picks
        self.assertEqual(v["n_games"], 80)

    def test_no_rerun_after_record(self):
        led = _ledger(5, 14, 3)
        d = records_wt()
        _review(led, d)
        with self.assertRaises(sc.ReviewAlreadyRecorded):
            _review(led, d)

    def test_beats_market(self):
        self.assertEqual(_review(_ledger(4, 14, 3, clv=0.02))["verdict"],
                         "BEATS_MARKET")
        self.assertEqual(_review(_ledger(4, 14, 3, clv=-0.02))["verdict"],
                         "DOES_NOT_BEAT_MARKET")

    def test_clustered_ci_present(self):
        v = _review(_ledger(4, 14, 3, clv=0.02))
        lo, hi = v["clv_picked_ci95"]
        self.assertLess(lo, v["clv_picked_mean"])
        self.assertGreater(hi, v["clv_picked_mean"])

    def test_labels_never_play(self):
        v = _review(_ledger(4, 14, 3, clv=0.02))
        self.assertEqual(v["status_label"], "RESEARCH_ONLY")
        self.assertFalse(v["promotable"])


if __name__ == "__main__":
    unittest.main()
