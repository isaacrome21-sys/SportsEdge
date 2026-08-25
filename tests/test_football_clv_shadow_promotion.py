import unittest

from sportsedge.core.clv.football import CLVClose, CLVDecision, score_clv, summarize_clv


class FootballCLVShadowPromotionTests(unittest.TestCase):
    def _decision(self, gate_result: str) -> CLVDecision:
        return CLVDecision(
            decision_ts="2026-09-10T23:00:00+00:00",
            game_id="2026_01_AAA_BBB",
            sport="nfl",
            market="spread",
            side="AAA",
            book="book",
            line_at_decision=-3.0,
            price_at_decision=-110,
            model_prob=0.56,
            novig_prob=0.50,
            ev=0.06,
            kelly_frac=0.02,
            stake_units=0.5,
            gate_result=gate_result,
        )

    def _close(self) -> CLVClose:
        return CLVClose(
            game_id="2026_01_AAA_BBB",
            market="spread",
            side="AAA",
            closing_line=-3.0,
            closing_price=-115,
            closing_novig_prob=0.53,
            probability_line=-3.0,
            book="book",
        )

    def test_shadow_qualified_observation_populates_promotion_evidence(self):
        summary = summarize_clv(score_clv([self._decision("SHADOW_QUALIFIED")], [self._close()]))
        self.assertIn(("nfl", "spread", "PROMOTION"), summary)
        self.assertEqual(summary[("nfl", "spread", "PROMOTION")].n, 1)

    def test_deployed_official_observation_remains_promotion_grade(self):
        summary = summarize_clv(score_clv([self._decision("OFFICIAL")], [self._close()]))
        self.assertIn(("nfl", "spread", "PROMOTION"), summary)

    def test_rejected_observation_never_populates_promotion_bucket(self):
        summary = summarize_clv(score_clv([self._decision("REJECTED_EV")], [self._close()]))
        self.assertIn(("nfl", "spread", "REJECTED"), summary)
        self.assertNotIn(("nfl", "spread", "PROMOTION"), summary)


if __name__ == "__main__":
    unittest.main()
