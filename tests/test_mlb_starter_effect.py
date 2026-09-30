"""Audit fix D: strict-prior starting-pitcher run effect."""
import unittest
from datetime import date, timedelta

from sportsedge.generic_market_engine import generic_market_engine_adapter
from sportsedge.mlb_starter_effect import (
    STARTER_EFFECT_BETA,
    STARTER_PRIOR_STARTS,
    apply_starter_effects,
    starter_residual_history,
    starter_run_effect,
)
from sportsedge.v7_distribution import calibrated_full_game_means


def _game(pk, day, away, home, a_score, h_score, a_sp=None, h_sp=None):
    def side(team, score, sp):
        out = {"team": {"id": team}, "score": score}
        if sp is not None:
            out["probablePitcher"] = {"id": sp}
        return out
    return {"gamePk": pk, "officialDate": day.isoformat(), "status": {"abstractGameState": "Final"},
            "teams": {"away": side(away, a_score, a_sp), "home": side(home, h_score, h_sp)}}


def _payload(extra_games=()):
    """Two teams alternate home/away every day; team 2's starter 99 allows 0 runs."""
    start = date(2026, 4, 1)
    days = {}
    for i in range(40):
        day = start + timedelta(days=i)
        home, away = (1, 2) if i % 2 == 0 else (2, 1)
        sp_two = 99 if i % 5 == 0 else 200 + i
        a_sp = sp_two if away == 2 else 300 + i
        h_sp = sp_two if home == 2 else 300 + i
        # Team 1 scores 0 against starter 99, else 5; team 2 always scores 4.
        one_score = 0 if sp_two == 99 else 5
        a_score = one_score if away == 1 else 4
        h_score = one_score if home == 1 else 4
        days.setdefault(day.isoformat(), []).append(_game(1000 + i, day, away, home, a_score, h_score, a_sp, h_sp))
    for g in extra_games:
        days.setdefault(g["officialDate"], []).append(g)
    return {"dates": [{"date": d, "games": gs} for d, gs in sorted(days.items())]}


class StarterEffectTests(unittest.TestCase):
    def test_strong_starter_gets_negative_effect_and_prior_is_strict(self):
        target = date(2026, 5, 11)
        residuals = starter_residual_history(_payload(), target)
        ace = starter_run_effect(residuals, 99, prior_starts=STARTER_PRIOR_STARTS)
        self.assertGreater(ace["starts"], 0)
        self.assertLess(ace["effect_runs"], 0.0)
        # Same-day or later games never enter the history.
        later = _game(9999, target, 1, 2, 30, 0, None, 99)
        again = starter_residual_history(_payload([later]), target)
        self.assertEqual(again[99], residuals[99])

    def test_unknown_or_missing_starter_is_neutral(self):
        residuals = starter_residual_history(_payload(), date(2026, 5, 11))
        self.assertEqual(starter_run_effect(residuals, None, prior_starts=40)["effect_runs"], 0.0)
        self.assertEqual(starter_run_effect(residuals, 123456, prior_starts=40)["effect_runs"], 0.0)

    def test_folded_raw_shift_moves_calibrated_opponent_mean_by_beta_effect(self):
        base_away, base_home = calibrated_full_game_means(4.4, 4.6)
        raw_away, raw_home = apply_starter_effects(4.4, 4.6, away_starter_effect_runs=-0.6, home_starter_effect_runs=0.25)
        away, home = calibrated_full_game_means(raw_away, raw_home)
        self.assertAlmostEqual(home, base_home - 0.6 * STARTER_EFFECT_BETA, places=12)
        self.assertAlmostEqual(away, base_away + 0.25 * STARTER_EFFECT_BETA, places=12)
        self.assertEqual(apply_starter_effects(4.4, 4.6, away_starter_effect_runs=0.0, home_starter_effect_runs=0.0), (4.4, 4.6))

    def test_engine_prices_an_ace_lower_for_the_opponent(self):
        base = {"game_id": "g1", "market": "MONEYLINE", "entity_id": "game", "line": 0.0,
                "side": "HOME", "away_mean_runs": 4.4, "home_mean_runs": 4.4, "simulations": 20000}
        neutral = generic_market_engine_adapter(base)
        raw_away, raw_home = apply_starter_effects(4.4, 4.4, away_starter_effect_runs=-0.6, home_starter_effect_runs=0.0)
        ace_away = generic_market_engine_adapter({**base, "away_mean_runs": raw_away, "home_mean_runs": raw_home})
        self.assertLess(ace_away["model_p"], neutral["model_p"] - 0.03)


if __name__ == "__main__":
    unittest.main()
