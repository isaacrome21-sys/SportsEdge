"""NFL card game info (ESPN), season stats (nflverse) and line movement. Display only."""
from __future__ import annotations

from datetime import date
import json
import unittest

from sportsedge.nfl_card_game_info import (
    fetch_espn_game_info,
    first_card_lines,
    game_info_lines,
    movement_lines,
    season_stats,
    snapshot_marker,
)

SCOREBOARD = {
    "events": [
        {
            "id": "401",
            "date": "2026-10-11T17:00Z",
            "competitions": [
                {
                    "venue": {"fullName": "Lambeau Field", "indoor": False},
                    "weather": {"displayValue": "Sunny", "temperature": 73},
                    "broadcasts": [{"names": ["FOX"]}],
                    "competitors": [
                        {"homeAway": "home", "team": {"id": "9", "abbreviation": "GB"}, "records": [{"type": "total", "summary": "2-2"}]},
                        {"homeAway": "away", "team": {"id": "3", "abbreviation": "CHI"}, "records": [{"type": "total", "summary": "3-1"}]},
                    ],
                }
            ],
        },
        {
            "id": "402",
            "date": "2026-10-11T20:25Z",
            "competitions": [
                {
                    "venue": {"fullName": "SoFi Stadium", "indoor": True},
                    "competitors": [
                        {"homeAway": "home", "team": {"id": "14", "abbreviation": "LAR"}},
                        {"homeAway": "away", "team": {"id": "28", "abbreviation": "WSH"}},
                    ],
                }
            ],
        },
    ]
}
SUMMARY = {
    "injuries": [
        {"team": {"id": "3", "abbreviation": "CHI"}, "injuries": [
            {"athlete": {"displayName": "Kyle Monangai", "position": {"abbreviation": "RB"}}, "status": "Out"},
            {"athlete": {"displayName": "Caleb Williams", "position": {"abbreviation": "QB"}}, "status": "Questionable"},
            {"athlete": {"displayName": "Someone Healthy", "position": {"abbreviation": "WR"}}, "status": "Active"},
        ]},
        {"team": {"id": "9", "abbreviation": "GB"}, "injuries": [
            {"athlete": {"displayName": "Edgerrin Cooper", "position": {"abbreviation": "LB"}}, "status": "Injured Reserve"},
        ]},
    ]
}


def _getter(calls: list):
    def get(url: str) -> dict:
        calls.append(url)
        if "scoreboard?dates=20261011" in url:
            return SCOREBOARD
        if "scoreboard" in url:
            return {"events": []}
        if "event=401" in url:
            return SUMMARY
        raise TimeoutError("boom")
    return get


def _engine(spread_line=1.5, total=45.5, over=-110):
    return {"games": [{"away": "CHI", "home": "GB", "markets": [
        {"market": "spread", "line": spread_line, "away_or_over_price": -110, "home_or_under_price": -110},
        {"market": "total", "line": total, "away_or_over_price": over, "home_or_under_price": -110},
        {"market": "moneyline", "line": None, "away_or_over_price": -125, "home_or_under_price": 105},
        {"market": "pass_yards", "line": 200.5, "player": "Tyson Bagent", "away_or_over_price": -110, "home_or_under_price": -110},
    ]}]}


class GameInfoTests(unittest.TestCase):
    def test_espn_info_matches_teams_and_filters_injuries(self):
        calls: list = []
        out = fetch_espn_game_info([{"away": "CHI", "home": "GB"}, {"away": "WAS", "home": "LAR"}], date(2026, 10, 11), getter=_getter(calls))
        gb = out["games"]["CHI@GB"]
        self.assertEqual(gb["kickoff"], "Sun Oct 11, 1:00 PM ET")
        self.assertEqual(gb["records"], {"CHI": "3-1", "GB": "2-2"})
        self.assertEqual(gb["weather"], "Sunny, 73°F")
        self.assertEqual([r["name"] for r in gb["injuries"]["CHI"]], ["Caleb Williams", "Kyle Monangai"])  # QB first; Active dropped
        self.assertNotIn("GB", gb["injuries"])  # IR is not shown
        la = out["games"]["WAS@LAR"]  # ESPN WSH -> WAS
        self.assertEqual(la["weather"], "Indoors")
        self.assertIsNone(la["injuries"])  # summary failed -> explicitly "not retrieved", never invented
        self.assertTrue(out["errors"])

    def test_render_lines_only_show_retrieved_facts(self):
        info = fetch_espn_game_info([{"away": "CHI", "home": "GB"}], date(2026, 10, 11), getter=_getter([]))["games"]["CHI@GB"]
        md = "\n".join(game_info_lines({"away": "CHI", "home": "GB", "context": {"game_info": info}}))
        self.assertIn("Sun Oct 11, 1:00 PM ET · Lambeau Field · FOX", md)
        self.assertIn("CHI injury report: Caleb Williams QB **QUESTIONABLE**; Kyle Monangai RB **OUT**", md)
        self.assertIn("GB injury report: no Out/Doubtful/Questionable listed", md)
        self.assertEqual(game_info_lines({"away": "CHI", "home": "GB", "context": {}}), [])

    def test_season_stats_strictly_prior_and_this_season(self):
        hist = [
            {"season": 2026, "date": "2026-09-13", "home": "GB", "away": "DET", "hs": 20, "as": 10},
            {"season": 2026, "date": "2026-09-20", "home": "MIN", "away": "GB", "hs": 30, "as": 17},
            {"season": 2025, "date": "2025-12-01", "home": "GB", "away": "MIN", "hs": 50, "as": 0},
            {"season": 2026, "date": "2026-10-11", "home": "GB", "away": "CHI", "hs": 1, "as": 0},
        ]
        self.assertEqual(season_stats(hist, "GB", 2026, date(2026, 10, 11)), {"games": 2, "record": "1-1", "ppg": 18.5, "papg": 20.0})
        self.assertIsNone(season_stats(hist, "CHI", 2026, date(2026, 10, 11)))


