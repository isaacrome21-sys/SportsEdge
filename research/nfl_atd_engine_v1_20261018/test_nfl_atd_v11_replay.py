"""v1.1 re-audit of 353147d5: full replay. Every pricer input is a
single-commit branch record; review re-runs the sha-verified pricer on
exactly those records and requires byte-identical canonical rows.
RED first.  Run: python3 -m pytest test_nfl_atd_v11_replay.py
"""
import gzip
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

import atd_provenance as pv
import atd_refresh as rf
from fake_github_api import FakeGitHub, synthetic_world

NOW = datetime(2026, 10, 25, 16, 30, tzinfo=timezone.utc)
FET = {"stats": "2026-10-25T15:00:00+00:00", "schedule": "2026-10-25T15:01:00+00:00"}


def real_rows(w):
    import price_nfl_atd_board_v11 as pr
    return pr.replay(w.inputs(), now=NOW, fetched_at=FET)


class TestStatsTeamsTie(unittest.TestCase):
    def body(self, rows):
        return gzip.compress(("player_id,season,season_type,week,recent_team\n" +
                              "".join(f"{r}\n" for r in rows)).encode())

    def test_same_week_different_teams_unresolved(self):
        t = pv.stats_teams(self.body(["a,2026,REG,7,KC", "a,2026,REG,7,DEN"]), 2026)
        self.assertIsNone(t["a"])

    def test_order_independent(self):
        t = pv.stats_teams(self.body(["a,2026,REG,7,DEN", "a,2026,REG,7,KC"]), 2026)
        self.assertIsNone(t["a"])

    def test_same_week_same_team_ok(self):
        t = pv.stats_teams(self.body(["a,2026,REG,7,KC", "a,2026,REG,7,KC"]), 2026)
        self.assertEqual(t["a"], "KC")

    def test_earlier_tie_superseded(self):
        t = pv.stats_teams(self.body(["a,2026,REG,6,KC", "a,2026,REG,6,DEN",
                                      "a,2026,REG,7,DEN"]), 2026)
        self.assertEqual(t["a"], "DEN")


class TestCanonical(unittest.TestCase):
    def test_canonical_json(self):
        self.assertEqual(pv.canonical_json([{"b": 1, "a": 0.5}]), b'[{"a":0.5,"b":1}]')
        self.assertEqual(pv.canonical_json([{"a": 1}]), pv.canonical_json([{"a": 1}]))


class TestRealPricerReplay(unittest.TestCase):
    def setUp(self):
        self.w = synthetic_world().__enter__()
        self.addCleanup(self.w.__exit__)
        self.rows = real_rows(self.w)

    def test_world_prices_and_refuses(self):
        by = {r["player_id"]: r for r in self.rows}
        self.assertEqual(by["P1"]["status"], "PRICED", by["P1"])
        self.assertEqual(by["P1"]["game_id"], "2026_08_LV_KC")
        self.assertEqual(by["OLD"]["reason"], "PLAYER_TEAM_UNRESOLVED")   # no 2026 stats
        self.assertEqual(by["TR"]["reason"], "PLAYER_TEAM_UNRESOLVED")    # same-week tie

    def test_replay_deterministic_and_clock_free(self):
        orig = rf._utcnow
        rf._utcnow = lambda: (_ for _ in ()).throw(AssertionError("wall clock used"))
        try:
            again = real_rows(self.w)
        finally:
            rf._utcnow = orig
        self.assertEqual(pv.canonical_json(again), pv.canonical_json(self.rows))

    def load(self, **kw):
        api = FakeGitHub()
        self.w.publish(api, self.rows, **kw)
        return pv.load_slate(api, "W1")

    def test_honest_record_counts(self):
        st = self.load()
        self.assertEqual(st["status"], "COUNTS", st["reasons"])

    def test_review_does_not_use_wall_clock(self):
        orig = rf._utcnow
        rf._utcnow = lambda: (_ for _ in ()).throw(AssertionError("wall clock used"))
        try:
            st = self.load()
        finally:
            rf._utcnow = orig
        self.assertEqual(st["status"], "COUNTS", st["reasons"])

    def test_edited_priced_value_replay_mismatch(self):
        def edit(rows):
            for r in rows:
                if r["player_id"] == "P1":
                    r["p_model"] = r["p_model"] + 0.05
        st = self.load(edit=edit)
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("RUN_REPLAY_MISMATCH", st["reasons"])

    def test_forged_refusal_replay_mismatch(self):
        def edit(rows):
            for r in rows:
                if r["player_id"] == "P2" and r["status"] == "PRICED":
                    for k in list(r):
                        if k not in ("player_id", "player_name", "game_id", "yes_price"):
                            r.pop(k)
                    r.update(status="UNPRICED", reason="PLAYER_TEAM_UNRESOLVED")
        st = self.load(edit=edit)
        self.assertIn("RUN_REPLAY_MISMATCH", st["reasons"])

    def test_dropped_row_replay_mismatch(self):
        st = self.load(edit=lambda rows: rows.pop())
        self.assertIn("RUN_REPLAY_MISMATCH", st["reasons"])

    def test_unknown_pricer_sha(self):
        st = self.load(pricer_sha="0" * 64)
        self.assertIn("RUN_PRICER_SHA_MISMATCH", st["reasons"])

    def test_board_record_missing(self):
        st = self.load(skip=("board",))
        self.assertIn("BOARD_RECORD_NOT_ON_BRANCH", st["reasons"])

    def test_board_pushed_after_run(self):
        st = self.load(board_at="2026-10-25T16:40:00Z")
        self.assertIn("INPUT_PUSH_NOT_BEFORE_RUN_PUSH", st["reasons"])

    def test_player_data_record_missing(self):
        st = self.load(skip=("player_data",))
        self.assertIn("DATA_RECORD_NOT_ON_BRANCH", st["reasons"])

    def test_pricer_sha_covers_code(self):
        import price_nfl_atd_board_v11 as pr
        self.assertRegex(pr.pricer_sha256(), r"^[0-9a-f]{64}$")
        self.assertIn("price_nfl_atd_board_v11.py", pr.PRICER_FILES)
        self.assertIn("atd_engine.py", pr.PRICER_FILES)


class TestPrereg(unittest.TestCase):
    def test_section4_systematic_exclusion(self):
        t = (Path(__file__).with_name("PREREG_NFL_ATD_ENGINE_V1_1_DRAFT.md")).read_text()
        s4 = t[t.index("## 4."):t.index("## 5.")]
        self.assertIn("systematic exclusion", s4)
        self.assertIn("traded", s4)
        self.assertIn("no 2026 stats", s4)

    def test_section2b_replay(self):
        t = (Path(__file__).with_name("PREREG_NFL_ATD_ENGINE_V1_1_DRAFT.md")).read_text()
        s2b = t[t.index("## 2b."):t.index("## 3.")]
        self.assertIn("RUN_REPLAY_MISMATCH", s2b)
        self.assertIn("boards/<season>-W<week>/<sha>.json", s2b)


if __name__ == "__main__":
    unittest.main()
