from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import unittest

from sportsedge.props_market_binding_stage7 import (
    NO_VIG_ONE_SIDED,
    bind_prop_market_with_attestation,
)
from sportsedge.props_pit_stage5 import pit_record_sha256, validate_pit_inputs
from sportsedge.props_validation_provenance_stage6 import (
    build_bound_validation_attestation,
    validation_attestation_sha256,
    verify_validation_attestation,
)

CODE_SHA = "c" * 40
MODEL_ID = "nfl_prop_research_model"
MODEL_VERSION = "v1"
ARTIFACT_A = "a" * 64
ARTIFACT_B = "b" * 64
UTC = timezone.utc


def _iso(value: datetime) -> str:
    return value.isoformat()


def _pit(index: int) -> dict:
    event = datetime(2026, 1, 9 + index, 18, 0, tzinfo=UTC)
    asof = event - timedelta(hours=6)
    return {
        "asof_ts": _iso(asof),
        "event_start_ts": _iso(event),
        "source_id": f"source-{index}",
        "entity_id": f"player-{index}",
        "availability_status": "ACTIVE",
        "snap_share": 0.70,
        "role_share": 0.25,
        "depth_status": "STARTER",
        "qb_status": "CONFIRMED",
        "weather_status": "KNOWN",
        "opponent_feature_asof_ts": _iso(asof - timedelta(hours=1)),
    }


def _fixture():
    predictions = []
    outcomes = []
    pits = {}
    probabilities = (0.10, 0.30, 0.70, 0.90)
    realized = (0, 0, 1, 1)
    for index, (probability, outcome) in enumerate(zip(probabilities, realized), start=1):
        pit = _pit(index)
        pits[f"p{index}"] = pit
        fold = "F1" if index <= 2 else "F2"
        if fold == "F1":
            train_cutoff = "2025-12-31T00:00:00+00:00"
            calibration_cutoff = "2025-12-30T00:00:00+00:00"
            artifact = ARTIFACT_A
        else:
            train_cutoff = "2026-01-11T00:00:00+00:00"
            calibration_cutoff = "2026-01-10T00:00:00+00:00"
            artifact = ARTIFACT_B
        predictions.append({
            "prediction_id": f"p{index}",
            "event_id": f"g{index}",
            "entity_id": pit["entity_id"],
            "market_id": "player_anytime_td",
            "fold_id": fold,
            "model_id": MODEL_ID,
            "model_version": MODEL_VERSION,
            "code_git_sha": CODE_SHA,
            "model_artifact_sha256": artifact,
            "pit_record_sha256": pit_record_sha256("NFL", pit),
            "prediction_asof_ts": pit["asof_ts"],
            "event_start_ts": pit["event_start_ts"],
            "train_cutoff_ts": train_cutoff,
            "calibration_fit_cutoff_ts": calibration_cutoff,
            "model_probability": probability,
        })
        outcomes.append({
            "prediction_id": f"p{index}",
            "outcome": outcome,
            "outcome_observed_at_ts": _iso(
                datetime.fromisoformat(pit["event_start_ts"]) + timedelta(hours=4)
            ),
        })
    training = {
        "F1": ["train-g0", "train-g00"],
        "F2": ["g1", "g2", "train-g3"],
    }
    return predictions, outcomes, pits, training


def _build(*, predictions=None, outcomes=None, pits=None, training=None, **overrides):
    base_predictions, base_outcomes, base_pits, base_training = _fixture()
    kwargs = {
        "predictions": base_predictions if predictions is None else predictions,
        "outcomes": base_outcomes if outcomes is None else outcomes,
        "pit_records": base_pits if pits is None else pits,
        "fold_training_event_ids": base_training if training is None else training,
        "sport": "NFL",
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "code_git_sha": CODE_SHA,
        "min_n": 4,
        "ece_max": 1.0,
        "max_bin_deviation_max": 1.0,
        "slope_min": -10.0,
        "slope_max": 10.0,
        "intercept_abs_max": 10.0,
    }
    kwargs.update(overrides)
    return build_bound_validation_attestation(**kwargs)


