import unittest

from sportsedge.core.clv.football import CLVClose, CLVDecision, score_clv


class FootballCLVReferenceLineTests(unittest.TestCase):
    def _decision(self, *, line=-3.0, market="spread", book="book"):
        return CLVDecision(
            decision_ts="2026-09-10T23:00:00+00:00",
            game_id="2026_01_AAA_BBB",
            sport="nfl",
            market=market,
            side="AAA",
            book=book,
            line_at_decision=line,
            price_at_decision=-110,
            model_prob=0.56,
            novig_prob=0.50,
            ev=0.06,
            kelly_frac=0.02,
            stake_units=0.5,
            gate_result="OFFICIAL",
        )

    def test_moved_line_without_same_threshold_probability_fails_closed(self):
        decision = self._decision(line=-3.0)
        close = CLVClose(
            game_id=decision.game_id,
            market=decision.market,
            side=decision.side,
            closing_line=-3.5,
            closing_price=-110,
            closing_novig_prob=0.50,
            probability_line=-3.5,
        )
        with self.assertRaisesRegex(ValueError, "CLV_REFERENCE_LINE_MISMATCH"):
            score_clv([decision], [close])

    def test_alternate_close_at_original_decision_threshold_scores_probability_clv(self):
        decision = self._decision(line=-3.0)
        close = CLVClose(
            game_id=decision.game_id,
            market=decision.market,
            side=decision.side,
            closing_line=-3.5,
            closing_price=-110,
            closing_novig_prob=0.54,
            probability_line=-3.0,
        )
        scored = score_clv([decision], [close])
        self.assertEqual(len(scored), 1)
        self.assertAlmostEqual(scored[0].clv, 0.04)

    def test_legacy_same_line_close_is_comparable_without_explicit_reference(self):
        decision = self._decision(line=-3.0)
        close = CLVClose(
            game_id=decision.game_id,
            market=decision.market,
            side=decision.side,
            closing_line=-3.0,
            closing_price=-108,
            closing_novig_prob=0.53,
        )
        scored = score_clv([decision], [close])
        self.assertAlmostEqual(scored[0].clv, 0.03)

    def test_line_free_market_remains_directly_comparable(self):
        decision = self._decision(line=None, market="moneyline")
        close = CLVClose(
            game_id=decision.game_id,
            market=decision.market,
            side=decision.side,
            closing_line=None,
            closing_price=-120,
            closing_novig_prob=0.55,
        )
        scored = score_clv([decision], [close])
        self.assertAlmostEqual(scored[0].clv, 0.05)

    def test_line_free_decision_rejects_line_bound_probability(self):
        decision = self._decision(line=None, market="moneyline")
        close = CLVClose(
            game_id=decision.game_id,
            market=decision.market,
            side=decision.side,
            closing_line=None,
            closing_price=-120,
            closing_novig_prob=0.55,
            probability_line=-3.0,
        )
        with self.assertRaisesRegex(ValueError, "CLV_REFERENCE_LINE_MISMATCH"):
            score_clv([decision], [close])

    def test_two_books_use_their_own_closing_probabilities(self):
        decision_a = self._decision(book="book-a")
        decision_b = self._decision(book="book-b")
        close_a = CLVClose(
            game_id=decision_a.game_id,
            market=decision_a.market,
            side=decision_a.side,
            closing_line=-3.0,
            closing_price=-120,
            closing_novig_prob=0.55,
            book="book-a",
        )
        close_b = CLVClose(
            game_id=decision_b.game_id,
            market=decision_b.market,
            side=decision_b.side,
            closing_line=-3.0,
            closing_price=100,
            closing_novig_prob=0.48,
            book="book-b",
        )
        scored = score_clv([decision_a, decision_b], [close_a, close_b])
        by_book = {row.decision.book: row.clv for row in scored}
        self.assertAlmostEqual(by_book["book-a"], 0.05)
        self.assertAlmostEqual(by_book["book-b"], -0.02)


if __name__ == "__main__":
    unittest.main()
