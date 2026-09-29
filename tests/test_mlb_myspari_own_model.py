import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sportsedge.mlb_myspari_own_model import LABEL, myspari_rows, render_markdown


def _row(market, side, odds, model_p, *, line=None, entity="777", fair=None, edge=None, status="MODEL_CANDIDATE"):
    return {"game_id": "777", "market": market, "entity_id": entity, "line": line, "side": side,
            "american_odds": odds, "model_p": model_p, "bet_status": status, "reason": "DEPLOYMENT_NOT_ELIGIBLE",
            "implied_probability": fair, "edge": edge, "engine_version": "shared_game_v8", "mc_paths": 100000}


PAYLOAD = {
    "observed_at_utc": "2026-09-29T20:00:00+00:00",
    "resolved_game": {"game_pk": 777, "away_team": "Detroit Tigers", "home_team": "Cleveland Guardians",
                      "scheduled_start_utc": "2026-09-29T22:08:00+00:00"},
    "results": [
        _row("MONEYLINE", "AWAY", 120, 0.50, fair=0.44, edge=0.06),
        _row("MONEYLINE", "HOME", -142, 0.50, fair=0.56, edge=-0.06),
        _row("RUN_LINE", "AWAY", -165, 0.66, line=1.5, fair=0.60, edge=0.06),
        _row("RUN_LINE", "HOME", 140, 0.34, line=-1.5, fair=0.40, edge=-0.06),
        # integer total: engine model_p is unconditional, edge is on the non-push basis
        _row("TOTALS", "UNDER", -110, 0.45, line=7.0, fair=0.46, edge=0.04),
        _row("TOTALS", "OVER", -110, 0.45, line=7.0, fair=0.54, edge=-0.04),
        _row("PITCHER_K", "OVER", -115, 0.58, line=6.5, entity="669373", fair=0.52, edge=0.06),
        _row("PITCHER_K", "UNDER", -105, 0.42, line=6.5, entity="669373", fair=0.48, edge=-0.06),
        _row("HITS", "OVER", -200, None, line=0.5, entity="608070", status="BLOCKED"),
    ],
}


class OwnModelCardTests(unittest.TestCase):
    def test_uses_engine_probability_not_a_new_one(self):
        rows = myspari_rows(PAYLOAD)
        ml_away = next(r for r in rows if r["market"] == "MONEYLINE" and r["side"] == "AWAY")
        self.assertAlmostEqual(ml_away["model_p"], 0.50, places=9)  # engine value, unchanged
        self.assertEqual(ml_away["scored_status"], "ACTIONABLE")
        self.assertEqual(ml_away["label"], LABEL)

    def test_pairs_run_line_with_negated_line(self):
        rows = myspari_rows(PAYLOAD)
        rl_away = next(r for r in rows if r["market"] == "RUN_LINE" and r["side"] == "AWAY")
        self.assertIsNotNone(rl_away["market_p"])
        self.assertIn("POWER_V1_NO_VIG", rl_away["reason_codes"])

    def test_push_mass_recovered_for_integer_total(self):
        rows = myspari_rows(PAYLOAD)
        under = next(r for r in rows if r["market"] == "TOTALS" and r["side"] == "UNDER")
        self.assertAlmostEqual(under["model_p"], 0.5, places=9)
        self.assertAlmostEqual(under["push_p"], 0.1, places=9)

    def test_blocked_engine_row_stays_unpriced(self):
        rows = myspari_rows(PAYLOAD)
        hits = next(r for r in rows if r["market"] == "HITS")
        self.assertEqual(hits["scored_status"], "NO_MODEL")
        self.assertIsNone(hits["edge"])

    def test_missing_opposite_side_blocks(self):
        payload = {"results": [_row("MONEYLINE", "AWAY", 120, 0.5, fair=0.44, edge=0.06)]}
        rows = myspari_rows(payload)
        self.assertEqual(rows[0]["scored_status"], "BLOCKED")

    def test_render_and_script(self):
        rows = myspari_rows(PAYLOAD, names={"669373": "Tarik Skubal"})
        text = render_markdown(rows, header="t", notes=["n"])
        self.assertIn("Tarik Skubal", text)
        self.assertIn("Engine did not price", text)
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp) / "engine.json"
            engine.write_text(json.dumps(PAYLOAD))
            out = Path(tmp) / "out"
            subprocess.run([sys.executable, "scripts/render_mlb_myspari_card.py", "--engine-output", str(engine),
                            "--out-dir", str(out), "--as-of", "2026-09-29T20:30:00+00:00"], check=True,
                           capture_output=True)
            self.assertIn("SportsEdge MLB card", (out / "card.md").read_text())


if __name__ == "__main__":
    unittest.main()
