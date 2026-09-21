import json
from pathlib import Path
import unittest

from sportsedge.sports.nfl.prop_challenger_contract import (
    PROP_CARD_SCHEMA,
    PROP_LEDGER_DIR,
    PROP_LEDGER_SCHEMA,
    PropContractError,
    apply_frozen_context,
    build_prop_card,
    make_prop_ledger,
    prepare_pit_role,
)
from sportsedge.sports.nfl.prop_role_challenger import PropQuoteEvaluation


class NFLPropChallengerContractTests(unittest.TestCase):
    def _projected(self):
        return {
            "pass_attempts": 34.0,
            "rush_attempts": 3.0,
            "targets": 8.0,
            "retrieved_at": "2026-09-21T16:00:00Z",
            "source": "PREGAME_DEPTH_CHART",
        }

    def _history(self):
        return [
            {"game_id": "g-prev-1", "observed_at": "2026-09-08T23:00:00Z", "pass_attempts": 31, "rush_attempts": 2, "targets": 7},
            {"game_id": "g-prev-2", "observed_at": "2026-09-15T23:00:00Z", "pass_attempts": 36, "rush_attempts": 3, "targets": 9},
        ]

    def _ev(self, entity, market, ev, edge):
        return PropQuoteEvaluation(
            entity_id=entity,
            market=market,
            side="OVER",
            line=10.5,
            book="DraftKings",
            price_american=-110,
            estimate_p=0.60,
            estimate_p_nonpush=0.60,
            push_p=0.0,
            market_no_vig_p=0.50,
            edge_probability_points=edge,
            ev_per_dollar=ev,
        )

    def test_point_in_time_role_accepts_only_strictly_prior_rows(self):
        result = prepare_pit_role(
            entity_id="p1",
            history=self._history(),
            projected_role=self._projected(),
            as_of="2026-09-21T17:00:00Z",
            current_game_id="g-current",
        )
        self.assertEqual(result.current_game_id, "g-current")
        self.assertEqual(result.projected_role_retrieved_at, "2026-09-21T16:00:00Z")
        self.assertEqual(result.max_history_observed_at, "2026-09-15T23:00:00Z")

    def test_same_game_realized_snaps_are_rejected(self):
        bad_history = self._history() + [{
            "game_id": "g-current",
            "observed_at": "2026-09-21T16:30:00Z",
            "pass_attempts": 1,
            "rush_attempts": 0,
            "targets": 0,
            "same_game_snaps": 12,
        }]
        with self.assertRaisesRegex(PropContractError, "SAME_GAME_REALIZED_USAGE_FORBIDDEN"):
            prepare_pit_role(
                entity_id="p1",
                history=bad_history,
                projected_role=self._projected(),
                as_of="2026-09-21T17:00:00Z",
                current_game_id="g-current",
            )

        projected = dict(self._projected(), actual_same_game_snaps=22)
        with self.assertRaisesRegex(PropContractError, "SAME_GAME_REALIZED_USAGE_FORBIDDEN"):
            prepare_pit_role(
                entity_id="p1",
                history=self._history(),
                projected_role=projected,
                as_of="2026-09-21T17:00:00Z",
                current_game_id="g-current",
            )

    def test_future_role_or_history_timestamp_fails_closed(self):
        projected = dict(self._projected(), retrieved_at="2026-09-21T17:00:01Z")
        with self.assertRaisesRegex(PropContractError, "PROJECTED_ROLE_FROM_FUTURE"):
            prepare_pit_role(
                entity_id="p1", history=self._history(), projected_role=projected,
                as_of="2026-09-21T17:00:00Z", current_game_id="g-current",
            )
        history = self._history() + [{
            "game_id": "g-other", "observed_at": "2026-09-21T17:00:00Z",
            "pass_attempts": 30, "rush_attempts": 2, "targets": 8,
        }]
        with self.assertRaisesRegex(PropContractError, "HISTORY_NOT_STRICTLY_PRIOR"):
            prepare_pit_role(
                entity_id="p1", history=history, projected_role=self._projected(),
                as_of="2026-09-21T17:00:00Z", current_game_id="g-current",
            )

    def test_context_is_versioned_hash_bound_and_zero_authority(self):
        pit = prepare_pit_role(
            entity_id="p1", history=self._history(), projected_role=self._projected(),
            as_of="2026-09-21T17:00:00Z", current_game_id="g-current",
        )
        result = apply_frozen_context(
            pit,
            context={
                "team_proe_z": 0.5,
                "opponent_pass_epa_z": 0.5,
                "opponent_rush_epa_z": -0.25,
                "wind_mph": 18.0,
                "roof_closed": False,
            },
        )
        policy = json.loads(Path("config/research/nfl_prop_challenger_context_v1.json").read_text())
        self.assertEqual(result.policy_id, "NFL_PROP_CHALLENGER_CONTEXT_V1")
        self.assertEqual(len(result.policy_sha256), 64)
        self.assertFalse(any(policy["authority"].values()))
        self.assertLess(result.multipliers["pass_volume_multiplier"], 1.0)

    def test_prop_card_is_separate_lane_and_ledger(self):
        card = build_prop_card([
            self._ev("p1", "RUSHING_YARDS", 0.10, 5.0),
            self._ev("p2", "RECEIVING_YARDS", 0.08, 4.0),
        ])
        self.assertEqual(card.schema, PROP_CARD_SCHEMA)
        self.assertNotEqual(PROP_CARD_SCHEMA, "SPORTSEDGE_NFL_RUN_IT_CARD_V2")
        ledger = make_prop_ledger(card, card_id="card-1", captured_at="2026-09-21T17:00:00Z")
        self.assertEqual(ledger["schema"], PROP_LEDGER_SCHEMA)
        self.assertEqual(ledger["lane"], "NFL_PROP_RESEARCH")
        self.assertEqual(ledger["ledger_dir"], PROP_LEDGER_DIR)
        self.assertNotEqual(PROP_LEDGER_DIR, "ledger/nfl_game_markets")

    def test_correlated_rows_for_same_player_count_once(self):
        card = build_prop_card([
            self._ev("p1", "RUSHING_YARDS", 0.12, 6.0),
            self._ev("p1", "RECEIVING_YARDS", 0.11, 5.0),
            self._ev("p1", "PASSING_TDS", 0.09, 4.0),
            self._ev("p2", "RECEPTIONS", 0.08, 3.0),
        ])
        self.assertEqual(len(card.rows), 4)
        self.assertEqual(card.independent_play_count, 2)
        p1 = [row for row in card.rows if row.entity_id == "p1"]
        self.assertEqual({row.independence_unit_id for row in p1}, {"PLAYER:p1"})
        self.assertEqual({row.correlation_group_id for row in p1}, {"PLAYER:p1"})
        self.assertEqual({row.component for row in p1}, {"YARDAGE", "TD"})
        self.assertEqual({row.component_group_id for row in p1}, {"p1:YARDAGE", "p1:TD"})

    def test_context_policy_change_requires_new_identity(self):
        policy = json.loads(Path("config/research/nfl_prop_challenger_context_v1.json").read_text())
        self.assertIn("new policy_id/version", policy["change_control"])
        self.assertIn("new file hash", policy["change_control"])


if __name__ == "__main__":
    unittest.main()
