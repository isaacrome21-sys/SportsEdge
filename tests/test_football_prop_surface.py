from __future__ import annotations

import json
from pathlib import Path
import unittest

from sportsedge.football_prop_run_machine import PROVIDER_MARKET_TO_STAT
from sportsedge.football_prop_surface import require_executable_prop_surface


class FootballPropSurfaceTests(unittest.TestCase):
    def test_nfl_and_cfb_surface_is_runtime_bound_but_promotion_blocked(self):
        for sport in ("NFL", "CFB"):
            spec = require_executable_prop_surface(sport)
            self.assertEqual(spec["engine_state"], "IMPLEMENTED_FAIL_CLOSED")
            self.assertEqual(spec["promotion_state"], "BLOCKED_EVIDENCE_REQUIRED")

    def test_declared_provider_surface_matches_run_machine_exactly(self):
        payload = json.loads(Path("config/football_prop_engine_surface.json").read_text())
        self.assertEqual(
            set(payload["implemented_ab_markets"].values()),
            set(PROVIDER_MARKET_TO_STAT),
        )
        self.assertIn("targets", payload["explicit_no_engine"])
        self.assertIn("first_td", payload["explicit_no_engine"])

    def test_freeze_registries_are_truthfully_unfrozen(self):
        for sport in ("nfl", "cfb"):
            row = json.loads(Path(f"config/{sport}_prop_model_freeze.json").read_text())
            self.assertEqual(row["status"], "UNFROZEN")
            self.assertIsNone(row["artifact_sha256"])
            self.assertFalse((Path(row["artifact_path"])).is_file())


if __name__ == "__main__":
    unittest.main()