class LineMovementTests(unittest.TestCase):
    def test_marker_round_trip_and_moves(self):
        first_body = "**NFL card** — CHI @ GB\n\n### CHI @ GB\n- x\n" + snapshot_marker(_engine(), "2026-10-10T21:02:00-05:00")
        first = first_card_lines([
            {"body": "**NFL card** later", "created_at": "2026-10-11T15:00:00Z"},
            {"body": first_body, "created_at": "2026-10-11T02:02:00Z"},
            {"body": "fair-price check", "created_at": "2026-10-10T00:00:00Z"},
        ])
        self.assertEqual(first["observed_at"], "2026-10-10T21:02:00-05:00")
        moved = movement_lines(first, _engine(spread_line=2.5, total=46.5, over=-115), "CHI", "GB")
        self.assertEqual(len(moved), 1)
        self.assertIn("Oct 10 9:02 PM CT", moved[0])
        self.assertIn("Spread CHI +1.5 (-110) → +2.5 (-110)", moved[0])
        self.assertIn("Total 45.5 o-110/u-110 → 46.5 o-115/u-110", moved[0])
        self.assertNotIn("ML", moved[0])
        self.assertEqual(movement_lines(first, _engine(), "CHI", "GB"), ["- Line move since first card (Oct 10 9:02 PM CT): no change"])
        self.assertEqual(movement_lines(None, _engine(), "CHI", "GB"), [])

    def test_price_only_move_keeps_line(self):
        first = {"observed_at": "2026-10-11T02:36:41Z", "lines": {"CHI@GB": {"spread": [1.5, -115, -105], "total": [45.5, -110, -110]}}}
        moved = movement_lines(first, _engine(spread_line=1.5), "CHI", "GB")
        self.assertEqual(moved, ["- Line move since first card (Oct 10 9:36 PM CT): Spread CHI +1.5 price -115 → -110"])

    def test_old_cards_without_marker_are_parsed_from_text(self):
        body = (
            "**NFL card** — SEA @ DEN\n\n### SEA @ DEN\n"
            "- Spread SEA +3.5 -105 / DEN -3.5 -115: no pick: spreads held until a margin model is validated\n"
            "- LEAN (no proven edge, not a bet): Under 44.5 @ -110 · model EV +3.0%\n"
            "- Total 44.5 o-110 / u-110: no lean (model edge under 2% EV)\n"
            "- ML SEA +150 / DEN -180: no pick: no moneyline model yet\n"
        )
        first = first_card_lines([{"body": body, "created_at": "2026-10-11T03:56:00Z"}])
        self.assertEqual(first["lines"]["SEA@DEN"], {"spread": [3.5, -105, -115], "total": [44.5, -110, -110], "moneyline": [None, 150, -180]})


class EngineHookTests(unittest.TestCase):
    def test_attach_game_info_is_display_only_and_fails_soft(self):
        from sportsedge.nfl_card_game_info import attach_game_info
        games = [{"away": "CHI", "home": "GB", "picks": [], "leans": [], "context": {"sources": ["nflverse games"]}}]
        before = json.dumps({k: games[0][k] for k in ("picks", "leans")})
        attach_game_info(games, [], date(2026, 10, 11), fetch_espn=True, getter=_getter([]))
        self.assertEqual(games[0]["context"]["game_info"]["venue"], "Lambeau Field")
        self.assertIn("ESPN", games[0]["context"]["sources"])
        self.assertEqual(before, json.dumps({k: games[0][k] for k in ("picks", "leans")}))

        def broken(url: str) -> dict:
            raise OSError("down")
        games2 = [{"away": "CHI", "home": "GB", "picks": [], "leans": [], "context": {}}]
        attach_game_info(games2, [], date(2026, 10, 11), fetch_espn=True, getter=broken)
        self.assertNotIn("game_info", games2[0]["context"])


if __name__ == "__main__":
    unittest.main()
