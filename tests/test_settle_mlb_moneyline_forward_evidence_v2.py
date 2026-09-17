import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.settle_mlb_moneyline_forward_evidence_v2 import (
    _evaluate_checkpoint,
    _load_policy,
    _student_t_quantile,
    settle_v2,
)
from sportsedge.mlb_moneyline_forward_lane import load_forward_lane_binding
from sportsedge.mlb_moneyline_paper_decision import freeze_paper_decision


ARTIFACT = "a" * 64


def write_json(path: Path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prediction(now, start, *, model_p=0.55):
    return {
        "promotion_authority": False,
        "market": "MONEYLINE",
        "game_pk": 123,
        "away_team_id": 10,
        "home_team_id": 20,
        "away_team": "Away Club",
        "home_team": "Home Club",
        "model_side": "HOME",
        "model_p": model_p,
        "market_blind": True,
        "feature_asof_ts": (now - timedelta(minutes=20)).isoformat(),
        "prediction_generated_at_utc": (now - timedelta(minutes=15)).isoformat(),
        "event_start_ts": start.isoformat(),
        "model_artifact_sha256": ARTIFACT,
    }


def quote(start, observed, *, home_odds=120, away_odds=-140, obs_id="entry"):
    return {
        "promotion_authority": False,
        "sportsbook": "draftkings",
        "provider_event_id": "dk-123",
        "capture_observation_id": obs_id,
        "home_team": "Home Club",
        "away_team": "Away Club",
        "scheduled_start_utc": start.isoformat(),
        "observed_at_utc": observed.isoformat(),
        "model_artifact_sha256": ARTIFACT,
        "raw_sha256": "b" * 64,
        "moneyline": {
            "status": "OK",
            "home_price_american": home_odds,
            "away_price_american": away_odds,
        },
    }


def source(observed_at):
    raw = b'{"gamePk":123,"status":"Final"}'
    return {
        "settlement": {
            "game_pk": 123,
            "status": "FINAL",
            "away_team_id": 10,
            "home_team_id": 20,
            "away_score": 3,
            "home_score": 5,
        },
        "source_uri": "https://statsapi.mlb.com/api/v1/schedule?sportId=1&gamePk=123",
        "observed_at_utc": observed_at.isoformat(),
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": raw,
    }


def checkpoint_row(index, binding, *, artifact=ARTIFACT, clv=0.01, roi=0.02, close=True):
    day = 1 + (index % 10)
    frozen = datetime(2026, 9, day, 18, 0, tzinfo=timezone.utc) + timedelta(seconds=index)
    row = {
        "status": "FORWARD_EVIDENCE_COMPLETE_V2",
        "state": "PAPER",
        "graded_bet": True,
        "evidence_counts": True,
        "stake_units": 0.0,
        "promotion_authority": False,
        "lane_id": binding["lane_id"],
        "lane_definition_sha256": binding["lane_definition_sha256"],
        "market_definition_sha256": binding["market_definition_sha256"],
        "policy_id": binding["policy_id"],
        "policy_sha256": binding["policy_sha256"],
        "policy_manifest_sha256": binding["policy_manifest_sha256"],
        "edge_floor_config_sha256": binding["edge_floor_config_sha256"],
        "model_artifact_sha256": artifact,
        "game_pk": 100000 + index,
        "slate_date": f"2026-09-{day:02d}",
        "decision_frozen_at_utc": frozen.isoformat(),
        "entry_home_odds": -110,
        "entry_away_odds": -110,
        "decision_provider_event_id": f"dk-{100000 + index}",
        "close_status": "AVAILABLE" if close else "MISSING",
        "close_home_odds": -115 if close else None,
        "close_away_odds": -105 if close else None,
        "clv_probability_points": clv if close else None,
        "settlement_status": "FINAL",
        "paper_roi_fraction_per_1u": roi,
    }
    return row


class SettlementV2RunnerTest(unittest.TestCase):
    def roots(self, base):
        root = Path(base)
        return (
            root / "predictions",
            root / "quotes",
            root / "decisions",
            root / "evidence",
            root / "raw",
            root / "checkpoints",
            root / "report.json",
        )

    def test_settles_only_pre_frozen_v2_bet(self):
        freeze_now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = freeze_now + timedelta(minutes=33)
        pred = prediction(freeze_now, start)
        entry = quote(start, freeze_now - timedelta(minutes=1), obs_id="entry")
        close = quote(start, start - timedelta(minutes=4), home_odds=-110, away_odds=-110, obs_id="close")
        decision = freeze_paper_decision(prediction=pred, quotes=[entry], now=freeze_now)
        self.assertEqual(decision["status"], "PAPER_BET_FROZEN")
        after = start + timedelta(hours=4)
        with tempfile.TemporaryDirectory() as tmp:
            predictions, quotes, decisions, evidence, raw, checkpoints, report = self.roots(tmp)
            write_json(predictions / "p.json", pred)
            write_json(quotes / "entry.json", entry)
            write_json(quotes / "close.json", close)
            write_json(decisions / "d.json", decision)
            result = settle_v2(
                prediction_root=predictions,
                quote_root=quotes,
                decision_root=decisions,
                output_root=evidence,
                raw_root=raw,
                checkpoint_root=checkpoints,
                report_path=report,
                now=after,
                settlement_fetcher=lambda game_pk: source(after),
            )
            files = list(evidence.rglob("*__v2.json"))
            self.assertEqual(len(files), 1)
            row = json.loads(files[0].read_text(encoding="utf-8"))
            raw_files = list(raw.rglob("*.json"))
        self.assertEqual(result["completed_v2_graded_bets"], 1)
        self.assertEqual(result["new_completed_v2_bets"], 1)
        self.assertEqual(result["close_rows_available"], 1)
        self.assertEqual(result["close_coverage"], 1.0)
        self.assertGreater(result["mean_clv_probability_points"], 0.0)
        self.assertEqual(result["next_checkpoint"], 50)
        self.assertEqual(result["checkpoint_evaluator_status"], "ACTIVE_FIXED_PREFIX_50_100_150")
        self.assertEqual(row["status"], "FORWARD_EVIDENCE_COMPLETE_V2")
        self.assertEqual(row["selected_side"], "HOME")
        self.assertIs(row["promotion_authority"], False)
        self.assertEqual(len(raw_files), 1)

    def test_paper_pass_does_not_fetch_or_enter_denominator(self):
        freeze_now = datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc)
        start = freeze_now + timedelta(minutes=33)
        pred = prediction(freeze_now, start, model_p=0.45)
        entry = quote(start, freeze_now - timedelta(minutes=1))
        decision = freeze_paper_decision(prediction=pred, quotes=[entry], now=freeze_now)
        self.assertEqual(decision["status"], "PAPER_PASS_FROZEN")
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            predictions, quotes, decisions, evidence, raw, checkpoints, report = self.roots(tmp)
            write_json(predictions / "p.json", pred)
            write_json(quotes / "q.json", entry)
            write_json(decisions / "d.json", decision)
            result = settle_v2(
                prediction_root=predictions,
                quote_root=quotes,
                decision_root=decisions,
                output_root=evidence,
                raw_root=raw,
                checkpoint_root=checkpoints,
                report_path=report,
                now=start + timedelta(hours=1),
                settlement_fetcher=lambda game_pk: calls.append(game_pk),
            )
        self.assertEqual(calls, [])
        self.assertEqual(result["paper_passes_frozen"], 1)
        self.assertEqual(result["completed_v2_graded_bets"], 0)
        self.assertEqual(result["new_completed_v2_bets"], 0)

    def test_legacy_completed_evidence_is_ignored_non_retroactively(self):
        with tempfile.TemporaryDirectory() as tmp:
            predictions, quotes, decisions, evidence, raw, checkpoints, report = self.roots(tmp)
            write_json(evidence / "legacy.json", {"status": "FORWARD_EVIDENCE_COMPLETE", "game_pk": 999})
            result = settle_v2(
                prediction_root=predictions,
                quote_root=quotes,
                decision_root=decisions,
                output_root=evidence,
                raw_root=raw,
                checkpoint_root=checkpoints,
                report_path=report,
                now=datetime(2026, 9, 20, 23, 0, tzinfo=timezone.utc),
                settlement_fetcher=lambda game_pk: self.fail("legacy row must not be fetched"),
            )
        self.assertEqual(result["legacy_non_v2_completed_rows_ignored"], 1)
        self.assertEqual(result["completed_v2_graded_bets"], 0)
        self.assertIs(result["promotion_authority"], False)

    def test_student_t_quantile_matches_known_df4_value(self):
        self.assertAlmostEqual(_student_t_quantile(0.975, 4), 2.776445, places=5)

    def test_checkpoint_50_can_only_emit_probation_candidate(self):
        binding = load_forward_lane_binding()
        policy = _load_policy()
        rows = [checkpoint_row(i, binding) for i in range(50)]
        result = _evaluate_checkpoint(rows, checkpoint=50, binding=binding, policy=policy)
        self.assertEqual(result["disposition"], "PROBATION_CANDIDATE")
        self.assertEqual(result["checkpoint_graded_count"], 50)
        self.assertEqual(result["clv_inference"]["interval_status"], "AVAILABLE")
        self.assertIs(result["promotion_authority"], False)
        self.assertIs(result["staking_change_allowed"], False)

    def test_checkpoint_150_stays_paper_until_warnings_are_cleared_or_signed_off(self):
        binding = load_forward_lane_binding()
        policy = _load_policy()
        rows = [checkpoint_row(i, binding) for i in range(150)]
        result = _evaluate_checkpoint(rows, checkpoint=150, binding=binding, policy=policy)
        self.assertGreater(result["clv_inference"]["clv_95_ci_lower_probability_points"], 0.0)
        self.assertEqual(result["disposition"], "PAPER_REQUIRED")
        self.assertIs(result["checks"]["warnings_cleared_or_signed_off"], False)
        self.assertIs(result["official_change_allowed"], False)

    def test_fixed_prefix_checkpoint_snapshot_is_create_only_and_artifact_scoped(self):
        binding = load_forward_lane_binding()
        with tempfile.TemporaryDirectory() as tmp:
            predictions, quotes, decisions, evidence, raw, checkpoints, report = self.roots(tmp)
            for index in range(50):
                write_json(evidence / f"row_{index:03d}.json", checkpoint_row(index, binding))
            result = settle_v2(
                prediction_root=predictions,
                quote_root=quotes,
                decision_root=decisions,
                output_root=evidence,
                raw_root=raw,
                checkpoint_root=checkpoints,
                report_path=report,
                now=datetime(2026, 9, 30, 23, 0, tzinfo=timezone.utc),
                settlement_fetcher=lambda game_pk: self.fail("precompleted rows must not refetch"),
            )
            paths = list(checkpoints.rglob("checkpoint_050.json"))
            self.assertEqual(len(paths), 1)
            first_bytes = paths[0].read_bytes()
            second = settle_v2(
                prediction_root=predictions,
                quote_root=quotes,
                decision_root=decisions,
                output_root=evidence,
                raw_root=raw,
                checkpoint_root=checkpoints,
                report_path=report,
                now=datetime(2026, 10, 1, 1, 0, tzinfo=timezone.utc),
                settlement_fetcher=lambda game_pk: self.fail("precompleted rows must not refetch"),
            )
            self.assertEqual(paths[0].read_bytes(), first_bytes)
        self.assertEqual(result["checkpoint_evaluations"][0]["disposition"], "PROBATION_CANDIDATE")
        self.assertEqual(len(result["new_checkpoint_snapshot_paths"]), 1)
        self.assertEqual(second["new_checkpoint_snapshot_paths"], [])


if __name__ == "__main__":
    unittest.main()
