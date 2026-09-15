from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from scripts.capture_nfl_attempt9_prospective_predictions import (
    _canonical_sha,
    capture,
)


FEATURES = [
    "home_points_for",
    "home_points_against",
    "away_points_for",
    "away_points_against",
    "home_net",
    "away_net",
]
HISTORY_DATES = [
    "2025-09-07",
    "2025-09-14",
    "2025-09-21",
    "2025-09-28",
    "2025-10-05",
]


def _artifact() -> dict:
    artifact = {
        "schema_version": "SPORTSEDGE_NFL_ATTEMPT9_RUNTIME_ARTIFACT_V1",
        "status": "RECONSTRUCTED_FROZEN_OWNER_RUNTIME_NOT_MODEL_P",
        "candidate": {
            "selected_attempt": 9,
            "feature_set": "exponential_recency_weighted_baseline",
            "decay": 0.85,
            "training_seasons": [2010, 2016],
            "historical_holdout_seasons": [2017, 2019],
            "feature_names": FEATURES,
        },
        "source": {"sha256": "a" * 64},
        "frozen_selection_provenance": {},
        "runtime": {
            "targets": {
                "margin": {
                    "feature_mean": [0.0] * 6,
                    "feature_std": [1.0] * 6,
                    "coefficients": [0.0] * 6,
                    "intercept": 3.5,
                },
                "total": {
                    "feature_mean": [0.0] * 6,
                    "feature_std": [1.0] * 6,
                    "coefficients": [0.0] * 6,
                    "intercept": 45.0,
                },
            }
        },
        "authority": {
            "creates_model_p": False,
            "promotion_authority": False,
            "truth_gate_pass": False,
            "official_authority": False,
            "staking_authority": False,
            "market_prices_used_as_features": False,
        },
        "use": "PROSPECTIVE_RAW_MARGIN_AND_TOTAL_FORECASTS_ONLY_UNTIL_SEPARATE_PROBABILITY_AND_PROMOTION_CONTRACT_EARNS_AUTHORITY",
    }
    artifact["artifact_sha256"] = _canonical_sha(artifact)
    return artifact


def _write_schedule(path: Path) -> None:
    fieldnames = [
        "game_id", "season", "week", "game_type", "gameday", "gametime",
        "home_team", "away_team", "home_score", "away_score",
    ]
    rows = []
    for index, gameday in enumerate(HISTORY_DATES):
        rows.append({
            "game_id": f"A-{index}", "season": "2025", "week": str(index + 1),
            "game_type": "REG", "gameday": gameday, "gametime": "13:00",
            "home_team": "A", "away_team": f"X{index}", "home_score": str(20 + index), "away_score": str(10 + index),
        })
        rows.append({
            "game_id": f"B-{index}", "season": "2025", "week": str(index + 1),
            "game_type": "REG", "gameday": gameday, "gametime": "16:00",
            "home_team": f"Y{index}", "away_team": "B", "home_score": str(14 + index), "away_score": str(24 + index),
        })
    rows.append({
        "game_id": "2026_02_B_A", "season": "2026", "week": "2",
        "game_type": "REG", "gameday": "2026-09-20", "gametime": "13:00",
        "home_team": "A", "away_team": "B", "home_score": "", "away_score": "",
    })
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class NFLAttempt9ProspectiveCaptureTests(unittest.TestCase):
    def test_first_write_is_raw_only_and_immutable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            schedule = root / "games.csv"
            output = root / "predictions"
            _write_schedule(schedule)
            artifact = _artifact()
            captured = datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc)

            first = capture(
                artifact=artifact,
                schedule=schedule,
                output_dir=output,
                capture_code_git_sha="b" * 40,
                captured=captured,
                horizon_days=9,
            )
            self.assertEqual(first["new_prediction_count"], 1)
            record = json.loads((output / "2026_02_B_A.json").read_text())
            self.assertEqual(record["raw_predicted_home_margin"], 3.5)
            self.assertEqual(record["raw_predicted_game_total"], 45.0)
            self.assertFalse(record["market_price_used"])
            self.assertFalse(record["model_p_created"])
            self.assertFalse(record["promotion_authority"])
            self.assertFalse(record["truth_gate_pass"])
            self.assertFalse(record["official_authority"])
            self.assertFalse(record["staking_authority"])
            self.assertNotIn("edge", record)
            self.assertNotIn("stake", record)
            self.assertNotIn("probability", record)

            before = (output / "2026_02_B_A.json").read_bytes()
            second = capture(
                artifact=artifact,
                schedule=schedule,
                output_dir=output,
                capture_code_git_sha="c" * 40,
                captured=captured,
                horizon_days=9,
            )
            after = (output / "2026_02_B_A.json").read_bytes()
            self.assertEqual(second["new_prediction_count"], 0)
            self.assertEqual(second["skipped_existing_count"], 1)
            self.assertEqual(before, after)

    def test_tampered_runtime_artifact_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            schedule = root / "games.csv"
            _write_schedule(schedule)
            artifact = _artifact()
            artifact["runtime"]["targets"]["margin"]["intercept"] = 999.0
            with self.assertRaisesRegex(ValueError, "ARTIFACT_SHA_MISMATCH"):
                capture(
                    artifact=artifact,
                    schedule=schedule,
                    output_dir=root / "predictions",
                    capture_code_git_sha="d" * 40,
                    captured=datetime(2026, 9, 15, 18, 0, tzinfo=timezone.utc),
                    horizon_days=9,
                )


if __name__ == "__main__":
    unittest.main()
