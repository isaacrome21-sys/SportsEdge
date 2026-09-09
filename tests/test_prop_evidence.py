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
)


def _all_ready() -> dict[str, bool]:
    return {group: True for group in EVIDENCE_GROUPS}


class PropEvidenceTests(unittest.TestCase):
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
