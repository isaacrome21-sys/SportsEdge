"""Fail-closed board-row tests (t227 defect fixes). RED first.

Run: python3 -m unittest test_nfl_atd_board_failclosed -v
Covers: (1) player_id rows get the same team-in-game check as name rows;
(2) an invalid yes_price refuses that row, never crashes the board;
(3) captured_at >= kickoff, or missing/unparseable timing, refuses the row;
(4) the engine emits only declared UNPRICED reason codes.
"""
import unittest

import atd_engine as eng

PRICED_STUB = {"status": "PRICED", "model_p": 0.30, "prior_games": 9,
               "weighted_games": 7.0, "weighted_td_games": 2.0,
               "pool_rate": 0.2, "pool_n": 500, "pool_source": "TEST",
               "position_group": "RB", "raw_rate": 0.3}


def _data():
    return {"by_player": {}, "by_season": {},
            "meta": {"p_gb": {"display_name": "Josh Jacobs", "team": "GB",
                              "position_group": "RB", "last_season": 2025,
                              "last_week": 18},
                     "p_bal": {"display_name": "Derrick Henry", "team": "BAL",
                               "position_group": "RB", "last_season": 2025,
                               "last_week": 18}}}


def _row(**kw):
    r = {"game_id": "g", "player_name": "Josh Jacobs", "player_id": "p_gb",
         "game_teams": ["DAL", "GB"], "yes_price": -150,
         "captured_at": "2026-10-25T11:00:00-05:00",
         "kickoff": "2026-10-25T12:00:00-05:00", "season": 2026, "week": 8}
    r.update(kw)
    return r


class StubbedEngine(unittest.TestCase):
    def setUp(self):
        self._orig = eng.price_player
        eng.price_player = lambda d, pid, s, w, pool_cache=None: dict(PRICED_STUB)

    def tearDown(self):
        eng.price_player = self._orig

    def price(self, **kw):
        data = _data()
        return eng.price_board_row(data, eng.build_name_index(data), _row(**kw))


class TestPlayerIdTeamCheck(StubbedEngine):
    def test_player_id_in_game_is_priced(self):
        self.assertEqual(self.price()["status"], "PRICED")

    def test_player_id_team_mismatch_refused(self):
        out = self.price(player_name="Derrick Henry", player_id="p_bal")
        self.assertEqual(out["status"], "UNPRICED")
        self.assertEqual(out["reason"], "UNPRICED_PLAYER_TEAM_MISMATCH")
        self.assertNotIn("model_p", out)

    def test_unknown_player_id_refused(self):
        out = self.price(player_id="nope")
        self.assertEqual(out["reason"], "UNPRICED_PLAYER_ID_UNKNOWN")

    def test_missing_game_teams_refuses_player_id_row(self):
        out = self.price(game_teams=[])
        self.assertEqual(out["reason"], "UNPRICED_PLAYER_TEAM_MISMATCH")

    def test_name_row_mismatch_still_unresolved(self):
        out = self.price(player_name="Derrick Henry", player_id=None)
        self.assertEqual(out["reason"], "UNPRICED_NAME_UNRESOLVED")


class TestInvalidPrice(StubbedEngine):
    BAD = [0, "abc", None, "", float("nan"), float("inf"), 50, -99.5, 99,
           True, False, [], {}, 1_000_001, -1_000_001]

    def test_each_invalid_price_refuses_row(self):
        for bad in self.BAD:
            with self.subTest(price=bad):
                out = self.price(yes_price=bad)
                self.assertEqual(out["status"], "UNPRICED")
                self.assertEqual(out["reason"], "UNPRICED_INVALID_PRICE")
                self.assertNotIn("model_p", out)

    def test_valid_prices_still_priced(self):
        for good in (-100, 100, -230, 600, "+600", "-230", 25000):
            with self.subTest(price=good):
                self.assertEqual(self.price(yes_price=good)["status"], "PRICED")

    def test_bad_row_does_not_crash_board(self):
        data = _data()
        idx = eng.build_name_index(data)
        rows = [_row(), _row(yes_price=0), _row(yes_price="x"),
                _row(yes_price=None), _row()]
        out = [eng.price_board_row(data, idx, r) for r in rows]
        self.assertEqual([o["status"] for o in out],
                         ["PRICED", "UNPRICED", "UNPRICED", "UNPRICED", "PRICED"])

    def test_missing_yes_price_key(self):
        data = _data()
        r = _row()
        del r["yes_price"]
        out = eng.price_board_row(data, eng.build_name_index(data), r)
        self.assertEqual(out["reason"], "UNPRICED_INVALID_PRICE")


