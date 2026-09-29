import unittest

from sportsedge.sports.nfl.context_autopull import NFLContextError
from sportsedge.sports.nfl.nflverse_role_bridge import build_nflverse_prop_role_payloads


class NflverseRoleBridgeTests(unittest.TestCase):
    def _rows(self):
        return [
            {"game_id":"old1","season":2026,"week":1,"player_id":"qb1","player_name":"QB One","team":"CHI","position":"QB","attempts":30,"completions":20,"passing_yards":240,"passing_tds":2,"interceptions":1,"carries":4,"rushing_yards":20,"rushing_tds":1},
            {"game_id":"old2","season":2026,"week":2,"player_id":"qb1","player_name":"QB One","team":"CHI","position":"QB","attempts":40,"completions":30,"passing_yards":330,"passing_tds":1,"interceptions":0,"carries":6,"rushing_yards":42,"rushing_tds":0},
            {"game_id":"old1","season":2026,"week":1,"player_id":"wr1","player_name":"WR One","team":"CHI","position":"WR","targets":10,"receptions":7,"receiving_yards":91,"receiving_tds":1,"carries":1,"rushing_yards":5},
            {"game_id":"old2","season":2026,"week":2,"player_id":"wr1","player_name":"WR One","team":"CHI","position":"WR","targets":8,"receptions":5,"receiving_yards":65,"receiving_tds":1},
        ]

    def _build(self, rows=None, **overrides):
        kw = dict(game_id="2026_03_CHI_X", kickoff="2026-09-28T23:00:00Z", observed_at="2026-09-28T20:00:00Z", source_uri="https://github.com/nflverse/nflverse-data", player_rows=self._rows() if rows is None else rows)
        kw.update(overrides)
        return build_nflverse_prop_role_payloads(**kw)

    def test_builds_empirical_role_vectors_and_td_shares(self):
        out = self._build()
        players = {row["player_id"]: row for row in out["players"]}
        qb, wr = players["qb1"], players["wr1"]
        self.assertAlmostEqual(qb["role_prior"]["pass_attempts"], 35.0)
        self.assertAlmostEqual(qb["role_prior"]["completion_rate"], 50/70)
        self.assertAlmostEqual(qb["role_prior"]["pass_yards_per_completion"], 570/50)
        self.assertAlmostEqual(qb["rushing_td_share"], 1.0)
        self.assertAlmostEqual(wr["role_prior"]["targets"], 9.0)
        self.assertAlmostEqual(wr["role_prior"]["catch_rate"], 12/18)
        self.assertAlmostEqual(wr["receiving_td_share"], 1.0)

    def test_rejects_target_week(self):
        rows=self._rows(); rows[0]=dict(rows[0],week=3)
        with self.assertRaisesRegex(NFLContextError,"not pre-target PIT data"): self._build(rows)

    def test_rejects_missing_marker(self):
        rows=self._rows(); del rows[0]["week"]
        with self.assertRaisesRegex(NFLContextError,"missing season/week PIT markers"): self._build(rows)

    def test_rejects_market_contamination(self):
        rows=self._rows(); rows[0]=dict(rows[0],sportsbook_price=-110)
        with self.assertRaisesRegex(NFLContextError,"market input forbidden"): self._build(rows)

    def test_rejects_post_kickoff(self):
        with self.assertRaisesRegex(NFLContextError,"before kickoff"): self._build(observed_at="2026-09-28T23:00:00Z")


if __name__ == "__main__": unittest.main()
