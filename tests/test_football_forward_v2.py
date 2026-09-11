from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.core.clv.football_forward_v2 import (
    CLOSE_DEFINITION_ID,
    POLICY_PATH,
    POLICY_SHA256,
    FootballForwardV2Error,
    SPORT_KEYS,
    build_close_record,
    coverage,
    load_forward_policy,
    plan_due_bulk_sports,
    power_fair_pair,
    validate_candidate,
)

ROOT = Path(__file__).resolve().parents[1]


class FootballForwardV2Tests(unittest.TestCase):
    def candidate(
        self,
        *,
        sport="CFB",
        decision_id="d1",
        start="2026-09-12T00:00:00Z",
        market="spreads",
    ):
        line = None if market == "h2h" else (-3.5 if market == "spreads" else 52.5)
        return {
            "decision_id": decision_id,
            "evidence_unit_id": "e" * 64,
            "sport": sport,
            "lane": f"game_{market}",
            "game_id": f"g-{decision_id}",
            "game_start_ts": start,
            "input_manifest_sha256": "f" * 64,
            "model_p": 0.58,
            "model_p_computed_at": "2026-09-11T22:35:00Z",
            "price_observed_at": "2026-09-11T22:30:00Z",
            "book": "draftkings",
            "price_source": "API",
            "selected_price": -110,
            "opposite_price": -110,
            "candidate_label": "LIKE",
            "certification_status": "CANDIDATE",
            "qualifying_threshold_id": "FOOTBALL_GAME_THRESHOLDS_V1",
            "qualifies_for_evidence": True,
            "actual_bet_placed": False,
            "kelly_fraction_information_only": 0.04,
            "market": market,
            "side": "HOME" if market != "totals" else "OVER",
            "line_at_decision": line,
        }

    def close(self, row=None, *, observed_at="2026-09-11T23:50:00Z"):
        candidate = row or self.candidate()
        market = candidate["market"]
        line = candidate["line_at_decision"]
        if market == "spreads":
            selected_line, opposite_line = line, -line
        elif market == "totals":
            selected_line = opposite_line = line
        else:
            selected_line = opposite_line = None
        return build_close_record(
            candidate=candidate,
            observed_at=observed_at,
            selected_price=-108,
            opposite_price=-112,
            selected_line=selected_line,
            opposite_line=opposite_line,
            snapshot_sha256="a" * 64,
        )

    def test_policy_covers_nfl_and_cfb_and_is_not_activated(self):
        p = json.loads((ROOT / "config/football_forward_capture_policy_v2.json").read_text())
        self.assertEqual(SPORT_KEYS["NFL"], "americanfootball_nfl")
        self.assertEqual(SPORT_KEYS["CFB"], "americanfootball_ncaaf")
        self.assertEqual(p["shared_evidence_contract"], "SPORTSEDGE_EVIDENCE_UNIT_V1")
        self.assertEqual(p["close_definition_id"], CLOSE_DEFINITION_ID)
        self.assertEqual(p["devig_method"], "POWER_V1")
        self.assertTrue(p["same_threshold_required_for_spreads_totals"])
        self.assertEqual(p["status"], "PROSPECTIVE_UNACTIVATED")
        self.assertFalse(p["promotion_authority"])
        self.assertFalse(p["evidence_clock_authority"])

    def test_candidate_must_satisfy_shared_ws0_contract(self):
        row = self.candidate()
        checked = validate_candidate(row)
        self.assertEqual(checked["market"], "spreads")
        row.pop("model_p")
        with self.assertRaisesRegex(FootballForwardV2Error, "DECISION_FIELDS_MISSING:model_p"):
            validate_candidate(row)

    def test_legacy_nfl_row_is_not_reinterpreted(self):
        legacy = {
            "decision_ts": "2026-09-11T22:30:00Z",
            "game_start_ts": "2026-09-12T00:00:00Z",
            "game_id": "n1",
            "sport": "NFL",
            "market": "spreads",
            "side": "HOME",
            "book": "draftkings",
            "line_at_decision": -3.5,
            "price_at_decision": -110,
            "gate_result": "SHADOW_QUALIFIED",
        }
        with self.assertRaisesRegex(FootballForwardV2Error, "DECISION_FIELDS_MISSING"):
            validate_candidate(legacy)

    def test_decision_must_be_formed_inside_frozen_window(self):
        row = self.candidate()
        row["model_p_computed_at"] = "2026-09-11T21:30:00Z"
        row["price_observed_at"] = "2026-09-11T21:30:00Z"
        with self.assertRaisesRegex(FootballForwardV2Error, "DECISION_OUTSIDE_WINDOW"):
            validate_candidate(row)

    def test_bulk_plan_costs_one_call_per_due_sport_not_per_game(self):
        now = datetime(2026, 9, 11, 23, 45, tzinfo=timezone.utc)
        rows = [
            self.candidate(sport="CFB", decision_id="c1"),
            self.candidate(sport="CFB", decision_id="c2"),
            self.candidate(sport="NFL", decision_id="n1"),
        ]
        plan = plan_due_bulk_sports(rows, [], now=now)
        self.assertEqual(plan["provider_request_count"], 2)
        self.assertEqual(plan["due_sports"], ["CFB", "NFL"])
        self.assertEqual(plan["due_decision_ids"]["CFB"], ["c1", "c2"])
        self.assertEqual(plan["policy_sha256"], POLICY_SHA256)

    def test_power_devig_is_not_proportional_when_prices_are_asymmetric(self):
        p1, p2 = power_fair_pair(-150, +125)
        raw1 = (150 / 250) / ((150 / 250) + (100 / 225))
        self.assertAlmostEqual(p1 + p2, 1.0, places=12)
        self.assertNotAlmostEqual(p1, raw1, places=8)

    def test_close_record_is_shared_contract_valid_and_same_threshold(self):
        row = self.candidate()
        close = self.close(row)
        self.assertEqual(len(close["close_id"]), 64)
        self.assertEqual(close["decision_id"], "d1")
        self.assertEqual(close["devig_method"], "POWER_V1")
        self.assertEqual(close["close_definition_id"], CLOSE_DEFINITION_ID)
        self.assertEqual(close["selected_line"], -3.5)
        self.assertEqual(close["opposite_line"], 3.5)
        self.assertEqual(close["policy_sha256"], POLICY_SHA256)

        with self.assertRaisesRegex(FootballForwardV2Error, "ORIGINAL_THRESHOLD_MISMATCH"):
            build_close_record(
                candidate=row,
                observed_at="2026-09-11T23:50:00Z",
                selected_price=-108,
                opposite_price=-112,
                selected_line=-4.0,
                opposite_line=4.0,
                snapshot_sha256="b" * 64,
            )

    def test_total_close_requires_same_threshold_on_both_sides(self):
        row = self.candidate(market="totals")
        with self.assertRaisesRegex(FootballForwardV2Error, "CLOSE_PAIR_LINE_MISMATCH"):
            build_close_record(
                candidate=row,
                observed_at="2026-09-11T23:50:00Z",
                selected_price=-110,
                opposite_price=-110,
                selected_line=52.5,
                opposite_line=53.0,
                snapshot_sha256="b" * 64,
            )

    def test_close_record_rejects_bad_snapshot_hash_and_wrong_window(self):
        row = self.candidate()
        with self.assertRaisesRegex(FootballForwardV2Error, "CLOSE_SNAPSHOT_SHA_INVALID"):
            build_close_record(
                candidate=row,
                observed_at="2026-09-11T23:50:00Z",
                selected_price=-108,
                opposite_price=-112,
                selected_line=-3.5,
                opposite_line=3.5,
                snapshot_sha256="not-a-sha",
            )
        with self.assertRaisesRegex(FootballForwardV2Error, "CLOSE_OUTSIDE_WINDOW"):
            self.close(row, observed_at="2026-09-11T23:30:00Z")

    def test_coverage_keeps_misses_in_denominator_and_rejects_duplicates(self):
        d1 = self.candidate(decision_id="d1")
        d2 = self.candidate(decision_id="d2")
        close = self.close(d1)
        report = coverage([d1, d2], [close])
        self.assertEqual(report["eligible_candidates"], 2)
        self.assertEqual(report["captured_closes"], 1)
        self.assertEqual(report["missed_closes"], 1)
        self.assertEqual(report["coverage"], 0.5)
        self.assertEqual(report["policy_sha256"], POLICY_SHA256)
        with self.assertRaisesRegex(FootballForwardV2Error, "DUPLICATE_CLOSE"):
            coverage([d1, d2], [close, close])

    def test_orphan_close_fails_closed(self):
        row = self.candidate(decision_id="d1")
        close = self.close(row)
        close["decision_id"] = "unknown"
        with self.assertRaisesRegex(FootballForwardV2Error, "ORPHAN_CLOSE"):
            coverage([row], [close])

    def test_close_policy_hash_tamper_fails_closed(self):
        row = self.candidate(decision_id="d1")
        close = self.close(row)
        close["policy_sha256"] = "0" * 64
        with self.assertRaisesRegex(FootballForwardV2Error, "POLICY_SHA_MISMATCH"):
            coverage([row], [close])

    def test_one_sided_candidate_is_rejected_from_v2_capture(self):
        row = self.candidate()
        row["opposite_price"] = None
        with self.assertRaisesRegex(FootballForwardV2Error, "V2_INELIGIBLE_ONE_SIDED"):
            validate_candidate(row)