class TestCaptureTiming(StubbedEngine):
    def test_after_kickoff_refused(self):
        out = self.price(captured_at="2026-10-25T12:30:00-05:00")
        self.assertEqual(out["reason"], "UNPRICED_CAPTURED_AFTER_KICKOFF")

    def test_at_kickoff_refused(self):
        out = self.price(captured_at="2026-10-25T12:00:00-05:00")
        self.assertEqual(out["reason"], "UNPRICED_CAPTURED_AFTER_KICKOFF")

    def test_cross_zone_comparison(self):
        # 12:30 ET == 11:30 CT, before a 12:00 CT kickoff.
        self.assertEqual(self.price(captured_at="2026-10-25T12:30:00-04:00")
                         ["status"], "PRICED")
        out = self.price(captured_at="2026-10-25T17:01:00Z")
        self.assertEqual(out["reason"], "UNPRICED_CAPTURED_AFTER_KICKOFF")

    def test_capture_house_format(self):
        out = self.price(captured_at="2026-10-18 3:13 PM CT",
                         kickoff="2026-10-18 7:20 PM CT")
        self.assertEqual(out["status"], "PRICED")
        out = self.price(captured_at="2026-10-18 7:25 PM CT",
                         kickoff="2026-10-18 7:20 PM CT")
        self.assertEqual(out["reason"], "UNPRICED_CAPTURED_AFTER_KICKOFF")

    def test_missing_timing_refused(self):
        for kw in ({"captured_at": None}, {"kickoff": None},
                   {"captured_at": ""}, {"kickoff": ""}):
            with self.subTest(**{k: repr(v) for k, v in kw.items()}):
                self.assertEqual(self.price(**kw)["reason"],
                                 "UNPRICED_TIMESTAMP_MISSING")

    def test_unparseable_timing_refused(self):
        for kw in ({"captured_at": "t"}, {"kickoff": "k"},
                   {"captured_at": "2026-10-25T11:00:00"},  # naive: no zone
                   {"kickoff": "2026-10-25 7:20 PM"},       # no zone
                   {"captured_at": 12345}):
            with self.subTest(**{k: repr(v) for k, v in kw.items()}):
                self.assertEqual(self.price(**kw)["reason"],
                                 "UNPRICED_TIMESTAMP_UNPARSEABLE")


class TestDeclaredCodes(unittest.TestCase):
    def test_constant_lists_every_code(self):
        want = {"UNPRICED_INSUFFICIENT_GAMES",
                "UNPRICED_POSITION_GROUP_NOT_POOLED",
                "UNPRICED_POOL_UNAVAILABLE", "UNPRICED_NAME_UNRESOLVED",
                "UNPRICED_NOT_A_PLAYER_ROW", "UNPRICED_PLAYER_ID_UNKNOWN",
                "UNPRICED_PLAYER_TEAM_MISMATCH", "UNPRICED_INVALID_PRICE",
                "UNPRICED_CAPTURED_AFTER_KICKOFF",
                "UNPRICED_TIMESTAMP_MISSING", "UNPRICED_TIMESTAMP_UNPARSEABLE"}
        self.assertEqual(set(eng.DECLARED_UNPRICED_REASONS), want)

    def test_source_emits_only_declared_codes(self):
        import re
        from pathlib import Path
        src = Path(eng.__file__).read_text()
        used = set(re.findall(r'"(UNPRICED_[A-Z_]+)"', src))
        self.assertTrue(used <= set(eng.DECLARED_UNPRICED_REASONS),
                        used - set(eng.DECLARED_UNPRICED_REASONS))

    def test_engine_outputs_only_declared_codes(self):
        # Drive the real (unstubbed) engine across every refusal path.
        apps = lambda pid, team, grp, n: [
            {"season": 2025, "week": w, "pid": pid, "position_group": grp,
             "team": team, "opp": "X", "td": w % 2, "st_td": 0}
            for w in range(1, n + 1)]
        bp = {"ok": apps("ok", "GB", "RB", 8), "few": apps("few", "GB", "RB", 2),
              "k": apps("k", "GB", "SPEC", 8), "bal": apps("bal", "BAL", "RB", 8)}
        meta = {pid: {"display_name": pid, "team": a[-1]["team"],
                      "position_group": a[-1]["position_group"],
                      "last_season": 2025, "last_week": len(a)}
                for pid, a in bp.items()}
        data = {"by_player": bp, "by_season": {}, "meta": meta}  # no pool
        idx = eng.build_name_index(data)
        rows = [_row(player_id=p, player_name=p) for p in bp] + [
            _row(player_id=None, player_name="ghost"),
            _row(player_name="GB Packers D/ST", player_id=None),
            _row(player_id="zzz"), _row(yes_price=0), _row(kickoff=None),
            _row(kickoff="nope"), _row(captured_at="2026-10-25T13:00:00-05:00")]
        seen = set()
        for r in rows:
            out = eng.price_board_row(data, idx, r)
            self.assertIn(out["status"], ("PRICED", "UNPRICED"))
            if out["status"] == "UNPRICED":
                self.assertIn(out["reason"], eng.DECLARED_UNPRICED_REASONS)
                seen.add(out["reason"])
        self.assertIn("UNPRICED_POOL_UNAVAILABLE", seen)
        self.assertGreaterEqual(len(seen), 10)


if __name__ == "__main__":
    unittest.main()
