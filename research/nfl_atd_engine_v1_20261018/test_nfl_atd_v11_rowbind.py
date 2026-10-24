"""v1.1 re-audit of 5150203a: each row is bound to its schedule game and the
player's pinned-stats team. RED first.  Run: python3 -m pytest test_nfl_atd_v11_rowbind.py
"""
import unittest

import atd_provenance as pv
from fake_github_api import FakeGitHub, ledger_to_records
from test_nfl_atd_v11_branchdata import led


class TestRowBinding(unittest.TestCase):
    def st(self, **kw):
        api = FakeGitHub()
        ledger_to_records(api, led(), **kw)
        return pv.load_slate(api, "S1")

    def test_honest_counts(self):
        st = self.st()
        self.assertEqual(st["status"], "COUNTS", st["reasons"])

    def test_row_mapped_to_other_schedule_game(self):
        # row says g1 but carries g2's teams -> schedule matches g2
        st = self.st(teams_override={"g1": ["Ag2", "Hg2"]})
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("ROW_GAME_ID_MISMATCH", st["reasons"])

    def test_player_team_not_in_game(self):
        st = self.st(player_team={"a": "Hg2"})
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("ROW_PLAYER_TEAM_MISMATCH", st["reasons"])

    def test_player_absent_from_stats_refused(self):
        st = self.st(player_team={"a": None})
        self.assertEqual(st["status"], "SCREEN")
        self.assertIn("ROW_PLAYER_TEAM_MISMATCH", st["reasons"])

    def test_away_team_player_ok(self):
        self.assertEqual(self.st(player_team={"a": "Ag1"})["status"], "COUNTS")

    def test_latest_stats_team_used(self):
        # helper reads the latest REG week of the run season
        import gzip
        body = gzip.compress(b"player_id,season,season_type,week,recent_team\n"
                             b"a,2026,REG,3,OLD\na,2026,REG,6,NEW\na,2025,REG,17,X\n")
        self.assertEqual(pv.stats_teams(body, 2026), {"a": "NEW"})

    def test_pricer_stores_schedule_game_id(self):
        import inspect
        import price_nfl_atd_board_v11 as pr
        src = inspect.getsource(pr)
        self.assertIn('"game_id": sk["game_id"]', src)
        self.assertIn('board_game_id', src)

# port (re-audit 8d86e7a9): the fake pricer is patched in by fixture, never
# registered on import.
from fake_github_api import module_fixtures as _mf
setUpModule, tearDownModule = _mf(guard=False)

if __name__ == "__main__":
    unittest.main()