class FootballForwardV2PolicyAuthorityTests(unittest.TestCase):
    def test_exported_policy_sha_binds_exact_committed_bytes(self):
        self.assertEqual(POLICY_SHA256, sha256(POLICY_PATH.read_bytes()).hexdigest())

    def test_loader_derives_runtime_windows_from_policy_bytes(self):
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        payload["decision_window_minutes_before_start"]["min"] = 46
        payload["close_window_minutes_before_start"]["max"] = 19
        encoded = json.dumps(payload, sort_keys=True) + "\n"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(encoded, encoding="utf-8")
            loaded = load_forward_policy(path)
        self.assertEqual(loaded["_decision_min"], 46)
        self.assertEqual(loaded["_close_max"], 19)
        self.assertEqual(loaded["_sha256"], sha256(encoded.encode()).hexdigest())

    def test_policy_activation_cannot_happen_by_config_only(self):
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        payload["status"] = "ACTIVE"
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(FootballForwardV2Error, "ACTIVATION_REQUIRES_CODE_REVIEW"):
                load_forward_policy(path)

    def test_policy_rejects_unsupported_market_surface(self):
        payload = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        payload["markets"].append("player_props")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "policy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(FootballForwardV2Error, "POLICY_MARKETS_UNSUPPORTED"):
                load_forward_policy(path)


if __name__ == "__main__":
    unittest.main()
