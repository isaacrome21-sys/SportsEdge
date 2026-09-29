import json
import os
import textwrap
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


class CeilingAndLabelTests(unittest.TestCase):
    def test_heavy_favorite_never_actionable(self):
        payload = {"results": [
            _row("RUN_LINE", "AWAY", -206, 0.80, line=1.5, fair=0.66, edge=0.14),
            _row("RUN_LINE", "HOME", 168, 0.20, line=-1.5, fair=0.34, edge=-0.14),
        ]}
        rows = myspari_rows(payload)
        fav = next(r for r in rows if r["side"] == "AWAY")
        self.assertEqual(fav["scored_status"], "PASS")
        self.assertIn("price > -165", render_markdown(rows, header="t"))

    def test_push_columns_explain_conditional_probability(self):
        text = render_markdown(myspari_rows(PAYLOAD), header="t")
        self.assertIn("Win p ex-push", text)
        self.assertIn("| 10.0% |", text)  # the integer-total push mass is shown, not hidden

    def test_input_board_note_names_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = Path(tmp) / "engine.json"
            engine.write_text(json.dumps(PAYLOAD))
            snap = Path(tmp) / "2026-09-29_dk_full_supplied.json"
            snap.write_text(json.dumps({"rows": [{}] * 17}))
            out = Path(tmp) / "out"
            subprocess.run([sys.executable, "scripts/render_mlb_myspari_card.py", "--engine-output", str(engine),
                            "--snapshot", str(snap), "--out-dir", str(out), "--as-of", "2026-09-29T20:30:00+00:00"],
                           check=True, capture_output=True)
            self.assertIn("2026-09-29_dk_full_supplied.json (17 rows", (out / "card.md").read_text())


class InputResolutionTests(unittest.TestCase):
    def resolve(self, files, *, event="workflow_dispatch", selected="", git_script="exit 1"):
        workflow = Path(".github/workflows/manual-mlb-snapshot.yml").read_text()
        block = workflow.split("      - name: Resolve input", 1)[1].split("        run: |\n", 1)[1]
        script = textwrap.dedent(block.split("\n      - name:", 1)[0])
        script = script.replace('${{ github.event_name }}', event)
        script = script.replace('RUN_DATE="$(TZ=America/Chicago date +%F)"', 'RUN_DATE="2026-09-28"')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in files:
                path = root / "manual_inputs/mlb" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('{}')
            (root / "bin").mkdir()
            git = root / "bin/git"
            git.write_text("#!/bin/bash\n" + git_script + "\n")
            git.chmod(0o755)
            output = root / "output"
            env = dict(os.environ, GITHUB_OUTPUT=str(output), DISPATCH_INPUT=selected,
                       EVENT_NAME=event, PUSH_BEFORE="old", PUSH_AFTER="new")
            env["PATH"] = str(root / "bin") + os.pathsep + env["PATH"]
            run = subprocess.run(["bash", "-c", script], cwd=root, env=env, capture_output=True, text=True)
            return run, output.read_text() if output.exists() else ""

    def test_same_day_fallback_is_ambiguous(self):
        run, _ = self.resolve(["2026-09-29_full.json", "2026-09-29_latest.json"])
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("AMBIGUOUS_MLB_SNAPSHOT", run.stderr)

    def test_earliest_future_date_wins(self):
        run, output = self.resolve(["2026-09-29_full.json", "2026-09-30_full.json"])
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("path=manual_inputs/mlb/2026-09-29_full.json", output)

    def test_dispatch_selects_full_board(self):
        selected = "manual_inputs/mlb/2026-09-29_full.json"
        run, output = self.resolve(["2026-09-29_full.json", "2026-09-29_latest.json"], selected=selected)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("path=" + selected, output)

    def test_push_diff_failure_is_not_a_fallback(self):
        run, _ = self.resolve(["2026-09-29_full.json"], event="push")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("MLB_INPUT_DIFF_FAILED", run.stderr)

    def test_multiple_changed_inputs_fail(self):
        run, _ = self.resolve(["2026-09-29_full.json", "2026-09-29_latest.json"], event="push",
            git_script="printf '%s\\n' manual_inputs/mlb/2026-09-29_full.json manual_inputs/mlb/2026-09-29_latest.json")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("AMBIGUOUS_CHANGED_MLB_SNAPSHOT", run.stderr)

    def test_push_uses_event_range(self):
        run, output = self.resolve(["2026-09-29_full.json", "2026-09-29_latest.json"], event="push",
            git_script='[[ "$*" == *"old new"* ]] || exit 3; echo manual_inputs/mlb/2026-09-29_full.json')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("path=manual_inputs/mlb/2026-09-29_full.json", output)


if __name__ == "__main__":
    unittest.main()
