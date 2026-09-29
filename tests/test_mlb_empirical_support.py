import copy
import unittest

from sportsedge.mlb_empirical_support import support_evidence
from sportsedge.mlb_myspari_own_model import myspari_rows, render_markdown
from sportsedge.pitcher_joint_engine import price_pitcher_market


class EmpiricalSupportTests(unittest.TestCase):
    def pair(self, values, line=13.5):
        pool = [dict(outs=v, strikeouts=4, earned_runs=2, hits_allowed=5, walks_allowed=1) for v in values]
        feature = {"features": {"history_pool": pool}, "source_subset_hash": "source-hash"}
        rows = []
        for side in ("OVER", "UNDER"):
            inp = dict(game_id="1", market="PITCHER_OUTS", entity_id="2", line=line,
                       side=side, features=feature["features"])
            result = price_pitcher_market(inp)
            result.update(american_odds=-110, implied_probability=.5,
                          edge=result["model_p"] / (1-result["push_p"]) - .5,
                          reason="OFFICIAL_BLOCKED: historical quote evidence required")
            result["empirical_evidence"] = support_evidence(feature, result)
            rows.append(result)
        return {"results": rows}

    def test_boyd_both_sides_withheld_without_mutating_engine_output(self):
        payload = self.pair([21, 15, 16, 21, 16, 18, 18, 16, 21, 20])
        before = copy.deepcopy(payload)
        rows = myspari_rows(payload)
        self.assertEqual(payload, before)
        self.assertEqual({r["raw_empirical_p"] for r in payload["results"]}, {0., 1.})
        self.assertTrue(all(0.0 < float(r["model_p_raw"]) < 1.0 for r in rows))
        for row in rows:
            self.assertEqual(row["scored_status"], "NO_MODEL")
            for key in ("model_p", "estimate_p", "fair_odds", "edge", "ev_per_dollar"):
                self.assertIsNone(row[key])
            self.assertEqual(row["confidence_score"], 0)
            self.assertEqual(row["star_rating"], 0)
            self.assertIn("EMPIRICAL_TAIL_UNSUPPORTED", row["presentation_reason"])
        text = render_markdown(rows, header="guard")
        self.assertIn("10/10 prior starts over 13.5", text)
        self.assertIn("0/10 prior starts under 13.5", text)
        self.assertNotIn("| 100.0% |", text)

    def test_nine_of_ten_and_complement_are_withheld(self):
        rows = myspari_rows(self.pair([18]*9 + [12]))
        self.assertTrue(all(r["scored_status"] == "NO_MODEL" for r in rows))
        self.assertTrue(all("EMPIRICAL_THIN_TAIL_UNSUPPORTED" in r["presentation_reason"] for r in rows))

    def test_middle_probabilities_are_unchanged(self):
        for wins in (5, 6):
            payload = self.pair([18]*wins + [12]*(10-wins))
            rows = myspari_rows(payload)
            self.assertTrue(all(r["presentation_reason"] is None for r in rows))
            self.assertEqual(sorted(r["model_p"] for r in rows), sorted(r["model_p"] for r in payload["results"]))

    def test_sample_boundary_29_vs_30(self):
        for n, blocked in ((29, True), (30, False)):
            rows = myspari_rows(self.pair([18]*(n-3) + [12]*3))
            # Use a 27/29 empirical tail at n=29; n=30 uses 27/30 exactly at 90%.
            if n == 29:
                rows = myspari_rows(self.pair([18]*27 + [12]*2))
            self.assertEqual(all(r["scored_status"] == "NO_MODEL" for r in rows), blocked)

    def test_unknown_sample_is_not_inferred_from_probability(self):
        payload = self.pair([18]*6 + [12]*4)
        for row in payload["results"]:
            del row["empirical_evidence"]
        rows = myspari_rows(payload)
        self.assertTrue(all("EMPIRICAL_SAMPLE_UNKNOWN" in r["presentation_reason"] for r in rows))

    def test_existing_unpriced_reason_survives(self):
        payload = self.pair([18]*10)
        for row in payload["results"]:
            row.update(model_p=None, reason="STARTER_TBD")
        text = render_markdown(myspari_rows(payload), header="guard")
        self.assertIn("STARTER_TBD", text)
        self.assertNotIn("EMPIRICAL_TAIL_UNSUPPORTED", text)

    def test_hitter_tail_and_weighted_counts(self):
        payload = self.pair([18]*10)
        for row in payload["results"]:
            row.update(engine_version="mlb_hitter_joint_empirical_kernel_v4", market="HOME_RUNS")
            row["empirical_evidence"].update(sample_unit="games", weighted=True)
        text = render_markdown(myspari_rows(payload), header="guard")
        self.assertIn("prior games", text)
        self.assertIn("counts are unweighted", text)

    def test_no_epsilon_edge_for_large_sample_endpoint(self):
        rows = myspari_rows(self.pair([18]*30))
        self.assertTrue(all("EMPIRICAL_BOUNDARY_UNCALIBRATED" in r["presentation_reason"] for r in rows))
        self.assertTrue(all(r["fair_odds"] is None for r in rows))

    def test_evidence_comes_from_exact_pool(self):
        payload = self.pair([18]*9 + [12])
        evidence = payload["results"][0]["empirical_evidence"]
        self.assertEqual((evidence["sample_size"], evidence["wins"], evidence["pushes"]), (10, 9, 0))
        self.assertEqual(evidence["source_subset_hash"], "source-hash")
        self.assertEqual(len(evidence["pool_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
