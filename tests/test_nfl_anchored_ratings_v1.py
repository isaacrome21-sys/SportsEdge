"""Synthetic contract checks only. These DO NOT constitute the NFL viability screen."""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sportsedge.sports.nfl import anchored_ratings_v1 as a


class AnchoredRatingsResearchTests(unittest.TestCase):
    def test_issuance_is_exactly_weighted_and_capped(self):
        self.assertAlmostEqual(a.issue(20, 10), 10.6)
        self.assertAlmostEqual(a.issue(-20, 10), 9.4)
        self.assertAlmostEqual(a.issue(12, 10), 10.3)

    def _write_csv(self, root: Path, rows: list[dict]) -> Path:
        path = root / "games.csv"
        fields = ["game_type","game_id","gameday","home_team","away_team",
                  "home_score","away_score","spread_line","total_line",
                  "home_qb_delta","away_qb_delta","weather_total_delta","neutral_site","location"]
        with path.open("w",newline="",encoding="utf-8") as fh:
            writer = csv.DictWriter(fh,fieldnames=fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({"game_type":"REG",**row})
        return path

    def test_nonfinite_consensus_close_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            path = self._write_csv(Path(d), [{
                "game_id":"g1","gameday":"2024-09-01","home_team":"KC","away_team":"BUF",
                "home_score":24,"away_score":21,"spread_line":"nan","total_line":45,
            }])
            with self.assertRaisesRegex(ValueError,"spread_line_NONFINITE"):
                a.read_games(path)

    def test_qb_and_weather_docks_cannot_exceed_caps(self):
        base = {"game_id":"g1","gameday":"2024-09-01","home_team":"KC","away_team":"BUF",
                "home_score":24,"away_score":21,"spread_line":3,"total_line":45}
        for name,value,expected in [
            ("home_qb_delta",4.01,"QB_CHANGE_EXCEEDS_4_POINTS"),
            ("away_qb_delta",-4.01,"QB_CHANGE_EXCEEDS_4_POINTS"),
            ("weather_total_delta",2.01,"WEATHER_EXCEEDS_RESEARCH_CAP"),
        ]:
            with self.subTest(name=name),tempfile.TemporaryDirectory() as d:
                path=self._write_csv(Path(d),[{**base,name:value}])
                with self.assertRaisesRegex(ValueError,expected):
                    a.read_games(path)

    def test_duplicate_game_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            row={"game_id":"g1","gameday":"2024-09-01","home_team":"KC","away_team":"BUF",
                 "home_score":24,"away_score":21,"spread_line":3,"total_line":45}
            with self.assertRaisesRegex(ValueError,"DUPLICATE"):
                a.read_games(self._write_csv(Path(d),[row,row]))

    def test_pit_unattested_qb_context_refused_even_below_cap(self):
        with tempfile.TemporaryDirectory() as d:
            row={"game_id":"g1","gameday":"2024-09-01","home_team":"KC","away_team":"BUF",
                 "home_score":24,"away_score":21,"spread_line":3,"total_line":45,
                 "home_qb_delta":2.5}
            with self.assertRaisesRegex(ValueError,"PIT_QB_WEATHER_CONTEXT_RECEIPT_REQUIRED"):
                a.read_games(self._write_csv(Path(d),[row]))

    def test_hfa_uses_prior_non_neutral_games_only(self):
        neutral = [a.Game(f"2023-09-{(i%28)+1:02d}",f"g{i}","A","B",40,10,3,40,True)
                   for i in range(32)]
        level,hfa,ratings = a.fit_as_of(neutral)
        self.assertEqual(hfa,0.0)
        self.assertGreater(level,0)
        self.assertIn("A",ratings)

    def test_nflverse_location_neutral_field_disables_home_advantage(self):
        with tempfile.TemporaryDirectory() as d:
            row={"game_id":"g1","gameday":"2024-09-01","home_team":"KC","away_team":"BUF",
                 "home_score":24,"away_score":21,"spread_line":3,"total_line":45,
                 "location":"Neutral"}
            games=a.read_games(self._write_csv(Path(d),[row]))
            self.assertTrue(games[0].neutral)

    def test_missing_data_cannot_pass_viability(self):
        result=a.screen([],design_years=frozenset({2024}))
        self.assertEqual(result["status"],"FAILED_SCREEN")
        self.assertEqual(result["screens"]["spread"]["status"],"FAILED_SCREEN")
        self.assertEqual(result["screens"]["total"]["status"],"FAILED_SCREEN")
        self.assertEqual(result["counted_rows"],0)
        self.assertFalse(result["verified_clv"])
        self.assertFalse(result["promotion_authority"])

    def test_flat_realized_cover_bands_fail_automatically(self):
        rows=[]
        for b in (0.5,1.5,2.5,3.5):
            for i in range(20):
                rows.append({"raw":b,"close":0,"issued":a.issue(b,0),
                             "actual":1 if i<10 else -1,
                             "pred_cover":.51,"real_cover":float(i<10)})
        report=a.screen_market(rows,"spread")
        self.assertEqual(report["status"],"FAILED_SCREEN")
        self.assertIn("NONRISING_REALIZED_COVER_BANDS",report["failures"])

    def test_overstated_cover_band_fails(self):
        rows=[{"raw":.5,"close":0,"issued":a.issue(.5,0),"actual":-1,
               "pred_cover":.60,"real_cover":0.0} for _ in range(20)]
        report=a.screen_market(rows,"spread")
        self.assertIn("OVERSTATED_COVER_GT_7_5PP",report["failures"])

    def test_same_date_does_not_enter_fit_before_predictions(self):
        # A synthetic 36-game history is intentionally invalid as real NFL
        # evidence. It proves only the batch-before-update chronology.
        history=[]
        start=date(2022,9,1)
        for i in range(40):
            day=(start+timedelta(days=i)).isoformat()
            history.append(a.Game(day,f"h{i}","A","B",24,20,4,44))
        target_day="2023-09-01"
        history.extend([
            a.Game(target_day,"test1","A","B",24,20,4,44),
            a.Game(target_day,"test2","A","B",3,55,4,44),
        ])
        histories=[]
        original=a.fit_as_of
        def spy(prior):
            histories.append([g.day for g in prior])
            return original(prior)
        with patch.object(a,"fit_as_of",side_effect=spy):
            result=a.screen(history,design_years=frozenset({2023}))
        self.assertTrue(histories)
        self.assertTrue(all(target_day not in batch for batch in histories))
        self.assertEqual(result["counted_rows"],0)


if __name__=="__main__":
    unittest.main()
