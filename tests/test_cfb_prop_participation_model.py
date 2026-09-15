from __future__ import annotations

import copy
import unittest

from sportsedge.sports.cfb.prop_participation_model import (
    CFBParticipationModelError,
    fit_cfb_participation_model,
    starter_retention_probability,
    validate_cfb_participation_artifact,
)

SOURCE_SHA = "a" * 64


def _row(
    index: int,
    *,
    group: str = "QB",
    quarter: int,
    clock: int,
    margin: float,
    starter: bool,
):
    return {
        "game_id": f"game-{index // 12}",
        "season": 2025,
        "week": 1 + (index // 24),
        "event_ts": f"2025-09-{1 + (index // 24):02d}T19:{index % 60:02d}:00+00:00",
        "position_group": group,
        "starter_on_play": starter,
        "quarter": quarter,
        "clock_seconds_remaining": clock,
        "score_margin": margin,
        "source_sha256": SOURCE_SHA,
    }


def _training_rows():
    rows = []
    i = 0
    # Competitive-state snaps: starter QB almost always remains on the field.
    for _ in range(36):
        rows.append(_row(i, quarter=2, clock=450, margin=3, starter=True)); i += 1
    for _ in range(4):
        rows.append(_row(i, quarter=2, clock=450, margin=3, starter=False)); i += 1
    # Late large leads: backups take the majority of QB snaps.
    for _ in range(8):
        rows.append(_row(i, quarter=4, clock=300, margin=28, starter=True)); i += 1
    for _ in range(32):
        rows.append(_row(i, quarter=4, clock=300, margin=28, starter=False)); i += 1
    # Late large deficits also increase substitution, but less sharply.
    for _ in range(18):
        rows.append(_row(i, quarter=4, clock=180, margin=-28, starter=True)); i += 1
    for _ in range(22):
        rows.append(_row(i, quarter=4, clock=180, margin=-28, starter=False)); i += 1
    return rows


class CFBPropParticipationModelTests(unittest.TestCase):
    def test_fit_is_deterministic_and_market_blind(self):
        rows = _training_rows()
        first = fit_cfb_participation_model(rows, min_rows_per_group=30)
        second = fit_cfb_participation_model(rows, min_rows_per_group=30)
        self.assertEqual(first, second)
        self.assertFalse(first["promotion_authority"])
        self.assertFalse(first["market_inputs_consumed"])
        self.assertEqual(first["validation_status"], "UNVALIDATED_CANDIDATE")
        self.assertEqual(first["training_row_count"], len(rows))
        self.assertEqual(validate_cfb_participation_artifact(first)["artifact_sha256"], first["artifact_sha256"])

    def test_large_late_lead_reduces_fitted_starter_retention(self):
        artifact = fit_cfb_participation_model(_training_rows(), min_rows_per_group=30)
        competitive = starter_retention_probability(
            artifact,
            position_group="QB",
            quarter=2,
            clock_seconds_remaining=450,
            score_margin=3,
        )
        blowout = starter_retention_probability(
            artifact,
            position_group="QB",
            quarter=4,
            clock_seconds_remaining=300,
            score_margin=28,
        )
        self.assertGreater(competitive, blowout)
        self.assertGreater(competitive, 0.5)
        self.assertLess(blowout, 0.5)

    def test_market_fields_are_rejected_at_training_boundary(self):
        row = _training_rows()[0]
        contaminated = dict(row)
        contaminated["spread"] = -21.5
        with self.assertRaisesRegex(
            CFBParticipationModelError,
            "CFB_PARTICIPATION_ROW_FIELD_FORBIDDEN:spread",
        ):
            fit_cfb_participation_model([contaminated] + _training_rows()[1:], min_rows_per_group=30)

    def test_artifact_tamper_fails_hash_binding(self):
        artifact = fit_cfb_participation_model(_training_rows(), min_rows_per_group=30)
        tampered = copy.deepcopy(artifact)
        tampered["position_coefficients"]["QB"][0] += 0.01
        with self.assertRaisesRegex(
            CFBParticipationModelError,
            "CFB_PARTICIPATION_ARTIFACT_SHA_MISMATCH",
        ):
            validate_cfb_participation_artifact(tampered)

    def test_missing_qb_model_fails_closed(self):
        rows = [
            _row(i, group="RB", quarter=2 if i < 20 else 4, clock=300, margin=3 if i < 20 else 28, starter=(i % 3 != 0))
            for i in range(40)
        ]
        with self.assertRaisesRegex(
            CFBParticipationModelError,
            "CFB_PARTICIPATION_QB_GROUP_REQUIRED",
        ):
            fit_cfb_participation_model(rows, min_rows_per_group=30)


if __name__ == "__main__":
    unittest.main()
