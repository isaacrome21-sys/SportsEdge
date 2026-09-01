from __future__ import annotations

import json
import unittest

from sportsedge.sports.cfb.season_priors_source import (
    fetch_returning_production, fetch_team_talent, fetch_prior_season_player_usage,
    match_usage_to_current_roster,
)


class _Resp:
    def __init__(self, payload): self.raw = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.raw


class CFBSeasonPriorTests(unittest.TestCase):
    def test_returning_and_talent_normalize(self):
        def opener(req, timeout=25):
            if "/player/returning" in req.full_url:
                return _Resp([{"season":2026,"team":"A","conference":"ACC","percentPPA":0.7,"usage":0.65}])
            if "/talent" in req.full_url:
                return _Resp([{"year":2026,"school":"A","talent":812.5}])
            raise AssertionError(req.full_url)
        returning, _, rsha = fetch_returning_production(season=2026, cfbd_api_key="x", opener=opener)
        talent, _, tsha = fetch_team_talent(season=2026, cfbd_api_key="x", opener=opener)
        self.assertEqual(returning["A"]["percent_ppa"], 0.7)
        self.assertEqual(talent["A"]["talent"], 812.5)
        self.assertEqual(len(rsha), 64)
        self.assertEqual(len(tsha), 64)

    def test_prior_usage_matches_current_roster_by_athlete_id_and_preserves_transfer(self):
        def opener(req, timeout=25):
            self.assertIn("year=2025", req.full_url)
            return _Resp([{"season":2025,"id":"11","name":"Player X","team":"Old U","position":"WR","usage":{"overall":0.2,"pass":0.1,"rush":0.0}}])
        rows, _, digest = fetch_prior_season_player_usage(season=2026, cfbd_api_key="x", opener=opener)
        matched = match_usage_to_current_roster(
            usage_rows=rows,
            current_roster_rows=[{"athlete_id":"11","position":"WR"}],
            current_team="New U",
        )
        self.assertEqual(len(digest), 64)
        self.assertEqual(matched[0]["usage_overall"], 0.2)
        self.assertTrue(matched[0]["transfer_team_changed"])
        self.assertEqual(matched[0]["current_team"], "New U")


if __name__ == "__main__": unittest.main()
