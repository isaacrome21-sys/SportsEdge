import unittest

from sportsedge.mlb_pitcher_k_composite_candidate import (
    AUTHORITY,
    PitcherKCompositeCandidateError,
    assert_evaluation_ready,
    build_composite_candidate,
)


def _workload(n=5):
    rows = [
        {
            "batters_faced": 22 + i,
            "number_of_pitches": 86 + i,
            "strikeouts": 5 + (i % 3),
            "outs": 17 + (i % 3),
        }
        for i in range(n)
    ]
    return {
        "schema": "MLB_PITCHER_K_WORKLOAD_CANDIDATE_V1",
        "authority": AUTHORITY,
        "source_contract": "STRICTLY_PRIOR_PITCHING_GAMELOG_ROWS",
        "start_count": n,
        "history": rows,
        "summary": {
            "recent_mean_batters_faced": 24.0,
            "recent_mean_number_of_pitches": 90.0,
            "recent_mean_outs": 18.0,
            "recent_mean_k_per_batter_faced": 0.28,
            "recent_mean_pitches_per_batter_faced": 3.75,
        },
        "deployment": False,
        "model_p_eligible": False,
    }


def _opp(n=5):
    return {
        "market": "PITCHER_K",
        "beta": 1.0,
        "target_rel": 1.08,
        "history_rel": [0.96 + 0.01 * i for i in range(n)],
        "opponent_team_id": 147,
        "validated_in": "#1509",
    }


def _lineup(n=5):
    return {
        "W": 200.0,
        "gamma": 0.5,
        "target_deviation": 1.04,
        "history_deviation": [0.98 + 0.01 * i for i in range(n)],
        "validated_in": "#1540",
    }


class PitcherKCompositeCandidateTests(unittest.TestCase):
    def test_binds_frozen_components_but_cannot_create_model_probability(self):
        got = build_composite_candidate(
            workload=_workload(),
            opp_k_adjustment=_opp(),
            lineup_k_adjustment=_lineup(),
        )
        self.assertEqual(got["authority"], AUTHORITY)
        self.assertEqual(got["market"], "PITCHER_K")
        self.assertEqual(got["start_count"], 5)
        self.assertEqual(got["components"]["opponent_k"]["validated_in"], "#1509")
        self.assertEqual(got["components"]["lineup_k"]["validated_in"], "#1540")
        self.assertFalse(got["evaluation_ready"])
        self.assertFalse(got["deployment"])
        self.assertFalse(got["model_p_eligible"])
        self.assertIsNone(got["probability_formula"])
        self.assertIsNone(got["fit_parameters"])
        self.assertEqual(
            got["missing_components"],
            ["pitcher_whiff_chase_pit_source", "pitcher_handedness_pit_source"],
        )

    def test_lineup_absence_uses_validated_fallback_without_blocking_bundle(self):
        got = build_composite_candidate(
            workload=_workload(),
            opp_k_adjustment=_opp(),
            lineup_k_adjustment=None,
        )
        self.assertIsNone(got["components"]["lineup_k"])
        self.assertEqual(got["lineup_status"], "VALIDATED_FALLBACK_TO_OPP_K")

    def test_history_alignment_is_fail_closed(self):
        with self.assertRaisesRegex(PitcherKCompositeCandidateError, "align"):
            build_composite_candidate(
                workload=_workload(5),
                opp_k_adjustment=_opp(4),
                lineup_k_adjustment=_lineup(5),
            )
        with self.assertRaisesRegex(PitcherKCompositeCandidateError, "align"):
            build_composite_candidate(
                workload=_workload(5),
                opp_k_adjustment=_opp(5),
                lineup_k_adjustment=_lineup(4),
            )

    def test_unvalidated_context_parameters_are_rejected(self):
        opp = _opp()
        opp["beta"] = 0.75
        with self.assertRaisesRegex(PitcherKCompositeCandidateError, "unvalidated opponent-K beta"):
            build_composite_candidate(
                workload=_workload(),
                opp_k_adjustment=opp,
                lineup_k_adjustment=_lineup(),
            )

        lineup = _lineup()
        lineup["gamma"] = 0.75
        with self.assertRaisesRegex(PitcherKCompositeCandidateError, "unvalidated lineup-K"):
            build_composite_candidate(
                workload=_workload(),
                opp_k_adjustment=_opp(),
                lineup_k_adjustment=lineup,
            )

    def test_evaluation_gate_remains_closed_until_skill_pit_sources_exist(self):
        got = build_composite_candidate(
            workload=_workload(),
            opp_k_adjustment=_opp(),
            lineup_k_adjustment=_lineup(),
        )
        with self.assertRaisesRegex(
            PitcherKCompositeCandidateError,
            "pitcher_whiff_chase_pit_source",
        ):
            assert_evaluation_ready(got)


if __name__ == "__main__":
    unittest.main()
