from __future__ import annotations

import unittest

from sportsedge.prop_evidence import (
    EVIDENCE_GROUPS,
    FIRST_HR_ORDERING,
    HITTER_EVENT_TYPE,
    HITTER_PA,
    HITTER_RUN_SEQUENCE,
    MARKET_EVIDENCE_DEPENDENCIES,
    PITCHER_EVENT_ALLOWED,
    PITCHER_WORKLOAD,
    PropEvidenceError,
    assess_prop_evidence,
    dependent_hitter_markets,
    dependent_pitcher_markets,
    evaluate_group_evidence_row,
    expected_market_identities,
    group_state_from_registry,
)


AS_OF_UTC = "2026-09-14T23:00:00Z"


def _all_ready() -> dict[str, bool]:
    return {group: True for group in EVIDENCE_GROUPS}


def _registry(status: str = "PASS") -> dict:
    rows = {}
    for group in EVIDENCE_GROUPS:
        row = {"status": status}
        if status == "PASS":
            row["evidence_sha256"] = "a" * 64
        rows[group] = row
    return {"schema_version": 1, "groups": rows}


def _complete_group_row(group: str) -> dict:
    return {
        "status": "PASS",
        "evidence_sha256": "a" * 64,
        "evidence_group": group,
        "market_identities": list(expected_market_identities(group)),
        "captured_at_utc": "2026-09-14T22:00:00Z",
        "valid_through_utc": "2026-09-15T23:00:00Z",
    }


