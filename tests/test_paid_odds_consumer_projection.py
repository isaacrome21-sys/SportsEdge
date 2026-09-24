from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from scripts import audit_paid_odds_consumers as audit


class PaidOddsConsumerProjectionTests(unittest.TestCase):
    def test_repository_projection_is_complete_and_safe(self):
        report = audit.audit()
        self.assertEqual(report["state"], "PASS")
        self.assertEqual(report["confirmation_reserve_credits"], 76)
        self.assertEqual(report["required_concurrency_group"], "sportsedge-paid-odds-api")

    def test_forward_profiles_are_3_and_5_credits(self):
        projection = audit.load_json(audit.DEFAULT_PROJECTION)
        spec = projection["consumers"][".github/workflows/football-nfl-forward-clv-collection.yml"]
        policy = audit.load_json(audit.ROOT / spec["policy_file"])
        decision = audit.request_profile_cost(policy, spec["request_profiles"]["decision"])[0]
        close = audit.request_profile_cost(policy, spec["request_profiles"]["close"])[0]
        self.assertEqual(decision, 3)
        self.assertEqual(close, 5)
        self.assertEqual(policy["request_profiles"]["decision"]["minimum_remaining_before_call"], 79)
        self.assertEqual(policy["request_profiles"]["close"]["minimum_remaining_before_call"], 81)

    def test_archive_profile_is_3_credits_and_guarded(self):
        projection = audit.load_json(audit.DEFAULT_PROJECTION)
        spec = projection["consumers"][".github/workflows/closing-line-archive.yml"]
        policy = audit.load_json(audit.ROOT / spec["policy_file"])
        cost = audit.request_profile_cost(policy, spec["request_profiles"]["game_markets"])[0]
        self.assertEqual(cost, 3)
        self.assertTrue(policy["provider_budget_guard"]["enabled"])
        self.assertEqual(policy["provider_budget_guard"]["budget_path"], projection["provider_budget_path"])

    def test_manual_mlb_failover_profile_is_6_credits(self):
        projection = audit.load_json(audit.DEFAULT_PROJECTION)
        spec = projection["consumers"][".github/workflows/archive-mlb-game-odds-failover.yml"]
        policy = audit.load_json(audit.ROOT / spec["policy_file"])
        cost = audit.request_profile_cost(policy, spec["request_profiles"]["game_odds"])[0]
        self.assertEqual(cost, 6)
        audit.probe_mlb_failover_runtime(policy)

    def test_confirmation_owner_profile_is_2_credits(self):
        projection = audit.load_json(audit.DEFAULT_PROJECTION)
        spec = projection["consumers"][".github/workflows/nfl-2026-line-capture.yml"]
        policy = audit.load_json(audit.ROOT / spec["policy_file"])
        cost = audit.request_profile_cost(policy, spec["request_profiles"]["confirmation_fallback"])[0]
        self.assertEqual(cost, 2)
        audit.probe_confirmation_runtime(policy)

    def test_trigger_parser_includes_non_schedule_spend_paths(self):
        value = yaml.load(
            "on:\n  push:\n  pull_request:\n  workflow_run:\n  workflow_dispatch:\n  schedule:\n    - cron: '0 * * * *'\n",
            Loader=yaml.BaseLoader,
        )
        self.assertEqual(
            audit.workflow_triggers(value),
            {"push", "pull_request", "workflow_run", "workflow_dispatch", "schedule"},
        )

    def test_undeclared_secret_touching_workflow_fails(self):
        actual = audit.discovered_paid_workflows(audit.load_json(audit.DEFAULT_PROJECTION))
        fake = copy.deepcopy(actual)
        fake[".github/workflows/new-paid-leak.yml"] = {
            "path": Path("new-paid-leak.yml"),
            "text": "secrets.SPORTSEDGE_ODDS_API_KEY",
            "workflow": {"on": {"push": None}},
            "triggers": {"push"},
        }
        with patch.object(audit, "discovered_paid_workflows", return_value=fake):
            with self.assertRaisesRegex(audit.PaidConsumerAuditError, "UNDECLARED_PAID_WORKFLOW"):
                audit.audit()

    def test_stale_declared_workflow_fails(self):
        projection = audit.load_json(audit.DEFAULT_PROJECTION)
        projection["consumers"][".github/workflows/deleted-paid-workflow.yml"] = copy.deepcopy(
            next(iter(projection["consumers"].values()))
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "projection.json"
            path.write_text(json.dumps(projection), encoding="utf-8")
            with self.assertRaisesRegex(audit.PaidConsumerAuditError, "STALE_DECLARED_PAID_WORKFLOW"):
                audit.audit(path)

    def test_cost_drift_fails(self):
        projection = audit.load_json(audit.DEFAULT_PROJECTION)
        projection["consumers"][".github/workflows/closing-line-archive.yml"]["request_profiles"]["game_markets"]["declared_credits_per_call"] = 2
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "projection.json"
            path.write_text(json.dumps(projection), encoding="utf-8")
            with self.assertRaisesRegex(audit.PaidConsumerAuditError, "CREDIT_COST_MISMATCH"):
                audit.audit(path)

    def test_trigger_drift_fails(self):
        projection = audit.load_json(audit.DEFAULT_PROJECTION)
        projection["consumers"][".github/workflows/closing-line-archive.yml"]["triggers"] = ["schedule"]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "projection.json"
            path.write_text(json.dumps(projection), encoding="utf-8")
            with self.assertRaisesRegex(audit.PaidConsumerAuditError, "TRIGGER_SET_MISMATCH"):
                audit.audit(path)

    def test_shared_concurrency_is_mandatory(self):
        projection = audit.load_json(audit.DEFAULT_PROJECTION)
        with self.assertRaisesRegex(audit.PaidConsumerAuditError, "PAID_CONCURRENCY_GROUP_MISMATCH"):
            audit.require_shared_concurrency(
                ".github/workflows/example.yml",
                {"concurrency": {"group": "some-other-group", "cancel-in-progress": "false"}},
                projection,
            )


if __name__ == "__main__":
    unittest.main()