class PropsValidationProvenanceStage6Tests(unittest.TestCase):
    def test_stage5_pit_hash_is_canonical_and_value_sensitive(self):
        pit = _pit(1)
        reversed_pit = dict(reversed(list(pit.items())))
        self.assertEqual(pit_record_sha256("NFL", pit), pit_record_sha256("NFL", reversed_pit))
        changed = dict(pit, snap_share=0.71)
        self.assertNotEqual(pit_record_sha256("NFL", pit), pit_record_sha256("NFL", changed))
        validated = validate_pit_inputs("NFL", pit)
        self.assertEqual(validated["pit_record_sha256"], pit_record_sha256("NFL", pit))

    def test_valid_multifold_attestation_is_hash_bound_and_zero_authority(self):
        attestation = _build()
        verified = verify_validation_attestation(attestation)
        self.assertTrue(verified["passed"])
        self.assertEqual(verified["status"], "PASS")
        self.assertEqual(verified["authority"], "RESEARCH_ONLY")
        self.assertEqual(verified["prediction_count"], 4)
        self.assertEqual(verified["fold_order"], ["F1", "F2"])
        self.assertTrue(verified["pit_hash_binding"])
        self.assertTrue(verified["training_membership_binding"])
        self.assertTrue(verified["separate_outcome_binding"])
        self.assertFalse(verified["can_create_model_p"])
        self.assertFalse(verified["can_promote"])
        self.assertFalse(verified["staking_authority"])
        self.assertFalse(verified["official_authority"])
        self.assertEqual(verified["artifact_sha256"], validation_attestation_sha256(verified))
        self.assertEqual(len(verified["fold_contracts"]["F1"]["training_event_ids_sha256"]), 64)

    def test_pit_hash_tamper_fails_closed(self):
        predictions, outcomes, pits, training = _fixture()
        predictions[0]["pit_record_sha256"] = "9" * 64
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_PIT_HASH_MISMATCH:p1"):
            _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)

    def test_model_identity_is_required_per_prediction(self):
        for field, value, reason in (
            ("model_id", "other", "BOUND_VALIDATION_MODEL_ID_MISMATCH:p1"),
            ("model_version", "v2", "BOUND_VALIDATION_MODEL_VERSION_MISMATCH:p1"),
            ("code_git_sha", "d" * 40, "BOUND_VALIDATION_CODE_SHA_MISMATCH:p1"),
        ):
            predictions, outcomes, pits, training = _fixture()
            predictions[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, reason):
                _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)

    def test_test_event_cannot_appear_in_fold_training_population(self):
        predictions, outcomes, pits, training = _fixture()
        training["F1"].append("g1")
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_TEST_EVENT_IN_TRAINING:F1:g1"):
            _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)

    def test_prediction_and_validation_units_must_be_unique(self):
        predictions, outcomes, pits, training = _fixture()
        duplicate = deepcopy(predictions[0])
        predictions.insert(1, duplicate)
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_PREDICTION_DUPLICATE:p1"):
            _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)

        predictions, outcomes, pits, training = _fixture()
        predictions[1]["event_id"] = predictions[0]["event_id"]
        predictions[1]["entity_id"] = predictions[0]["entity_id"]
        pits["p2"]["entity_id"] = predictions[0]["entity_id"]
        predictions[1]["pit_record_sha256"] = pit_record_sha256("NFL", pits["p2"])
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_UNIT_DUPLICATE"):
            _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)

    def test_outcomes_are_separate_complete_and_unique(self):
        predictions, outcomes, pits, training = _fixture()
        missing = outcomes[1:]
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_OUTCOME_MISSING:p1"):
            _build(predictions=predictions, outcomes=missing, pits=pits, training=training)

        predictions, outcomes, pits, training = _fixture()
        duplicate = outcomes + [deepcopy(outcomes[0])]
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_OUTCOME_DUPLICATE:p1"):
            _build(predictions=predictions, outcomes=duplicate, pits=pits, training=training)

        predictions, outcomes, pits, training = _fixture()
        orphan = outcomes + [{"prediction_id": "orphan", "outcome": 0, "outcome_observed_at_ts": "2026-02-01T00:00:00+00:00"}]
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_ORPHAN_OUTCOMES:orphan"):
            _build(predictions=predictions, outcomes=orphan, pits=pits, training=training)

    def test_temporal_leakage_and_early_outcomes_fail_closed(self):
        for field, value in (
            ("train_cutoff_ts", "2026-01-10T13:00:00+00:00"),
            ("calibration_fit_cutoff_ts", "2026-01-10T13:00:00+00:00"),
            ("prediction_asof_ts", "2026-01-10T18:00:00+00:00"),
        ):
            predictions, outcomes, pits, training = _fixture()
            predictions[0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_TEMPORAL_LEAKAGE:p1"):
                _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)

        predictions, outcomes, pits, training = _fixture()
        outcomes[0]["outcome_observed_at_ts"] = "2026-01-10T17:59:59+00:00"
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_OUTCOME_OBSERVED_BEFORE_EVENT:p1"):
            _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)

    def test_fold_identity_reentry_and_cutoff_reversal_fail_closed(self):
        predictions, outcomes, pits, training = _fixture()
        predictions[1]["model_artifact_sha256"] = ARTIFACT_B
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_FOLD_IDENTITY_DRIFT:F1"):
            _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)

        predictions, outcomes, pits, training = _fixture()
        training["F2"] = ["g1", "train-g2", "train-g3"]
        predictions[1]["fold_id"] = "F2"
        predictions[1]["train_cutoff_ts"] = predictions[2]["train_cutoff_ts"]
        predictions[1]["calibration_fit_cutoff_ts"] = predictions[2]["calibration_fit_cutoff_ts"]
        predictions[1]["model_artifact_sha256"] = ARTIFACT_B
        predictions[2]["fold_id"] = "F1"
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_FOLD_REENTRY:F1"):
            _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)

        predictions, outcomes, pits, training = _fixture()
        for row in predictions[2:]:
            row["train_cutoff_ts"] = "2025-12-29T00:00:00+00:00"
            row["calibration_fit_cutoff_ts"] = "2025-12-28T00:00:00+00:00"
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_FOLD_CUTOFF_REVERSED"):
            _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)

    def test_attestation_tamper_and_fake_pass_flag_are_rejected(self):
        attestation = _build()
        tampered = deepcopy(attestation)
        tampered["metrics"]["brier"] += 0.001
        with self.assertRaisesRegex(ValueError, "VALIDATION_ATTESTATION_HASH_MISMATCH"):
            verify_validation_attestation(tampered)

        fake = deepcopy(attestation)
        fake["passed"] = "true"
        fake["artifact_sha256"] = validation_attestation_sha256(fake)
        with self.assertRaisesRegex(ValueError, "VALIDATION_ATTESTATION_PASS_FLAG_INVALID"):
            verify_validation_attestation(fake)

    def test_threshold_types_do_not_silently_coerce(self):
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_THRESHOLD_INVALID:min_n"):
            _build(min_n=True)
        with self.assertRaisesRegex(ValueError, "BOUND_VALIDATION_THRESHOLD_INVALID:ece_max"):
            _build(ece_max="1.0")

    def test_stage7_requires_verified_attestation_identity_and_preserves_one_sided_ev(self):
        attestation = _build()
        bound = bind_prop_market_with_attestation(
            sport="NFL",
            market="player_anytime_td",
            entity_id="player-live",
            model_probability=0.60,
            offered_odds=125,
            validation_attestation=attestation,
            model_id=MODEL_ID,
            model_version=MODEL_VERSION,
            code_git_sha=CODE_SHA,
        )
        self.assertEqual(bound.market_no_vig_probability, NO_VIG_ONE_SIDED)
        self.assertGreater(bound.expected_value_per_unit, 0.0)
        self.assertEqual(bound.validation_artifact_sha256, attestation["artifact_sha256"])
        self.assertEqual(bound.validation_model_id, MODEL_ID)
        self.assertEqual(bound.validation_model_version, MODEL_VERSION)
        self.assertEqual(bound.status, "RESEARCH_ONLY_POST_VALIDATION_BINDING")
        self.assertFalse(bound.official)
        self.assertFalse(bound.staking_authority)

        with self.assertRaisesRegex(ValueError, "VALIDATION_ATTESTATION_MODEL_VERSION_MISMATCH"):
            bind_prop_market_with_attestation(
                sport="NFL", market="player_anytime_td", entity_id="player-live",
                model_probability=0.60, offered_odds=125,
                validation_attestation=attestation, model_id=MODEL_ID,
                model_version="wrong", code_git_sha=CODE_SHA,
            )

    def test_stage7_rejects_hash_valid_failed_attestation(self):
        failed = _build(min_n=100)
        self.assertFalse(failed["passed"])
        self.assertEqual(failed["status"], "FAIL")
        with self.assertRaisesRegex(ValueError, "BLOCKED_VALIDATION_ATTESTATION_NOT_PASS"):
            bind_prop_market_with_attestation(
                sport="NFL", market="player_anytime_td", entity_id="player-live",
                model_probability=0.60, offered_odds=125,
                validation_attestation=failed, model_id=MODEL_ID,
                model_version=MODEL_VERSION, code_git_sha=CODE_SHA,
            )

    def test_stage7_cannot_reuse_validation_for_different_market(self):
        with self.assertRaisesRegex(ValueError, "VALIDATION_ATTESTATION_MARKET_MISMATCH"):
            bind_prop_market_with_attestation(
                sport="NFL", market="player_pass_yds", entity_id="player-live",
                model_probability=.60, offered_odds=125, validation_attestation=_build(),
                model_id=MODEL_ID, model_version=MODEL_VERSION, code_git_sha=CODE_SHA)

    def test_stage7_rejects_pooled_market_validation(self):
        predictions, outcomes, pits, training = _fixture()
        predictions[0]["market_id"] = "player_pass_yds"
        attestation = _build(predictions=predictions, outcomes=outcomes, pits=pits, training=training)
        with self.assertRaisesRegex(ValueError, "VALIDATION_ATTESTATION_MIXED_MARKETS_NOT_ADMITTED"):
            bind_prop_market_with_attestation(
                sport="NFL", market="player_anytime_td", entity_id="player-live",
                model_probability=.60, offered_odds=125, validation_attestation=attestation,
                model_id=MODEL_ID, model_version=MODEL_VERSION, code_git_sha=CODE_SHA)


if __name__ == "__main__":
    unittest.main()
