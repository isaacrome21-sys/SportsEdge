from __future__ import annotations

import unittest

from sportsedge.sports.cfb.decision_policy import (
    CFB_EDGE_FLOOR_SCOPE,
    CFB_LIVE_EDGE_FLOOR,
    historical_candidate_policy,
    live_candidate_decision,
)


class CFBEdgeFloorScopeTests(unittest.TestCase):
    def test_scope_is_per_candidate_not_portfolio(self):
        self.assertEqual(CFB_EDGE_FLOOR_SCOPE, "PER_CANDIDATE_DECISION")
        self.assertEqual(CFB_LIVE_EDGE_FLOOR, 0.03)
        for edge in (0.029, 0.020):
            historical = historical_candidate_policy(
                edge=edge,
                ev_per_dollar=0.05,
                quote_fresh=True,
                two_sided=True,
                data_quality_ok=True,
                pit_ok=True,
                coverage_ok=True,
                policy_sha_ok=True,
            )
            live = live_candidate_decision(
                edge=edge,
                ev_per_dollar=0.05,
                quote_fresh=True,
                two_sided=True,
                exposure_ok=True,
                data_quality_ok=True,
                coverage_ok=True,
                override_log_complete=True,
                policy_sha_ok=True,
                historical_status="OFFICIAL",
            )
            self.assertEqual(historical.status, "NO_BET")
            self.assertEqual(live.status, "NO_BET")

    def test_candidate_at_floor_can_qualify_but_exposure_can_only_reduce(self):
        qualified = live_candidate_decision(
            edge=0.03,
            ev_per_dollar=0.01,
            quote_fresh=True,
            two_sided=True,
            exposure_ok=True,
            data_quality_ok=True,
            coverage_ok=True,
            override_log_complete=True,
            policy_sha_ok=True,
            historical_status="OFFICIAL",
        )
        blocked_by_exposure = live_candidate_decision(
            edge=0.03,
            ev_per_dollar=0.01,
            quote_fresh=True,
            two_sided=True,
            exposure_ok=False,
            data_quality_ok=True,
            coverage_ok=True,
            override_log_complete=True,
            policy_sha_ok=True,
            historical_status="OFFICIAL",
        )
        self.assertEqual(qualified.status, "OFFICIAL_BET")
        self.assertEqual(blocked_by_exposure.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