class PropEvidenceTests(unittest.TestCase):
    def test_registry_pass_requires_evidence_hash(self):
        payload = _registry()
        payload["groups"][HITTER_PA] = {"status": "PASS"}
        with self.assertRaisesRegex(PropEvidenceError, "HITTER_PA PASS requires evidence_sha256"):
            group_state_from_registry(payload)

    def test_registry_missing_group_resolves_false(self):
        payload = _registry()
        payload["groups"][HITTER_PA] = {"status": "MISSING"}
        state = group_state_from_registry(payload)
        self.assertFalse(state[HITTER_PA])
        self.assertTrue(state[HITTER_EVENT_TYPE])

    def test_every_group_missing_fails_closed(self):
        for group in sorted(EVIDENCE_GROUPS):
            with self.subTest(group=group):
                result = evaluate_group_evidence_row(
                    group=group,
                    row={"status": "MISSING"},
                    as_of_utc=AS_OF_UTC,
                )
                self.assertFalse(result.passed)
                self.assertIn("STATUS_NOT_PASS", result.blockers)

    def test_every_group_partial_pass_evidence_fails_closed(self):
        for group in sorted(EVIDENCE_GROUPS):
            with self.subTest(group=group):
                row = _complete_group_row(group)
                del row["valid_through_utc"]
                result = evaluate_group_evidence_row(
                    group=group,
                    row=row,
                    as_of_utc=AS_OF_UTC,
                )
                self.assertFalse(result.passed)
                self.assertIn("EVIDENCE_METADATA_INCOMPLETE:valid_through_utc", result.blockers)

    def test_every_group_stale_evidence_fails_closed(self):
        for group in sorted(EVIDENCE_GROUPS):
            with self.subTest(group=group):
                row = _complete_group_row(group)
                row["valid_through_utc"] = "2026-09-14T22:59:59Z"
                result = evaluate_group_evidence_row(
                    group=group,
                    row=row,
                    as_of_utc=AS_OF_UTC,
                )
                self.assertFalse(result.passed)
                self.assertIn("EVIDENCE_STALE", result.blockers)

    def test_every_group_wrong_market_identity_fails_closed(self):
        for group in sorted(EVIDENCE_GROUPS):
            with self.subTest(group=group):
                row = _complete_group_row(group)
                row["market_identities"] = ["MONEYLINE"]
                result = evaluate_group_evidence_row(
                    group=group,
                    row=row,
                    as_of_utc=AS_OF_UTC,
                )
                self.assertFalse(result.passed)
                self.assertIn("MARKET_IDENTITY_MISMATCH", result.blockers)

    def test_every_group_wrong_component_identity_fails_closed(self):
        groups = sorted(EVIDENCE_GROUPS)
        for index, group in enumerate(groups):
            with self.subTest(group=group):
                row = _complete_group_row(group)
                row["evidence_group"] = groups[(index + 1) % len(groups)]
                result = evaluate_group_evidence_row(
                    group=group,
                    row=row,
                    as_of_utc=AS_OF_UTC,
                )
                self.assertFalse(result.passed)
                self.assertIn("EVIDENCE_GROUP_IDENTITY_MISMATCH", result.blockers)

    def test_complete_fresh_identity_bound_evidence_is_evaluator_pass(self):
        for group in sorted(EVIDENCE_GROUPS):
            with self.subTest(group=group):
                result = evaluate_group_evidence_row(
                    group=group,
                    row=_complete_group_row(group),
                    as_of_utc=AS_OF_UTC,
                )
                self.assertTrue(result.passed)
                self.assertEqual(result.blockers, ())

    def test_hitter_pa_failure_blocks_every_dependent_hitter_market(self):
        state = _all_ready()
        state[HITTER_PA] = False
        hitter_markets = dependent_hitter_markets()
        self.assertIn("HITS", hitter_markets)
        self.assertIn("FIRST_HOME_RUN", hitter_markets)
        self.assertIn("HITS_RUNS_RBIS", hitter_markets)

        for market in hitter_markets:
            with self.subTest(market=market):
                result = assess_prop_evidence(
                    market=market,
                    group_state=state,
                    calibration_consistent=True,
                )
                self.assertFalse(result.ready_for_forward_capture)
                self.assertIn(HITTER_PA, result.missing_groups)
                self.assertIn(f"EVIDENCE_GROUP_MISSING:{HITTER_PA}", result.blockers)

    def test_hitter_event_type_failure_does_not_block_pitcher_lane(self):
        state = _all_ready()
        state[HITTER_EVENT_TYPE] = False
        hitter = assess_prop_evidence(
            market="TOTAL_BASES", group_state=state, calibration_consistent=True
        )
        pitcher = assess_prop_evidence(
            market="PITCHER_K", group_state=state, calibration_consistent=True
        )
        self.assertFalse(hitter.ready_for_forward_capture)
        self.assertIn(HITTER_EVENT_TYPE, hitter.missing_groups)
        self.assertTrue(pitcher.ready_for_forward_capture)

    def test_run_sequence_only_blocks_markets_that_depend_on_run_state(self):
        state = _all_ready()
        state[HITTER_RUN_SEQUENCE] = False
        run_market = assess_prop_evidence(
            market="RBI", group_state=state, calibration_consistent=True
        )
        simple_event_market = assess_prop_evidence(
            market="HITS", group_state=state, calibration_consistent=True
        )
        self.assertFalse(run_market.ready_for_forward_capture)
        self.assertIn(HITTER_RUN_SEQUENCE, run_market.missing_groups)
        self.assertTrue(simple_event_market.ready_for_forward_capture)

    def test_first_home_run_requires_ordering_in_addition_to_pa_and_event_type(self):
        state = _all_ready()
        state[FIRST_HR_ORDERING] = False
        result = assess_prop_evidence(
            market="FIRST_HOME_RUN", group_state=state, calibration_consistent=True
        )
        self.assertFalse(result.ready_for_forward_capture)
        self.assertEqual(result.missing_groups, (FIRST_HR_ORDERING,))
        self.assertEqual(
            MARKET_EVIDENCE_DEPENDENCIES["FIRST_HOME_RUN"],
            frozenset({HITTER_PA, HITTER_EVENT_TYPE, FIRST_HR_ORDERING}),
        )

    def test_pitcher_workload_failure_blocks_every_dependent_pitcher_market(self):
        state = _all_ready()
        state[PITCHER_WORKLOAD] = False
        pitcher_markets = dependent_pitcher_markets()
        self.assertIn("PITCHER_OUTS", pitcher_markets)
        self.assertIn("PITCHER_K", pitcher_markets)
        self.assertIn("PITCHER_RECORD_WIN", pitcher_markets)

        for market in pitcher_markets:
            with self.subTest(market=market):
                result = assess_prop_evidence(
                    market=market,
                    group_state=state,
                    calibration_consistent=True,
                )
                self.assertFalse(result.ready_for_forward_capture)
                self.assertIn(PITCHER_WORKLOAD, result.missing_groups)

    def test_pitcher_event_allowed_is_not_required_for_pure_workload_lane(self):
        state = _all_ready()
        state[PITCHER_EVENT_ALLOWED] = False
        outs = assess_prop_evidence(
            market="PITCHER_OUTS", group_state=state, calibration_consistent=True
        )
        strikeouts = assess_prop_evidence(
            market="PITCHER_K", group_state=state, calibration_consistent=True
        )
        self.assertTrue(outs.ready_for_forward_capture)
        self.assertFalse(strikeouts.ready_for_forward_capture)
        self.assertIn(PITCHER_EVENT_ALLOWED, strikeouts.missing_groups)

    def test_calibration_consistency_cannot_substitute_for_primary_evidence(self):
        result = assess_prop_evidence(
            market="HITS",
            group_state={},
            calibration_consistent=True,
        )
        self.assertFalse(result.ready_for_forward_capture)
        self.assertEqual(result.calibration_consistency, "CONSISTENT")
        self.assertEqual(set(result.missing_groups), {HITTER_PA, HITTER_EVENT_TYPE})

    def test_calibration_inconsistency_is_veto_not_independent_evidence(self):
        result = assess_prop_evidence(
            market="HITS",
            group_state=_all_ready(),
            calibration_consistent=False,
        )
        self.assertFalse(result.ready_for_forward_capture)
        self.assertEqual(result.missing_groups, ())
        self.assertEqual(result.blockers, ("CALIBRATION_CONSISTENCY_FAILED",))

    def test_unestablished_calibration_fails_closed_without_inventing_result(self):
        result = assess_prop_evidence(
            market="HITS",
            group_state=_all_ready(),
            calibration_consistent=None,
        )
        self.assertFalse(result.ready_for_forward_capture)
        self.assertEqual(result.calibration_consistency, "NOT_ESTABLISHED")
        self.assertIn("CALIBRATION_CONSISTENCY_NOT_ESTABLISHED", result.blockers)

    def test_unmapped_prop_market_fails_closed(self):
        with self.assertRaisesRegex(PropEvidenceError, "UNMAPPED_PROP_MARKET"):
            assess_prop_evidence(
                market="NOT_A_REAL_PROP",
                group_state=_all_ready(),
                calibration_consistent=True,
            )

    def test_unknown_evidence_group_is_rejected(self):
        with self.assertRaisesRegex(PropEvidenceError, "unknown evidence groups"):
            assess_prop_evidence(
                market="HITS",
                group_state={**_all_ready(), "FAKE_GROUP": True},
                calibration_consistent=True,
            )


if __name__ == "__main__":
    unittest.main()