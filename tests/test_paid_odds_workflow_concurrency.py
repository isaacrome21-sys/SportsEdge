from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
GLOBAL_GROUP = "group: sportsedge-paid-odds-api"
NO_CANCEL = "cancel-in-progress: false"

# These are the workflows/jobs currently allowed to make paid The Odds API
# requests. Keeping the list explicit makes additions reviewable: a new paid
# lane must opt into the same account-wide GitHub Actions concurrency group.
PAID_WORKFLOWS = (
    "archive-mlb-game-odds.yml",
    "archive-mlb-game-odds-failover.yml",
    "mlb-additional-pit-archive.yml",
    "auto-mlb.yml",
    "mlb-provider-freeze-capture.yml",
    "mlb-authentic-provider-freeze.yml",
    "archive-provider-acceptance-probe.yml",
    "mlb-v8-evidence.yml",
    "run-it-control-plane.yml",
    "live-full-model-expansion.yml",
    "football-nfl-forward-clv-collection.yml",
)


class PaidOddsWorkflowConcurrencyTest(unittest.TestCase):
    def _read(self, name: str) -> str:
        path = WORKFLOWS / name
        self.assertTrue(path.is_file(), f"paid workflow missing: {name}")
        return path.read_text(encoding="utf-8")

    def test_every_paid_workflow_uses_account_wide_queue(self) -> None:
        for name in PAID_WORKFLOWS:
            with self.subTest(workflow=name):
                text = self._read(name)
                self.assertIn(
                    GLOBAL_GROUP,
                    text,
                    f"{name} can spend credits without the shared account lock",
                )
                self.assertIn(
                    NO_CANCEL,
                    text,
                    f"{name} may cancel an in-flight paid capture",
                )

    def test_authentic_freeze_selects_key_before_single_capture(self) -> None:
        text = self._read("mlb-authentic-provider-freeze.yml")
        capture = "python scripts/capture_mlb_odds_api_freeze.py"
        self.assertEqual(text.count(capture), 1)
        selection_end = "done\n          if [[ -z \"$selected_key\" ]]"
        self.assertIn(selection_end, text)
        self.assertLess(text.index(selection_end), text.index(capture))
        self.assertIn(
            "MLB_AUTHENTIC_PROVIDER_CAPTURE_FAILED_TERMINAL_NO_KEY_ROTATION",
            text,
        )

    def test_acceptance_probe_never_fans_out_after_provider_failure(self) -> None:
        text = self._read("archive-provider-acceptance-probe.yml")
        self.assertIn("name, key = configured[0]", text)
        self.assertEqual(text.count("urlopen("), 1)
        self.assertIn("'rotation_attempted':False", text)
        self.assertIn("'key_rotation_after_provider_failure':False", text)

    def test_live_diagnostic_uses_only_first_configured_key(self) -> None:
        text = self._read("live-full-model-expansion.yml")
        self.assertIn("name, key = configured[0]", text)
        self.assertEqual(text.count("urlopen("), 1)
        self.assertIn("'rotation_attempted': False", text)
        self.assertIn(
            "if: steps.acquisition.outputs.exit_code == '0' && steps.diagnostic.outputs.exit_code == '0'",
            text,
        )


if __name__ == "__main__":
    unittest.main()
