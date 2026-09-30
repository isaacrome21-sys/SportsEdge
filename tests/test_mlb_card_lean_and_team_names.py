"""Candidate pitcher-win rows print LEAN; team-total rows show the team name.

Presentation only: no probability changes.
"""
import unittest

from sportsedge.mlb_myspari_own_model import myspari_rows, render_markdown, team_entity_names
from sportsedge.pitcher_record_win_engine import PITCHER_RECORD_WIN_ENGINE_VERSION


def _row(market, side, odds, model_p, *, line=None, entity="849841", fair=None, edge=None, version="shared_game_v8"):
    return {"game_id": "849841", "market": market, "entity_id": entity, "line": line, "side": side,
            "american_odds": odds, "model_p": model_p, "bet_status": "MODEL_CANDIDATE",
            "reason": "DEPLOYMENT_NOT_ELIGIBLE", "implied_probability": fair, "edge": edge,
            "engine_version": version, "mc_paths": 100000}


# Real-shaped #1273 Mahle to-record-win pair (Sept 30).
MAHLE_WIN = [
    _row("PITCHER_RECORD_WIN", "YES", 340, 0.277, line=0.0, entity="641835", fair=0.184, edge=0.093,
         version=PITCHER_RECORD_WIN_ENGINE_VERSION),
    _row("PITCHER_RECORD_WIN", "NO", -514, 0.723, line=0.0, entity="641835", fair=0.816, edge=-0.093,
         version=PITCHER_RECORD_WIN_ENGINE_VERSION),
]


class CandidateEngineLeanTests(unittest.TestCase):
    def test_pitcher_record_win_candidate_prints_lean_not_actionable(self):
        rows = myspari_rows({"results": MAHLE_WIN}, team_sides={"641835": "HOME"})
        yes = next(r for r in rows if r["side"] == "YES")
        self.assertEqual(yes["scored_status"], "LEAN")
        self.assertEqual(yes["star_rating"], 0)
        self.assertIn("CANDIDATE_ENGINE_LEAN_ONLY", yes["presentation_reason_codes"])
        self.assertEqual(yes["model_p_raw"], 0.277)  # probability untouched

    def test_game_lines_are_unaffected(self):
        rows = myspari_rows({"results": [
            _row("MONEYLINE", "AWAY", 120, 0.50, fair=0.44, edge=0.06),
            _row("MONEYLINE", "HOME", -142, 0.50, fair=0.56, edge=-0.06),
        ]})
        away = next(r for r in rows if r["side"] == "AWAY")
        self.assertEqual(away["scored_status"], "ACTIONABLE")


class TeamNameTests(unittest.TestCase):
    PAYLOAD = {
        "resolved_game": {"game_pk": 849841, "away_team": "Philadelphia Phillies", "home_team": "Atlanta Braves"},
        "market_resolution": [
            {"market_type": "TEAM_TOTAL", "entity_id": "144", "team_side": "HOME", "subject_name": None},
            {"market_type": "TEAM_TOTAL", "entity_id": "143", "team_side": "AWAY", "subject_name": None},
            {"market_type": "PITCHER_OUTS", "entity_id": "641835", "team_side": None, "subject_name": "Tyler Mahle"},
        ],
    }

    def test_team_ids_map_to_team_names(self):
        self.assertEqual(team_entity_names(self.PAYLOAD), {"144": "Atlanta Braves", "143": "Philadelphia Phillies"})

    def test_team_total_row_renders_team_name(self):
        rows = myspari_rows({"results": [
            _row("TEAM_TOTALS", "OVER", 105, 0.542, line=3.5, entity="144", fair=0.456, edge=0.086),
            _row("TEAM_TOTALS", "UNDER", -135, 0.458, line=3.5, entity="144", fair=0.544, edge=-0.086),
        ]}, names=team_entity_names(self.PAYLOAD))
        text = render_markdown(rows, header="t")
        self.assertIn("Atlanta Braves Team Totals Over 3.5", text)
        self.assertNotIn("| 144 Team Totals", text)


if __name__ == "__main__":
    unittest.main()
